"""Engine, sessão e inicialização do banco SQLite."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from civic.config import get_settings


class Base(DeclarativeBase):
    """Base declarativa de todos os modelos."""


def _garantir_pasta_sqlite(url: str) -> None:
    """Cria a pasta do arquivo SQLite, se necessário (ignora bancos em memória)."""
    banco = make_url(url).database
    if banco and banco != ":memory:" and not banco.startswith("file:"):
        Path(banco).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def _configurar_sqlite(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def criar_engine(url: str | None = None, **kwargs: Any) -> Engine:
    """Cria uma engine; para SQLite liga foreign keys e WAL em cada conexão."""
    url = url or get_settings().database_url
    if url.startswith("sqlite"):
        _garantir_pasta_sqlite(url)
        connect_args = kwargs.pop("connect_args", {})
        connect_args.setdefault("check_same_thread", False)
        # Coletas longas (PNCP, TSE) escrevem em paralelo com a rotina diária: espera a trava em vez de falhar.
        connect_args.setdefault("timeout", 120)
        engine = create_engine(url, connect_args=connect_args, **kwargs)
        event.listen(engine, "connect", _configurar_sqlite)
        return engine
    return create_engine(url, **kwargs)


engine: Engine = criar_engine()
SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False
)


def get_db() -> Iterator[Session]:
    """Dependency do FastAPI: abre uma sessão por requisição e a fecha ao final."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _adicionar_colunas_novas(bind: Engine, inspetor: Any) -> None:
    """Acrescenta (ALTER TABLE ADD COLUMN) colunas novas em tabelas que já existem.

    Só entram colunas que aceitam nulo ou têm valor padrão simples no modelo; as
    demais ficam para a recriação das tabelas derivadas em `init_db`.
    """
    from sqlalchemy import text

    with bind.begin() as conexao:
        for nome, tabela in Base.metadata.tables.items():
            if not inspetor.has_table(nome):
                continue
            existentes = {c["name"] for c in inspetor.get_columns(nome)}
            for coluna in tabela.columns:
                if coluna.name in existentes:
                    continue
                padrao = coluna.default.arg if coluna.default is not None and not callable(coluna.default.arg) else None
                if isinstance(padrao, bool) or not isinstance(padrao, (int, str)):
                    padrao = None
                if padrao is None and not coluna.nullable:
                    continue
                tipo = coluna.type.compile(dialect=bind.dialect)
                sufixo = f" DEFAULT {padrao!r}" if padrao is not None else ""
                conexao.execute(text(f'ALTER TABLE {nome} ADD COLUMN "{coluna.name}" {tipo}{sufixo}'))


# Tabelas derivadas ou recarregadas por inteiro a cada coleta: se o formato mudar,
# basta recriá-las vazias em vez de migrar.
TABELAS_DERIVADAS = ("alertas", "despesas_municipais", "servidores_municipais", "candidatos")


def init_db(bind: Engine | None = None) -> None:
    """Cria as tabelas que ainda não existem e recria tabelas derivadas desatualizadas."""
    from sqlalchemy import inspect

    from civic import models  # noqa: F401  (registra os modelos no metadata)

    bind = bind or engine
    _adicionar_colunas_novas(bind, inspect(bind))
    inspetor = inspect(bind)
    for nome in TABELAS_DERIVADAS:
        if not inspetor.has_table(nome):
            continue
        existentes = {c["name"] for c in inspetor.get_columns(nome)}
        esperadas = {c.name for c in Base.metadata.tables[nome].columns}
        if not esperadas <= existentes:
            Base.metadata.tables[nome].drop(bind)
    Base.metadata.create_all(bind=bind)
