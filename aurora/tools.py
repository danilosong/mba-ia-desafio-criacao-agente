"""Tools dos agentes.

Nenhuma tool recebe apartamento: ele sempre vem do state da sessão, gravado uma
única vez na criação da sessão.
"""

from datetime import date
from typing import Literal

from google.adk.tools import FunctionTool, ToolContext

from aurora import banco
from aurora.regulamento import CAPITULOS

AREAS = {area["id"]: area for area in banco.ler_json("areas.json")}
LIMITE_DE_CAPITULOS_POR_TURNO = 2

AreaId = Literal[tuple(AREAS)]
Assunto = Literal[tuple(CAPITULOS)]


def _apartamento(tool_context: ToolContext) -> str:
    return tool_context.state["apartamento"]


def _data_valida(data: str) -> bool:
    try:
        return date.fromisoformat(data).isoformat() == data
    except ValueError:
        return False


def _entrada_invalida(area: str, data: str) -> dict | None:
    if area not in AREAS:
        return {"status": "erro", "mensagem": f"Área desconhecida. Use uma de: {', '.join(AREAS)}."}
    if not _data_valida(data):
        return {"status": "erro", "mensagem": "Data inválida. Use o formato AAAA-MM-DD."}
    return None


def listar_minhas_reservas(tool_context: ToolContext) -> dict:
    """Lista as reservas ativas do apartamento do morador autenticado."""
    return {"status": "ok", "reservas": banco.listar_reservas(_apartamento(tool_context))}


def verificar_disponibilidade(area: AreaId, data: str) -> dict:
    """Informa se uma área está livre ou ocupada em uma data.

    Args:
        area: Id da área comum.
        data: Data no formato AAAA-MM-DD.
    """
    if erro := _entrada_invalida(area, data):
        return erro
    return {"status": "ok", "disponibilidade": "livre" if banco.data_livre(area, data) else "ocupada"}


def reservar_area(area: AreaId, data: str, tool_context: ToolContext) -> dict:
    """Reserva uma área comum para o apartamento do morador autenticado.

    Args:
        area: Id da área comum.
        data: Data no formato AAAA-MM-DD.
    """
    if erro := _entrada_invalida(area, data):
        return erro
    codigo = banco.criar_reserva(_apartamento(tool_context), area, data)
    if codigo is None:
        return {"status": "recusada", "mensagem": "A reserva foi recusada: essa data já está ocupada."}
    return {"status": "ok", "codigo": codigo, "mensagem": f"Reserva {codigo} criada para {data}."}


def cancelar_reserva(area: AreaId, data: str, tool_context: ToolContext) -> dict:
    """Cancela uma reserva do próprio apartamento do morador autenticado.

    Args:
        area: Id da área comum.
        data: Data da reserva no formato AAAA-MM-DD.
    """
    if erro := _entrada_invalida(area, data):
        return erro
    codigo = banco.cancelar_reserva(_apartamento(tool_context), area, data)
    if codigo is None:
        return {"status": "nao_encontrada", "mensagem": "Seu apartamento não tem reserva dessa área nessa data."}
    return {"status": "ok", "codigo": codigo, "mensagem": f"Reserva {codigo} cancelada."}


def listar_meus_visitantes(tool_context: ToolContext) -> dict:
    """Lista os visitantes autorizados pelo apartamento do morador autenticado."""
    return {"status": "ok", "visitantes": banco.listar_visitantes(_apartamento(tool_context))}


def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict:
    """Autoriza a entrada de um visitante no prédio.

    Args:
        nome: Nome do visitante.
        data: Data da visita no formato AAAA-MM-DD.
    """
    nome = nome.strip()
    if not nome:
        return {"status": "erro", "mensagem": "Informe o nome do visitante."}
    if not _data_valida(data):
        return {"status": "erro", "mensagem": "Data inválida. Use o formato AAAA-MM-DD."}
    banco.criar_visitante(_apartamento(tool_context), nome, data)
    return {"status": "ok", "mensagem": f"Entrada de {nome} autorizada para {data}."}


def consultar_regulamento(assunto: Assunto, tool_context: ToolContext) -> dict:
    """Devolve o único capítulo do regulamento que trata do assunto informado.

    Args:
        assunto: Assunto do capítulo a consultar.
    """
    consultados = tool_context.state.get("temp:capitulos_consultados", 0)
    if consultados >= LIMITE_DE_CAPITULOS_POR_TURNO:
        return {"status": "limite", "mensagem": "Limite de capítulos por pergunta atingido."}
    tool_context.state["temp:capitulos_consultados"] = consultados + 1
    return {"status": "ok", "capitulo": CAPITULOS[assunto]}


def reserva_gera_cobranca(area: str, data: str, tool_context: ToolContext) -> bool:
    """Regra de negócio 2: decide a confirmação pela taxa cadastrada, não pelo modelo."""
    return area in AREAS and AREAS[area]["taxa"] > 0


TOOLS_RESERVAS = [
    listar_minhas_reservas,
    verificar_disponibilidade,
    FunctionTool(reservar_area, require_confirmation=reserva_gera_cobranca),
    cancelar_reserva,
]
TOOLS_VISITANTES = [
    listar_meus_visitantes,
    FunctionTool(autorizar_visitante, require_confirmation=True),
]
