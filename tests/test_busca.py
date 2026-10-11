from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from civic import busca
from civic.api import app
from civic.cleaning import despesa_municipal_do_tce
from civic.database import get_db
from civic.models import (
    Candidato,
    DespesaMunicipal,
    DoacaoCampanha,
    Fornecedor,
    Municipio,
    ServidorMunicipal,
    Socio,
    UnidadeGestora,
)
from tests.conftest import AGORA
from tests.test_pernambuco import EMPENHO

CNPJ = "25301353000152"


def _popular(db: Session) -> None:
    db.add(Municipio(codigo_ibge="2604007", nome="Carpina", nome_normalizado="CARPINA", sigla_uf="PE"))
    db.add(UnidadeGestora(id=169, nome="Prefeitura Municipal de Carpina", natureza="Prefeitura Municipal",
                          codigo_municipio_tce="P042", municipio="Carpina", municipio_normalizado="CARPINA"))
    db.add(Fornecedor(cnpj=CNPJ, razao_social="COLÉGIO CONVERGENTE LTDA", nome_fantasia="COLEGIO CONVERGENTE",
                      situacao_cadastral="ATIVA", municipio="CARPINA", sigla_uf="PE", referencia="2026-09",
                      atualizado_em=AGORA))
    db.flush()
    db.add(DespesaMunicipal(**despesa_municipal_do_tce({**EMPENHO, "ID_UNIDADE_GESTORA": "169", "CPF_CNPJ": CNPJ,
                                                        "FORNECEDOR": "COLEGIO CONVERGENTE", "VALORPAGO": "1000.00"})))
    db.add(DespesaMunicipal(**despesa_municipal_do_tce({**EMPENHO, "ID_EMPENHO": "2", "ID_UNIDADE_GESTORA": "169",
                                                        "FORNECEDOR": "Orlando Francisco da Silva",
                                                        "VALORPAGO": "50.00"})))
    db.add(Socio(cnpj_basico=CNPJ[:8], tipo="PF", nome="ORLANDO FRANCISCO DA SILVA",
                 nome_normalizado="ORLANDO FRANCISCO DA SILVA", documento="931274", qualificacao="Sócio-Administrador"))
    for cargo, ano in (("COORDENADOR", 2017), ("DIRETOR", 2025)):
        db.add(ServidorMunicipal(unidade_gestora_id=169, nome="ORLANDO FRANCISCO DA SILVA",
                                 nome_normalizado="ORLANDO FRANCISCO DA SILVA", cargo=cargo, vinculo="Cargo Comissionado",
                                 data_admissao=date(ano, 1, 15), cpf_meio="931274"))
    # Homônimo com outro CPF: resultado separado.
    db.add(Socio(cnpj_basico=CNPJ[:8], tipo="PF", nome="ORLANDO FRANCISCO DA SILVA",
                 nome_normalizado="ORLANDO FRANCISCO DA SILVA", documento="111111"))
    db.add(Candidato(sq_candidato="9", ano=2024, cargo="VEREADOR", municipio_ibge="2604007", nome="MARIA DAS DORES",
                     nome_normalizado="MARIA DAS DORES", nome_urna="Maria do Povo", sigla_partido="XX", eleito=True))
    db.add(DoacaoCampanha(ano=2024, sq_candidato="9", doador_nome="ORLANDO FRANCISCO DA SILVA",
                          doador_nome_normalizado="ORLANDO FRANCISCO DA SILVA", doador_cpf_meio="931274",
                          valor_centavos=200_000))
    db.commit()


@pytest.fixture()
def cliente(fabrica: sessionmaker[Session]) -> Iterator[TestClient]:
    with fabrica() as db:
        _popular(db)
        contagem = busca.reconstruir_indice(db)
    assert contagem["empresa"] == 1 and contagem["servidor"] == 1 and contagem["socio"] == 2

    def _db() -> Iterator[Session]:
        with fabrica() as sessao:
            yield sessao

    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_busca_agrupa_papeis_da_mesma_pessoa(cliente: TestClient) -> None:
    corpo = cliente.get("/api/busca", params={"q": "orlando  silva"}).json()
    # Mesmo nome com dois CPFs: são duas pessoas; o credor (só nome) não dá para atribuir e fica à parte.
    assert corpo["total"] == 3
    pessoa = corpo["resultados"][0]
    assert pessoa["documento"] == "***.931.274-**"
    assert [p["tipo"] for p in pessoa["papeis"]] == ["servidor", "socio", "doador"]
    servidor = pessoa["papeis"][0]
    assert servidor["papel"] == "DIRETOR (Cargo Comissionado), 2 vínculos" and servidor["ano"] == 2025
    assert servidor["url"] == "/cidade/PE/Carpina/pessoal?busca=ORLANDO FRANCISCO DA SILVA"
    assert pessoa["papeis"][1]["url"] == f"/fornecedores/{CNPJ}"
    assert pessoa["papeis"][2]["valor"] == "2000.00" and pessoa["papeis"][2]["url"] == "/cidade/PE/Carpina/eleitos"
    assert {r["documento"] for r in corpo["resultados"]} == {"***.931.274-**", "***.111.111-**", None}


def test_papel_sem_cpf_de_outro_estado_nao_junta(cliente: TestClient, fabrica: sessionmaker[Session]) -> None:
    with fabrica() as db:
        db.query(Socio).filter(Socio.documento == "111111").delete()
        db.add(UnidadeGestora(id=10_000_000, nome="PREFEITURA MUNICIPAL DE MARACAÍ", natureza="Prefeitura Municipal",
                              codigo_municipio_tce="3528700", municipio="Maracaí", municipio_normalizado="MARACAI",
                              sigla_uf="SP", fonte="TCE-SP"))
        db.flush()
        db.add(DespesaMunicipal(**{**despesa_municipal_do_tce({**EMPENHO, "ID_EMPENHO": "3", "FORNECEDOR":
                                   "ORLANDO FRANCISCO DA SILVA", "VALORPAGO": "10.00"}), "unidade_gestora_id": 10_000_000}))
        db.commit()
        busca.reconstruir_indice(db)
    corpo = cliente.get("/api/busca", params={"q": "orlando francisco"}).json()
    assert corpo["total"] == 2
    pessoa = next(r for r in corpo["resultados"] if r["documento"])
    assert "Maracaí/SP" not in {p["lugar"] for p in pessoa["papeis"]}


def test_papel_sem_cpf_junta_quando_so_ha_uma_pessoa(cliente: TestClient, fabrica: sessionmaker[Session]) -> None:
    with fabrica() as db:
        db.query(Socio).filter(Socio.documento == "111111").delete()
        db.commit()
        busca.reconstruir_indice(db)
    corpo = cliente.get("/api/busca", params={"q": "orlando francisco"}).json()
    [pessoa] = corpo["resultados"]
    assert [p["tipo"] for p in pessoa["papeis"]] == ["servidor", "socio", "doador", "credor"]
    assert pessoa["homonimos_possiveis"] is True  # o credor foi ligado só pelo nome


def test_busca_empresa_por_nome_e_cnpj(cliente: TestClient) -> None:
    por_nome = cliente.get("/api/busca", params={"q": "convergente"}).json()
    [empresa] = por_nome["resultados"]
    assert empresa["tipo_pessoa"] == "PJ" and empresa["documento"] == CNPJ
    assert empresa["papeis"][0]["valor"] == "1000.00" and empresa["papeis"][0]["lugar"] == "CARPINA/PE"
    assert cliente.get("/api/busca", params={"q": CNPJ}).json()["resultados"][0]["titulo"] == "COLÉGIO CONVERGENTE LTDA"
    # Sem acento e pelo nome de urna do candidato.
    assert cliente.get("/api/busca", params={"q": "colegio"}).json()["total"] == 1
    assert cliente.get("/api/busca", params={"q": "maria das"}).json()["resultados"][0]["titulo"] == "Maria do Povo"


def test_termo_curto_ou_sem_indice(cliente: TestClient, fabrica: sessionmaker[Session]) -> None:
    assert cliente.get("/api/busca", params={"q": "ab"}).json()["total"] == 0
    with fabrica() as db:
        assert busca.buscar(db, "orlando")["indice_disponivel"] is True
    assert busca.expressao_fts('a"b c') == '"A"* AND "B"* AND "C"*'  # aspas não quebram a consulta


def test_busca_dentro_da_cidade(cliente: TestClient) -> None:
    carpina = cliente.get("/api/busca", params={"q": "convergente", "uf": "pe", "municipio": "Carpina"}).json()
    assert carpina["cidade"] == "Carpina/PE"
    [empresa] = carpina["resultados"]
    pagamento = next(p for p in empresa["papeis"] if p["tipo"] == "pagamento")
    assert pagamento["orgao"] == "Prefeitura Municipal de Carpina" and pagamento["valor"] == "1000.00"
    assert cliente.get("/api/busca", params={"q": "convergente", "uf": "PE", "municipio": "Recife"}).json()["total"] == 0
    # Na cidade, o servidor aparece; o doador (campanha em Carpina) também.
    pessoa = cliente.get("/api/busca", params={"q": "orlando", "uf": "PE", "municipio": "Carpina"}).json()["resultados"][0]
    assert {"servidor", "doador"} <= {p["tipo"] for p in pessoa["papeis"]}
    assert busca.cidade_token("São José do Egito/PE") == "SAOJOSEDOEGITOPE"
