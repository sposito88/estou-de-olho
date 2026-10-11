"""O banco de exemplo (`python -m civic.demo`) precisa alimentar todas as páginas principais."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from civic import busca, demo, queries
from civic.alertas import recalcular_alertas
from civic.api import app
from civic.config import get_settings
from civic.database import get_db


@pytest.fixture()
def cliente(fabrica: sessionmaker[Session]) -> Iterator[TestClient]:
    with fabrica() as db:
        demo.popular(db)
        contagem = recalcular_alertas(db, get_settings())
        busca.reconstruir_indice(db)
    assert contagem.get("servidor_socio", 0) >= 1  # a secretária sócia da construtora (um por órgão pagador)
    queries._MEDIANAS_CACHE.clear()

    def _db() -> Iterator[Session]:
        with fabrica() as sessao:
            yield sessao

    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.parametrize("caminho", [
    "/api/gastos/resumo", "/api/gastos/ranking", "/api/alertas", "/api/municipios/PE/Vila Exemplo/cota",
    "/api/municipios/PE/Vila Exemplo/emendas", "/api/municipios/PE/Vila Exemplo/emenda-pix",
    "/api/municipios/PE/Vila Exemplo/prefeitura", "/api/municipios/PE/Vila Exemplo/camara",
    "/api/municipios/PE/Vila Exemplo/pessoal", "/api/municipios/PE/Vila Exemplo/contratos",
    "/api/municipios/PE/Vila Exemplo/contas", "/api/municipios/PE/Vila Exemplo/eleitos",
    "/api/fornecedores/99000001000101", "/api/busca?q=maria exemplar", "/api/deputados/900001/gastos",
])
def test_paginas_com_dados_de_exemplo(cliente: TestClient, caminho: str) -> None:
    resposta = cliente.get(caminho)
    assert resposta.status_code == 200, (caminho, resposta.text[:300])
