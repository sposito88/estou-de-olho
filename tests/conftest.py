from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from civic.cleaning import gerar_hash, normalizar_nome
from civic.config import Settings
from civic.database import Base
from civic.models import Deputado, Despesa

AGORA = datetime(2026, 10, 7, 12, 0, 0)


@pytest.fixture(autouse=True)
def _sem_limite_de_consultas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Os testes fazem muitas consultas seguidas do mesmo "IP": o limite fica desligado (há teste próprio)."""
    from civic.config import get_settings

    monkeypatch.setattr(get_settings(), "api_limite_por_minuto", 0)
    # Nenhum teste pode usar o bot, o canal ou o token de administração de produção.
    for campo in ("telegram_bot_token", "telegram_chat_id", "telegram_admin_chat_id", "admin_token"):
        monkeypatch.setattr(get_settings(), campo, None)


@pytest.fixture()
def fabrica() -> Iterator[sessionmaker[Session]]:
    """SQLite em memória compartilhado entre conexões, com todas as tabelas."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture()
def db(fabrica: sessionmaker[Session]) -> Iterator[Session]:
    with fabrica() as sessao:
        yield sessao


SEGREDOS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_ADMIN_CHAT_ID", "ADMIN_TOKEN", "TRANSPARENCIA_API_KEY")


@pytest.fixture()
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for nome in SEGREDOS:  # variáveis do ambiente (ex.: contêiner com o .env de produção) não entram nos testes
        monkeypatch.delenv(nome, raising=False)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def deputado(id_: int, nome: str, partido: str = "PT", uf: str = "SP") -> Deputado:
    return Deputado(
        id=id_,
        nome=nome,
        nome_normalizado=normalizar_nome(nome) or "",
        sigla_partido=partido,
        sigla_uf=uf,
        url_foto=f"https://exemplo/{id_}.jpg",
        id_legislatura=57,
        atualizado_em=AGORA,
    )


def despesa(
    deputado_id: int,
    ano: int,
    mes: int,
    liquido: int,
    *,
    cnpj: str | None = "12345678000195",
    fornecedor: str = "Fornecedor X",
    num: str = "1",
    data: date | None = None,
    tipo: str = "COMBUSTÍVEIS",
    tipo_documento: str = "Nota Fiscal",
    documento: int | None = None,
) -> Despesa:
    """Despesa de teste; `documento` (valor da nota) padrão = `liquido`."""
    documento = liquido if documento is None else documento
    data = data if data is not None else date(ano, mes, 10)
    return Despesa(
        hash_unico=gerar_hash(deputado_id, ano, mes, None, num, cnpj, documento, 0),
        deputado_id=deputado_id,
        ano=ano,
        mes=mes,
        data_documento=data,
        tipo_despesa=tipo,
        tipo_documento=tipo_documento,
        num_documento=num,
        cod_documento=None,
        fornecedor=fornecedor,
        cnpj_cpf=cnpj,
        tipo_pessoa="PJ" if cnpj and len(cnpj) == 14 else ("PF" if cnpj else None),
        valor_documento_centavos=documento,
        valor_glosa_centavos=documento - liquido,
        valor_liquido_centavos=liquido,
        url_documento=None,
        parcela=0,
    )
