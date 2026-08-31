"""Banco do módulo de Ações — separado do banco do bot (`tradingbot.persistence`) por
desenho, não por acidente: specs/00 e CLAUDE.md exigem que os dois módulos nunca
compartilhem estado, dado, modelo ou runtime, só fundação de engenharia. Mesmo padrão de
`persistence/db.py` (SQLite local por padrão, Postgres via variável de ambiente em
produção), banco físico diferente para que um `DROP`/migração acidental num módulo nunca
alcance o outro.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_SQLITE_PATH = Path(__file__).resolve().parents[4] / "results" / "acoes.db"


class Base(DeclarativeBase):
    pass


def _default_database_url() -> str:
    DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DEFAULT_SQLITE_PATH}"


def get_engine(database_url: str | None = None):
    url = database_url or os.environ.get("ACOES_DATABASE_URL") or _default_database_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def _assert_trigger_exclusao_mutua(engine) -> None:
    """`models.py` registra a trigger de exclusão mútua `universo_elegivel`/
    `universo_exclusao` via `event.listen(..., "after_create", ...)` — mas esse evento só
    dispara quando `create_all` cria tabela nova. Banco existente (restaurado de backup,
    ou criado antes desta trigger existir) nunca ganha a proteção sozinho, e o sintoma é
    silencioso: os testes passam contra banco novo em memória, produção fica exposta
    (achado real, 2026-08-29 — 59 linhas de `universo_elegivel` sobreviventes de um
    reprocessamento que corrigiu a exclusão sem limpar o lado antigo, só descobertas por
    um join manual, meses depois). Falha ruidosamente aqui em vez de deixar a mesma
    corrupção se acumular de novo sem ninguém notar — mesmo princípio do
    `IngestionCountMismatchError`."""
    dialeto = engine.dialect.name
    if dialeto == "postgresql":
        consulta = "SELECT tgname FROM pg_trigger WHERE tgname IN (:t1, :t2)"
    elif dialeto == "sqlite":
        consulta = "SELECT name FROM sqlite_master WHERE type='trigger' AND name IN (:t1, :t2)"
    else:
        return
    with engine.connect() as con:
        encontradas = {
            row[0]
            for row in con.execute(
                text(consulta),
                {"t1": "trg_universo_elegivel_exclusivo", "t2": "trg_universo_exclusao_exclusivo"},
            )
        }
    faltando = {"trg_universo_elegivel_exclusivo", "trg_universo_exclusao_exclusivo"} - encontradas
    if faltando:
        raise RuntimeError(
            f"Trigger(s) de exclusão mútua ausente(s) neste banco: {sorted(faltando)}. "
            "universo_elegivel/universo_exclusao podem acumular o mesmo (data_decisao, "
            "ticker) nos dois lados sem essa proteção. Aplique a DDL de "
            "tradingbot.acoes.models (_TRIGGER_FUNCAO_POSTGRES/_TRIGGER_ELEGIVEL_SQLITE "
            "e pares) manualmente contra este banco antes de continuar."
        )


def get_session_factory(database_url: str | None = None) -> sessionmaker:
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    _assert_trigger_exclusao_mutua(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


_default_session_factory: sessionmaker | None = None


def get_session() -> Session:
    global _default_session_factory
    if _default_session_factory is None:
        _default_session_factory = get_session_factory()
    return _default_session_factory()
