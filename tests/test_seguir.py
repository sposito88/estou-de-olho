from __future__ import annotations

from collections.abc import Iterator
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from civic import demo
from civic.alertas import recalcular_alertas
from civic.api import app
from civic.config import get_settings
from civic.database import get_db
from civic.models import Alerta

ATOM = "{http://www.w3.org/2005/Atom}"


@pytest.fixture()
def cliente(fabrica: sessionmaker[Session]) -> Iterator[TestClient]:
    with fabrica() as db:
        demo.popular(db)
        recalcular_alertas(db, get_settings())

    def _db() -> Iterator[Session]:
        with fabrica() as sessao:
            yield sessao

    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_primeira_vez_estavel_entre_recalculos(cliente: TestClient, fabrica: sessionmaker[Session]) -> None:
    with fabrica() as db:
        antes = {a.chave: a.primeira_vez for a in db.scalars(select(Alerta))}
        recalcular_alertas(db, get_settings())
        depois = {a.chave: a.primeira_vez for a in db.scalars(select(Alerta))}
    assert antes and antes == depois  # mesmos alertas, mesma chave e mesma data de primeira aparição


def test_alerta_por_id_e_feed(cliente: TestClient) -> None:
    lista = cliente.get("/api/alertas", params={"ordem": "recentes"}).json()
    primeiro = lista["itens"][0]
    assert primeiro["primeira_vez"]
    um = cliente.get(f"/api/alertas/{primeiro['id']}").json()
    assert um["titulo"] == primeiro["titulo"]
    assert cliente.get("/api/alertas/999999").status_code == 404
    assert cliente.get("/api/alertas/resumo").status_code == 200  # rota fixa não é confundida com id

    resposta = cliente.get("/api/alertas/feed.xml", params={"municipio_ibge": "2699901", "titulo": "Vila Exemplo"})
    assert resposta.headers["content-type"].startswith("application/atom+xml")
    raiz = ET.fromstring(resposta.content)
    entradas = raiz.findall(f"{ATOM}entry")
    assert entradas and "Vila Exemplo" in raiz.findtext(f"{ATOM}title")
    assert all("não é acusação" in (e.findtext(f"{ATOM}summary") or "") for e in entradas)
