"""Caminhos e configuração lidos do ambiente."""

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

DADOS = RAIZ / "dados"
VAR = RAIZ / "var"
BANCO_CONDOMINIO = VAR / "condominio.db"
BANCO_SESSOES = VAR / "sessoes.db"

MODELO_PADRAO = "gemini-3.6-flash"


def nome_do_modelo() -> str:
    return os.getenv("GEMINI_MODEL") or MODELO_PADRAO
