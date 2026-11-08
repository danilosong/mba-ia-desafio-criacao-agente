"""API do assistente. Suba com: uv run uvicorn aurora.api:app --port 8000"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from aurora import banco
from aurora.conversa import (
    Assistente,
    ConfirmacaoInexistente,
    ModeloIndisponivel,
    SessaoInexistente,
)


class NovaSessao(BaseModel):
    apartamento: str


class NovaMensagem(BaseModel):
    texto: str


class RespostaConfirmacao(BaseModel):
    id: str
    confirmado: bool


assistente: Assistente


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI) -> AsyncIterator[None]:
    global assistente
    banco.inicializar()
    assistente = Assistente()
    yield


app = FastAPI(title="Residencial Aurora", lifespan=ciclo_de_vida)


@app.exception_handler(SessaoInexistente)
async def _sessao_inexistente(_: Request, __: SessaoInexistente) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Sessão não encontrada."})


@app.exception_handler(ConfirmacaoInexistente)
async def _confirmacao_inexistente(_: Request, __: ConfirmacaoInexistente) -> JSONResponse:
    return JSONResponse(
        status_code=409, content={"detail": "Não existe confirmação pendente com esse id nesta sessão."}
    )


@app.exception_handler(ModeloIndisponivel)
async def _modelo_indisponivel(_: Request, __: ModeloIndisponivel) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "O assistente está indisponível."})


@app.post("/sessoes", status_code=201)
async def criar_sessao(corpo: NovaSessao) -> dict:
    return {"session_id": await assistente.criar_sessao(corpo.apartamento)}


@app.post("/sessoes/{session_id}/mensagens")
async def enviar_mensagem(session_id: str, corpo: NovaMensagem) -> dict:
    return await assistente.enviar_mensagem(session_id, corpo.texto)


@app.post("/sessoes/{session_id}/confirmacoes")
async def responder_confirmacao(session_id: str, corpo: RespostaConfirmacao) -> dict:
    return await assistente.responder_confirmacao(session_id, corpo.id, corpo.confirmado)


@app.get("/sessoes/{session_id}/eventos")
async def listar_eventos(session_id: str) -> list[dict]:
    sessao = await assistente.obter_sessao(session_id)
    return [e.model_dump(mode="json", by_alias=True, exclude_none=True) for e in sessao.events]


@app.get("/apartamentos/{numero}/reservas")
def reservas_do_apartamento(numero: str) -> list[dict]:
    return banco.listar_reservas(numero)


@app.get("/apartamentos/{numero}/visitantes")
def visitantes_do_apartamento(numero: str) -> list[dict]:
    return banco.listar_visitantes(numero)
