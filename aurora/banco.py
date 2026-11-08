"""Dados do condomínio em SQLite: é aqui que as regras de gravação valem."""

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from aurora.config import BANCO_CONDOMINIO, DADOS, VAR

ESQUEMA = """
CREATE TABLE IF NOT EXISTS reservas (
    codigo      TEXT PRIMARY KEY,
    apartamento TEXT NOT NULL,
    area        TEXT NOT NULL,
    data        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ativa' CHECK (status IN ('ativa', 'cancelada'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uma_reserva_ativa_por_area_e_data
    ON reservas (area, data) WHERE status = 'ativa';
CREATE TABLE IF NOT EXISTS visitantes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    apartamento TEXT NOT NULL,
    nome        TEXT NOT NULL,
    data        TEXT NOT NULL
);
"""


def ler_json(nome: str) -> list[dict]:
    return json.loads((DADOS / nome).read_text(encoding="utf-8"))


@contextmanager
def conexao() -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(BANCO_CONDOMINIO, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def _gravar_estado_inicial(con: sqlite3.Connection) -> None:
    con.executemany(
        "INSERT INTO reservas (codigo, apartamento, area, data)"
        " VALUES (:codigo, :apartamento, :area, :data)",
        ler_json("reservas.json"),
    )
    con.executemany(
        "INSERT INTO visitantes (apartamento, nome, data) VALUES (:apartamento, :nome, :data)",
        ler_json("visitantes.json"),
    )


def inicializar() -> None:
    """Cria o banco e carrega os dados iniciais só se ele ainda estiver vazio."""
    VAR.mkdir(exist_ok=True)
    with conexao() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(ESQUEMA)
        con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT 1 FROM reservas LIMIT 1").fetchone() is None:
            _gravar_estado_inicial(con)
        con.execute("COMMIT")


def restaurar() -> None:
    """Volta reservas e visitantes ao estado dos arquivos de dados/."""
    inicializar()
    with conexao() as con:
        con.execute("BEGIN IMMEDIATE")
        con.execute("DELETE FROM reservas")
        con.execute("DELETE FROM visitantes")
        _gravar_estado_inicial(con)
        con.execute("COMMIT")


def listar_reservas(apartamento: str) -> list[dict]:
    with conexao() as con:
        linhas = con.execute(
            "SELECT codigo, area, data FROM reservas"
            " WHERE apartamento = ? AND status = 'ativa' ORDER BY data, area",
            (apartamento,),
        ).fetchall()
    return [dict(linha) for linha in linhas]


def listar_visitantes(apartamento: str) -> list[dict]:
    with conexao() as con:
        linhas = con.execute(
            "SELECT nome, data FROM visitantes WHERE apartamento = ? ORDER BY data, id",
            (apartamento,),
        ).fetchall()
    return [dict(linha) for linha in linhas]


def data_livre(area: str, data: str) -> bool:
    with conexao() as con:
        linha = con.execute(
            "SELECT 1 FROM reservas WHERE area = ? AND data = ? AND status = 'ativa'",
            (area, data),
        ).fetchone()
    return linha is None


def criar_reserva(apartamento: str, area: str, data: str) -> str | None:
    """Grava a reserva e devolve o código, ou None se a data já estiver ocupada.

    A exclusividade vem do índice único parcial: o próprio INSERT é a conferência,
    então duas gravações simultâneas não têm como passar. Linhas canceladas ficam
    na tabela, e por isso a chave primária também impede reaproveitar o código delas.
    """
    with conexao() as con:
        for _ in range(5):
            codigo = f"RSV-{uuid.uuid4().hex[:12].upper()}"
            try:
                cursor = con.execute(
                    "INSERT INTO reservas (codigo, apartamento, area, data)"
                    " VALUES (?, ?, ?, ?)"
                    " ON CONFLICT (area, data) WHERE status = 'ativa' DO NOTHING",
                    (codigo, apartamento, area, data),
                )
            except sqlite3.IntegrityError:
                continue  # colisão de código: tenta outro
            return codigo if cursor.rowcount == 1 else None
    raise RuntimeError("Não foi possível gerar um código de reserva único.")


def cancelar_reserva(apartamento: str, area: str, data: str) -> str | None:
    """Cancela a reserva ativa do apartamento e devolve o código, se ela existir."""
    with conexao() as con:
        linha = con.execute(
            "UPDATE reservas SET status = 'cancelada'"
            " WHERE apartamento = ? AND area = ? AND data = ? AND status = 'ativa'"
            " RETURNING codigo",
            (apartamento, area, data),
        ).fetchone()
    return linha["codigo"] if linha else None


def criar_visitante(apartamento: str, nome: str, data: str) -> None:
    with conexao() as con:
        con.execute(
            "INSERT INTO visitantes (apartamento, nome, data) VALUES (?, ?, ?)",
            (apartamento, nome, data),
        )
