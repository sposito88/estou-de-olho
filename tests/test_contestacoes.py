from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from civic.alertas import pontuar
from civic.api import app
from civic.config import get_settings
from civic.database import get_db
from civic.models import Contestacao

PEDIDO = {
    "tipo": "resposta",
    "url": "/fornecedores/25301353000152",
    "alvo": "Alerta: servidor sócio de fornecedor",
    "mensagem": "Sou o sócio citado. Deixei o cargo em 2022, antes dos contratos; segue a portaria de exoneração.",
    "nome": "Fulano",
    "contato": "fulano@example.org",
}


@pytest.fixture()
def cliente(fabrica: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    s = get_settings()
    monkeypatch.setattr(s, "admin_token", SecretStr("segredo"))
    monkeypatch.setattr(s, "contestacoes_por_dia", 2)

    def _db() -> Iterator[Session]:
        with fabrica() as sessao:
            yield sessao

    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_fluxo_da_contestacao(cliente: TestClient, fabrica: sessionmaker[Session]) -> None:
    r = cliente.post("/api/contestacoes", json=PEDIDO, headers={"X-Forwarded-For": "200.1.1.1"})
    assert r.status_code == 201 and r.json()["status"] == "recebida"
    protocolo = r.json()["protocolo"]
    with fabrica() as db:
        guardado = db.query(Contestacao).one()
        assert guardado.origem_hash and "200.1.1.1" not in guardado.origem_hash  # IP não fica guardado
    # Ainda não analisada: não aparece em público.
    assert cliente.get("/api/contestacoes", params={"url": PEDIDO["url"]}).json()["total"] == 0

    admin = {"X-Admin-Token": "segredo"}
    assert cliente.get("/api/admin/contestacoes").status_code == 401
    lista = cliente.get("/api/admin/contestacoes", headers=admin).json()
    assert lista["itens"][0]["contato"] == "fulano@example.org"
    id_ = lista["itens"][0]["id"]
    r = cliente.patch(f"/api/admin/contestacoes/{id_}", headers=admin,
                      json={"status": "resposta_publicada", "resposta_publica": "Resposta do citado publicada."})
    assert r.status_code == 200 and r.json()["respondido_em"]

    publica = cliente.get("/api/contestacoes", params={"url": PEDIDO["url"]}).json()
    assert publica["total"] == 1 and publica["itens"][0]["protocolo"] == protocolo
    assert "contato" not in publica["itens"][0] and "nome" not in publica["itens"][0]


def test_limites_e_anti_spam(cliente: TestClient, fabrica: sessionmaker[Session]) -> None:
    ip = {"X-Forwarded-For": "10.0.0.9"}
    assert cliente.post("/api/contestacoes", json=PEDIDO, headers=ip).status_code == 201
    assert cliente.post("/api/contestacoes", json=PEDIDO, headers=ip).status_code == 201
    assert cliente.post("/api/contestacoes", json=PEDIDO, headers=ip).status_code == 429
    # Robô preenche o campo invisível: responde "ok" sem gravar.
    assert cliente.post("/api/contestacoes", json={**PEDIDO, "site": "http://spam"},
                        headers={"X-Forwarded-For": "10.0.0.10"}).status_code == 201
    with fabrica() as db:
        assert db.query(Contestacao).count() == 2
    assert cliente.post("/api/contestacoes", json={**PEDIDO, "mensagem": "curta"}).status_code == 422
    assert cliente.post("/api/contestacoes", json={**PEDIDO, "url": "http://fora.com"}).status_code == 422


def test_area_admin_desligada_sem_token(cliente: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "admin_token", None)
    assert cliente.get("/api/admin/contestacoes", headers={"X-Admin-Token": "x"}).status_code == 404


def test_pontuar_alertas() -> None:
    fraco = pontuar({"tipo": "empresa_nova", "gravidade": "media", "valor_centavos": 150_000})  # R$ 1.500
    forte = pontuar({"tipo": "servidor_socio", "gravidade": "alta", "valor_centavos": 578_914_952})  # R$ 5,8 mi
    assert fraco < 20 and forte >= 80
    combinado = pontuar({"tipo": "empresa_nova", "gravidade": "media", "valor_centavos": 150_000}, tipos_do_cnpj=3)
    assert combinado == fraco + 20
    assert pontuar({"tipo": "pix_parado", "gravidade": "alta", "valor_centavos": 10**12}, 5) == 100
