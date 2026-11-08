"""Execução dos agentes pelo Runner e ciclo de vida das confirmações."""

import asyncio
import logging
from collections import defaultdict

from google.adk.events import Event
from google.adk.flows.llm_flows.functions import REQUEST_CONFIRMATION_FUNCTION_CALL_NAME
from google.adk.runners import Runner
from google.adk.sessions import Session
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.genai import types

from aurora.agentes import NOME_DO_APP, criar_app
from aurora.config import BANCO_SESSOES, VAR
from aurora.tools import AREAS

logger = logging.getLogger(__name__)

USUARIO = "morador"
MENSAGEM_SEM_RESPOSTA = "A ação foi processada, mas não consegui gerar uma resposta agora."


class SessaoInexistente(Exception):
    pass


class ConfirmacaoInexistente(Exception):
    pass


class ModeloIndisponivel(Exception):
    pass


def _pedidos_de_confirmacao(sessao: Session) -> dict[str, tuple[types.FunctionCall, str]]:
    """Mapeia o id de cada pedido de confirmação para a chamada e o agente que pediu."""
    return {
        chamada.id: (chamada, evento.author)
        for evento in sessao.events
        for chamada in evento.get_function_calls()
        if chamada.name == REQUEST_CONFIRMATION_FUNCTION_CALL_NAME
    }


def _ids_respondidos(sessao: Session) -> set[str]:
    return {
        resposta.id
        for evento in sessao.events
        for resposta in evento.get_function_responses()
        if resposta.name == REQUEST_CONFIRMATION_FUNCTION_CALL_NAME
    }


def _descrever(chamada: types.FunctionCall) -> dict:
    original = chamada.args["originalFunctionCall"]
    detalhes = dict(original.get("args") or {})
    if detalhes.get("area") in AREAS:
        detalhes["taxa"] = AREAS[detalhes["area"]]["taxa"]
    return {"id": chamada.id, "acao": original["name"], "detalhes": detalhes}


def confirmacoes_pendentes(sessao: Session) -> list[dict]:
    """Calcula as pendências a partir dos eventos, que sobrevivem ao reinício."""
    respondidos = _ids_respondidos(sessao)
    return [
        _descrever(chamada)
        for id_, (chamada, _) in _pedidos_de_confirmacao(sessao).items()
        if id_ not in respondidos
    ]


def _texto_final(eventos: list[Event]) -> str:
    for evento in reversed(eventos):
        if evento.author == "user" or not evento.content or not evento.content.parts:
            continue
        texto = "".join(p.text for p in evento.content.parts if p.text and not p.thought)
        if texto.strip():
            return texto.strip()
    return ""


def _resultado_da_retomada(sessao: Session, id_confirmacao: str, id_original: str) -> dict | None:
    """Devolve o resultado da tool produzido depois da resposta do morador."""
    apos_resposta = False
    for evento in sessao.events:
        for resposta in evento.get_function_responses():
            if resposta.id == id_confirmacao:
                apos_resposta = True
            elif apos_resposta and resposta.id == id_original:
                return resposta.response or {}
    return None


class Assistente:
    def __init__(self) -> None:
        VAR.mkdir(exist_ok=True)
        self.sessoes = SqliteSessionService(str(BANCO_SESSOES))
        app = criar_app()
        self.runner = Runner(app=app, session_service=self.sessoes)
        # Runner.run_async escolhe o agente antes de anexar a resposta à sessão, então
        # ele não acha quem pediu a confirmação pelo id, e o processador de confirmação
        # ignora em silêncio uma resposta entregue a outro agente. Por isso a retomada
        # usa um Runner fixado no agente autor do pedido, lido dos eventos persistidos.
        self._runners_de_retomada = {
            agente.name: Runner(
                app_name=NOME_DO_APP, agent=agente, session_service=self.sessoes
            )
            for agente in app.root_agent.sub_agents
        }
        self._travas: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def criar_sessao(self, apartamento: str) -> str:
        sessao = await self.sessoes.create_session(
            app_name=NOME_DO_APP, user_id=USUARIO, state={"apartamento": apartamento}
        )
        return sessao.id

    async def obter_sessao(self, session_id: str) -> Session:
        sessao = await self.sessoes.get_session(
            app_name=NOME_DO_APP, user_id=USUARIO, session_id=session_id
        )
        if sessao is None:
            raise SessaoInexistente(session_id)
        return sessao

    async def _executar(
        self, session_id: str, mensagem: types.Content, runner: Runner | None = None
    ) -> str:
        eventos = [
            evento
            async for evento in (runner or self.runner).run_async(
                user_id=USUARIO, session_id=session_id, new_message=mensagem
            )
        ]
        return _texto_final(eventos)

    async def enviar_mensagem(self, session_id: str, texto: str) -> dict:
        await self.obter_sessao(session_id)
        async with self._travas[session_id]:
            mensagem = types.Content(role="user", parts=[types.Part(text=texto)])
            try:
                resposta = await self._executar(session_id, mensagem)
            except Exception as erro:
                logger.exception("Falha ao processar a mensagem")
                raise ModeloIndisponivel from erro
            sessao = await self.obter_sessao(session_id)
            return {"resposta": resposta, "confirmacoes_pendentes": confirmacoes_pendentes(sessao)}

    async def responder_confirmacao(self, session_id: str, id_: str, confirmado: bool) -> dict:
        await self.obter_sessao(session_id)
        async with self._travas[session_id]:
            sessao = await self.obter_sessao(session_id)
            pedidos = _pedidos_de_confirmacao(sessao)
            if id_ in _ids_respondidos(sessao) or id_ not in pedidos:
                raise ConfirmacaoInexistente(id_)
            chamada, autor = pedidos[id_]
            id_original = chamada.args["originalFunctionCall"]["id"]
            mensagem = types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=id_,
                            name=REQUEST_CONFIRMATION_FUNCTION_CALL_NAME,
                            response={"confirmed": confirmado},
                        )
                    )
                ],
            )
            resposta = ""
            try:
                resposta = await self._executar(
                    session_id, mensagem, self._runners_de_retomada.get(autor)
                )
            except Exception:
                # A tool roda antes da chamada ao modelo: uma falha do modelo aqui não
                # desfaz a ação. O resultado real é conferido logo abaixo.
                logger.exception("Falha ao gerar a resposta depois da confirmação")

            sessao = await self.obter_sessao(session_id)
            resultado = _resultado_da_retomada(sessao, id_, id_original)
            if resultado is None:
                raise ModeloIndisponivel("A retomada não chegou à tool que pediu a confirmação.")
            return {
                "resposta": resposta or resultado.get("mensagem") or MENSAGEM_SEM_RESPOSTA,
                "confirmacoes_pendentes": confirmacoes_pendentes(sessao),
            }
