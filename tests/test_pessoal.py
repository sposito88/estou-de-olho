from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from civic import queries
from civic.api import app
from civic.cleaning import despesa_municipal_do_tce
from civic.database import get_db
from civic.models import (
    Candidato,
    DespesaMunicipal,
    DoacaoCampanha,
    Municipio,
    PagamentoMunicipal,
    ServidorMunicipal,
    UnidadeGestora,
)
from tests.test_pernambuco import EMPENHO

INICIO = queries.inicio_mandato_municipal()


def _servidor(nome: str, cargo: str, vinculo: str, admissao: date, cpf_meio: str, ug: int = 169,
              hash_cpf: str | None = None) -> ServidorMunicipal:
    return ServidorMunicipal(unidade_gestora_id=ug, nome=nome, nome_normalizado=nome, cargo=cargo, vinculo=vinculo,
                             data_admissao=admissao, cpf_meio=cpf_meio, hash_cpf=hash_cpf or nome, matricula="1",
                             ano_remessa=INICIO + 1, mes_remessa=8)


def _empenho(chave: str, mes: int, elemento: str, valor: str, fornecedor: str = "SECRETARIA DE EDUCACAO",
             cpf: str = "", historico: str = "FOLHA", ug: str = "169") -> DespesaMunicipal:
    return DespesaMunicipal(**despesa_municipal_do_tce({
        **EMPENHO, "ID_EMPENHO": chave, "ID_UNIDADE_GESTORA": ug, "ANOREFERENCIA": str(INICIO),
        "MESREFERENCIA": str(mes), "DATAEMPENHO": f"{INICIO}-{mes:02d}-05", "ELEMENTODESPESA": elemento,
        "VALORPAGO": valor, "VALOREMPENHADO": valor, "FORNECEDOR": fornecedor, "CPF_CNPJ": cpf, "HISTORICO": historico,
    }))


@pytest.fixture()
def cliente(fabrica: sessionmaker[Session]) -> Iterator[TestClient]:
    with fabrica() as db:
        db.add(Municipio(codigo_ibge="2604007", nome="Carpina", nome_normalizado="CARPINA", sigla_uf="PE"))
        for ug, nome, natureza in ((169, "Prefeitura Municipal de Carpina", "Prefeitura Municipal"),
                                   (170, "Câmara Municipal de Carpina", "Câmara Municipal")):
            db.add(UnidadeGestora(id=ug, nome=nome, natureza=natureza, codigo_municipio_tce="P042",
                                  municipio="Carpina", municipio_normalizado="CARPINA"))
        db.flush()
        db.add_all([
            _servidor("ANA LIMA", "PROFESSOR", "Efetivo / Vitalício", date(2011, 3, 1), "555634"),
            # Mesma pessoa, dois contratos temporários.
            _servidor("JOAO SOUZA", "AUXILIAR", "Contratação por Excepcional Interesse Público", date(INICIO - 1, 2, 1),
                      "111222", hash_cpf="H1"),
            _servidor("JOAO SOUZA", "AUXILIAR", "Contratação por Excepcional Interesse Público", date(INICIO, 2, 1),
                      "111222", hash_cpf="H1"),
            _servidor("CARLA DIAS", "SECRETARIA ADJUNTA", "Cargo Comissionado", date(INICIO, 1, 2), "931274"),
            _servidor("PEDRO VEREADOR", "VEREADOR", "Eletivo", date(INICIO, 1, 1), "000001", ug=170),  # câmara: fora
        ])
        db.add_all([
            _empenho("1", 1, "Vencimentos e Vantagens Fixas - Pessoal Civil", "1000.00"),
            _empenho("2", 1, "Contratação por Tempo Determinado", "500.00"),
            _empenho("3", 2, "Obrigações Patronais", "200.00"),
            _empenho("4", 2, "Material de Consumo", "999.00"),  # não é folha
            # Prestador PF que também está na lista de pessoal (dígitos 7 a 9 do CPF = "222").
            _empenho("5", 3, "Outros Serviços de Terceiros ? Pessoa Física", "300.00", fornecedor="JOAO SOUZA",
                     cpf="***.***.222-33", historico="SERVICO DE PINTURA"),
            _empenho("6", 3, "Outros Serviços de Terceiros ? Pessoa Física", "800.00", fornecedor="MARIA LOCADORA",
                     cpf="***.***.004-04", historico="LOCACAO DO IMOVEL DA UBS"),
            _empenho("7", 3, "Vencimentos e Vantagens Fixas - Pessoal Civil", "70.00", ug="170"),  # câmara: fora
        ])
        db.add(Candidato(sq_candidato="9", ano=2024, cargo="PREFEITO", municipio_ibge="2604007", nome="FULANO PREFEITO",
                         nome_normalizado="FULANO PREFEITO", sigla_partido="XX", eleito=True))
        db.add_all([
            DoacaoCampanha(ano=2024, sq_candidato="9", doador_nome="CARLA DIAS", doador_nome_normalizado="CARLA DIAS",
                           doador_cpf_meio="931274", valor_centavos=150_000),
            # Homônima com outro CPF: não casa.
            DoacaoCampanha(ano=2024, sq_candidato="9", doador_nome="ANA LIMA", doador_nome_normalizado="ANA LIMA",
                           doador_cpf_meio="999999", valor_centavos=1),
        ])
        db.commit()

    def _db() -> Iterator[Session]:
        with fabrica() as sessao:
            yield sessao

    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_pessoal_da_prefeitura(cliente: TestClient) -> None:
    d = cliente.get("/api/municipios/PE/Carpina/pessoal").json()
    assert (d["qtd_vinculos"], d["qtd_pessoas"]) == (4, 3)  # sem o vereador; João conta uma vez
    temporarios = next(v for v in d["por_vinculo"] if v["nome"].startswith("Contratação"))
    assert (temporarios["vinculos"], temporarios["pessoas"], temporarios["no_mandato"]) == (2, 1, 1)
    assert d["remessa"] == {"ano": INICIO + 1, "mes": 8}

    assert d["ano"] == INICIO
    janeiro = next(m for m in d["folha_por_mes"] if m["mes"] == 1)
    assert janeiro["total"] == "1500.00"
    assert {c["nome"]: c["total"] for c in janeiro["por_categoria"]}["Contratados temporários"] == "500.00"
    assert d["folha_por_ano"][0]["total"] == "1700.00"  # sem material de consumo nem a câmara

    assert d["prestadores_total"] == "1100.00" and d["prestadores_qtd"] == 2
    locadora, joao = d["prestadores"]
    assert locadora["tipo"] == "Aluguel de imóvel" and locadora["servidor"] is None
    assert joao["tipo"] == "Serviço" and joao["servidor"]["cargo"] == "AUXILIAR"

    [doador] = d["doadores_nomeados"]
    assert (doador["nome"], doador["doado"], doador["candidato"], doador["eleito"]) == (
        "CARLA DIAS", "1500.00", "FULANO PREFEITO", True)


def test_folha_pela_data_do_pagamento(cliente: TestClient, fabrica: sessionmaker[Session]) -> None:
    """Empenho global de janeiro pago em parcelas: cada mês recebe o que foi pago nele."""
    with fabrica() as db:
        for mes, valor in ((1, 40_000), (2, 60_000), (3, -5_000)):
            db.add(PagamentoMunicipal(unidade_gestora_id=169, ano=INICIO, id_empenho="1", data=date(INICIO, mes, 10),
                                      tipo="Pagamento", valor_centavos=valor))
        db.commit()
    d = cliente.get("/api/municipios/PE/Carpina/pessoal").json()
    assert d["folha_pela_data_do_pagamento"] is True
    assert [(m["mes"], m["total"]) for m in d["folha_por_mes"]] == [(1, "400.00"), (2, "600.00"), (3, "-50.00")]


def test_lista_de_pessoal(cliente: TestClient) -> None:
    tudo = cliente.get("/api/municipios/PE/Carpina/pessoal/lista").json()
    assert tudo["total"] == 4 and tudo["itens"][0]["data_admissao"] >= f"{INICIO}-01-01"
    assert tudo["itens"][-1]["cpf"] == "***.555.634-**"
    busca = cliente.get("/api/municipios/PE/Carpina/pessoal/lista", params={"busca": "secretária"}).json()
    assert [i["nome"] for i in busca["itens"]] == ["CARLA DIAS"]
    filtro = cliente.get("/api/municipios/PE/Carpina/pessoal/lista",
                         params={"vinculo": "Cargo Comissionado", "desde": INICIO}).json()
    assert filtro["total"] == 1
    assert cliente.get("/api/municipios/PE/Atlantida/pessoal").status_code == 404
