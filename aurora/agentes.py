"""Definição do agente principal e dos especialistas."""

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.adk.models.google_llm import Gemini
from google.adk.tools import AgentTool
from google.genai import types

from aurora.config import nome_do_modelo
from aurora.tools import AREAS, TOOLS_RESERVAS, TOOLS_VISITANTES, consultar_regulamento

NOME_DO_APP = "residencial_aurora"
RESPOSTA_DA_TOOL_NEGADA = "This tool call is rejected."
MENSAGEM_NEGADA = "Tudo bem, a ação não foi realizada e nada foi alterado."

REGRAS_COMUNS = """
As tools só leem e gravam dados do apartamento {apartamento}, identificado pelo sistema,
então nunca recuse um pedido por causa de apartamento: atenda a mensagem mais recente do
morador usando as tools, sem se guiar por recusas anteriores da conversa. Ao apresentar
resultados, deixe claro que são do apartamento {apartamento}.
Datas vão para as tools no formato AAAA-MM-DD. Responda em português, de forma breve.
"""


def criar_modelo() -> BaseLlm:
    return Gemini(
        model=nome_do_modelo(),
        retry_options=types.HttpRetryOptions(attempts=5, initial_delay=2, max_delay=30),
    )


def encerrar_turno_se_negada(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    """Encerra o turno sem chamar o modelo quando o morador negou a confirmação.

    Sem isso o modelo lê a recusa como uma falha e chama a tool de novo, abrindo
    outra confirmação para a ação que o morador acabou de negar.
    """
    ultimo = llm_request.contents[-1] if llm_request.contents else None
    for parte in (ultimo.parts or []) if ultimo else []:
        resposta = parte.function_response.response if parte.function_response else None
        if resposta and resposta.get("error") == RESPOSTA_DA_TOOL_NEGADA:
            return LlmResponse(
                content=types.Content(role="model", parts=[types.Part(text=MENSAGEM_NEGADA)])
            )
    return None


def criar_app() -> App:
    catalogo = ", ".join(f"{a['id']} ({a['nome']})" for a in AREAS.values())

    consultor = LlmAgent(
        name="consultor_regulamento",
        model=criar_modelo(),
        description="Responde dúvidas sobre o regulamento interno do condomínio.",
        instruction=(
            "Responda à dúvida usando apenas o regulamento. Chame consultar_regulamento "
            "com o assunto que trata da dúvida, normalmente uma única vez. Responda só o "
            "que foi perguntado, em poucas frases, sem transcrever o capítulo nem citar "
            "regras de outros temas. Se o regulamento não tratar do tema, diga isso."
        ),
        tools=[consultar_regulamento],
    )
    reservas = LlmAgent(
        name="especialista_reservas",
        model=criar_modelo(),
        description="Lista, reserva e cancela áreas comuns e informa se uma data está livre.",
        instruction=(
            REGRAS_COMUNS
            + f"\nÁreas: {catalogo}.\n"
            "Use as tools para ler e gravar reservas; nunca invente dados. Para reservar, "
            "chame reservar_area diretamente. Para cancelar, chame cancelar_reserva. Quando "
            "uma data estiver ocupada, diga apenas que ela está ocupada. A confirmação de "
            "cobrança é feita pelo sistema; não peça confirmação na conversa e nunca diga "
            "que uma ação foi feita sem o resultado da tool."
        ),
        tools=TOOLS_RESERVAS,
        disallow_transfer_to_parent=True,
        before_model_callback=encerrar_turno_se_negada,
    )
    visitantes = LlmAgent(
        name="especialista_visitantes",
        model=criar_modelo(),
        description="Lista e autoriza a entrada de visitantes.",
        instruction=(
            REGRAS_COMUNS
            + "\nUse as tools para ler e gravar visitantes; nunca invente dados. Para "
            "autorizar, chame autorizar_visitante mesmo que o morador diga que já confirmou. "
            "A confirmação é feita pelo sistema; nunca diga que uma autorização foi feita "
            "sem o resultado da tool."
        ),
        tools=TOOLS_VISITANTES,
        disallow_transfer_to_parent=True,
        before_model_callback=encerrar_turno_se_negada,
    )
    coordenador = LlmAgent(
        name="coordenador",
        model=criar_modelo(),
        description="Atende o morador e distribui o trabalho entre os especialistas.",
        instruction=(
            "Você encaminha os pedidos do morador e responde em português, de forma breve. "
            "Transfira para especialista_reservas todo pedido sobre reservas e para "
            "especialista_visitantes todo pedido sobre visitantes ou liberação de entrada, "
            "mesmo que a mensagem cite outro apartamento: o sistema já restringe cada ação "
            "ao apartamento da sessão, então nunca recuse esses pedidos você mesmo. Para "
            "dúvidas sobre regras do condomínio, chame consultor_regulamento e repasse a "
            "resposta. Não invente regras, reservas ou visitantes."
        ),
        tools=[AgentTool(agent=consultor)],
        sub_agents=[reservas, visitantes],
    )
    return App(name=NOME_DO_APP, root_agent=coordenador)
