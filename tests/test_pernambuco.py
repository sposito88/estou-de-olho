from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from civic import pernambuco, queries
from civic.api import app
from civic.cleaning import despesa_municipal_do_tce, servidor_do_tce
from civic.config import Settings
from civic.database import get_db
from civic.models import (
    DeputadoEstadual,
    DespesaMunicipal,
    ServidorMunicipal,
    SyncCheckpointEstadual,
    UnidadeGestora,
    VerbaIndenizatoria,
)
from civic.scraper import Resumo
from tests.conftest import AGORA

EMPENHO = {
    "VALORLIQUIDADO": "300.00", "CODIGO_MUNICIPIO": "P042", "CPF_CNPJ": "***.***.404-92",
    "NOMEUNIDADEGESTORA": "Câmara Municipal de Carpina", "VALORPAGO": "300.00", "MESREFERENCIA": "3",
    "ACAO": "MANUTENCAO", "VALOREMPENHADO": "300.00", "ANOREFERENCIA": "2025", "NUMEROEMPENHO": "0000066",
    "ID_EMPENHO": "9673719     ", "HISTORICO": "DESPESA DE 01 DIARIA  ", "ELEMENTODESPESA": "Diárias - Civil",
    "FORNECEDOR": "Severino Borges da Silva", "DATAEMPENHO": "2025-03-17 00:00:00.0", "ID_UNIDADE_GESTORA": "170",
    "FUNCAO": "Legislativa", "MODALIDADE": "Aplicações Diretas",
}


# --------------------------------------------------------------------------- limpeza


def test_despesa_municipal_do_tce() -> None:
    d = despesa_municipal_do_tce(EMPENHO)
    assert d["chave"] == "9673719|2025|0000066|170"
    assert d["unidade_gestora_id"] == 170
    assert (d["ano"], d["mes"], d["data_empenho"]) == (2025, 3, date(2025, 3, 17))
    assert (d["cpf_cnpj"], d["tipo_pessoa"]) == ("***.***.404-92", "PF")
    assert d["fornecedor_normalizado"] == "SEVERINO BORGES DA SILVA"
    assert d["historico"] == "DESPESA DE 01 DIARIA"
    assert d["valor_pago_centavos"] == 30_000

    pj = despesa_municipal_do_tce({**EMPENHO, "CPF_CNPJ": "08777708000165"})
    assert (pj["cpf_cnpj"], pj["tipo_pessoa"]) == ("08777708000165", "PJ")
    zerado = despesa_municipal_do_tce({**EMPENHO, "CPF_CNPJ": "00000000000000"})
    assert (zerado["cpf_cnpj"], zerado["tipo_pessoa"]) == (None, None)


def test_servidor_do_tce() -> None:
    s = servidor_do_tce(
        {"UnidadeJurisdicionadaTCE": "170", "NomeServidor": "Severino  Borges da Silva", "NomeCargo": "VEREADOR",
         "NomeTipoVinculo": "Eletivo", "DataAdmissao": "2025-01-01", "AnoRemessa": "2026", "MesRemessa": "9"}
    )
    assert s["nome_normalizado"] == "SEVERINO BORGES DA SILVA"
    assert (s["unidade_gestora_id"], s["cargo"], s["data_admissao"]) == (170, "VEREADOR", date(2025, 1, 1))


def test_inicio_mandato_municipal() -> None:
    assert queries.inicio_mandato_municipal(date(2026, 10, 7)) == 2025
    assert queries.inicio_mandato_municipal(date(2025, 1, 1)) == 2025
    assert queries.inicio_mandato_municipal(date(2024, 12, 31)) == 2021
    assert queries.inicio_mandato_municipal(date(2029, 3, 1)) == 2029


# --------------------------------------------------------------------------- coletores (fontes falsas)


class ClienteFalso:
    """Responde por trecho de URL; guarda as chamadas para conferir o que foi pulado."""

    def __init__(self, respostas: dict[str, Any]) -> None:
        self.respostas = respostas
        self.chamadas: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, params: dict[str, Any] | None = None, *, latin1: bool = False) -> Any:
        self.chamadas.append((url, params or {}))
        for trecho, resposta in self.respostas.items():
            if trecho in url:
                return resposta(params or {}) if callable(resposta) else resposta
        raise AssertionError(f"URL inesperada: {url}")


def _alepe() -> ClienteFalso:
    return ClienteFalso(
        {
            "deputados.php": [
                {"id": "4508", "nome": "Abimael Santos", "partido": "PL", "foto": "/imagens/a.jpg"},
                {"id": "4432", "nome": "Ex Deputado", "partido": "PTB", "foto": ""},
            ],
            "/parlamentares/": [{"nomeParlamentar": "Abimael Santos", "partido": "PL"}],
            "rubricas.php": [{"numero_categoria": 3, "nome_categoria": "ASSESSORIA JURÍDICA "}],
            "dep-meses.php": lambda p: [{"mes": 1}, {"mes": 2}] if p["dep"] == 4508 else [],
            "verbaindenizatoria.php": lambda p: [{"docid": f"{p['mes']}00", "total": "1000"}],
            "verbaindenizatorianotas.php": [
                {"rubrica": 3, "sequencial": 1, "data": "31/01/2025", "cnpj": "47006999000140",
                 "empresa": "Advocacia X", "valor": "1000"},
            ],
        }
    )


def test_coleta_alepe_com_checkpoint(db: Session, settings: Settings) -> None:
    cliente = _alepe()
    assert pernambuco.sincronizar_deputados_estaduais(cliente, db, settings) == 2  # type: ignore[arg-type]
    ab = db.get(DeputadoEstadual, 4508)
    assert ab is not None and ab.em_exercicio and ab.url_foto == "https://www.alepe.pe.gov.br/imagens/a.jpg"
    assert db.get(DeputadoEstadual, 4432).em_exercicio is False  # type: ignore[union-attr]

    resumo = Resumo()
    assert pernambuco.coletar_verbas(cliente, db, [2025], settings, resumo, progresso=False) == 2  # type: ignore[arg-type]
    notas = list(db.scalars(select(VerbaIndenizatoria)))
    assert {(n.mes, n.rubrica_nome, n.valor_centavos) for n in notas} == {
        (1, "ASSESSORIA JURÍDICA", 100_000), (2, "ASSESSORIA JURÍDICA", 100_000)
    }
    # 2025 já fechou: meses + marcador de ano verificado (mes=0) para os dois deputados.
    marcas = set(db.execute(select(SyncCheckpointEstadual.deputado_estadual_id, SyncCheckpointEstadual.mes)))
    assert marcas == {(4508, 1), (4508, 2), (4508, 0), (4432, 0)}

    # Segunda rodada: ano fechado e verificado, nenhuma chamada por deputado.
    cliente.chamadas.clear()
    pernambuco.coletar_verbas(cliente, db, [2025], settings, Resumo(), progresso=False)  # type: ignore[arg-type]
    assert not any("dep-meses" in u for u, _ in cliente.chamadas)
    assert db.scalar(select(func.count()).select_from(VerbaIndenizatoria)) == 2


def test_recente() -> None:
    hoje = date(2026, 10, 7)
    assert pernambuco.recente(2026, 10, hoje) and pernambuco.recente(2026, 8, hoje)
    assert not pernambuco.recente(2026, 7, hoje)


CONTRATO = {
    "CodigoContrato": "777", "CodigoUG": "169", "AnoContrato": "2025", "NumeroContrato": "12",
    "TipoProcesso": "Pregão Eletrônico", "NumeroProcesso": "5", "AnoProcesso": "2025",
    "Objeto": "LOCAÇÃO DE VEÍCULOS", "RazaoSocial": "Fulano de Tal", "CPF_CNPJ": "***.***.724-69",
    "NumeroDocumento": "032.679.724-69", "NumeroDocumentoAjustado": "03267972469", "Valor": "46999.20",
    "Vigencia": "11/08/2025 a 11/08/2026", "Situacao": "Regular", "Estagio": "Em Execução",
    "LinkArquivo": "http://sistemas.tcepe.tc.br/audinArquivos/licon/contrato.pdf",
}


def _tce(empenhos_2025: list[dict[str, Any]]) -> ClienteFalso:
    def resposta(conteudo: list[dict[str, Any]]) -> dict[str, Any]:
        return {"resposta": {"status": "OK", "limiteResultado": "100000", "conteudo": conteudo}}

    unidades = [
        {"ID_UNIDADE_GESTORA": "169", "ORGAO": "Prefeitura Municipal de Carpina", "NATUREZA": "Prefeitura Municipal",
         "CODIGOMUNICIPIO": "P042", "MUNICIPIO": "Carpina", "ESFERA": "Municipal "},
        {"ID_UNIDADE_GESTORA": "170", "ORGAO": "Câmara Municipal de Carpina", "NATUREZA": "Câmara Municipal",
         "CODIGOMUNICIPIO": "P042", "MUNICIPIO": "Carpina", "ESFERA": "Municipal "},
        {"ID_UNIDADE_GESTORA": "1301", "ORGAO": "Consórcio Mata Norte", "NATUREZA": "Consórcio",
         "CODIGOMUNICIPIO": "P042", "MUNICIPIO": "Carpina", "ESFERA": "Municipal "},
        {"ID_UNIDADE_GESTORA": "1", "ORGAO": "Prefeitura de Abreu e Lima", "NATUREZA": "Prefeitura Municipal",
         "CODIGOMUNICIPIO": "P001", "MUNICIPIO": "Abreu e Lima", "ESFERA": "Municipal "},
    ]
    return ClienteFalso(
        {
            "UnidadesJurisdicionadas": resposta(unidades),
            "DespesasMunicipais": lambda p: resposta(empenhos_2025 if p["ANOREFERENCIA"] == 2025 else []),
            "EmpenhoPagamento": lambda p: resposta(
                [{"ID_UNIDADE_GESTORA": "170", "IDEMPENHO": "9673719", "TIPO": "Pagamento",
                  "DATA": "2025-03-20 00:00:00.0", "ANOREFERENCIA": "2025", "VALOR": "300.00"}]
                if p["ID_UNIDADE_GESTORA"] == 170 and p["ANOREFERENCIA"] == 2025 else []
            ),
            "Contratos!json": lambda p: resposta([CONTRATO]),
            "ListaServidores": lambda p: resposta(
                [{"UnidadeJurisdicionadaTCE": "170", "NomeServidor": "Severino Borges da Silva", "NomeCargo": "VEREADOR",
                  "NomeTipoVinculo": "Eletivo", "DataAdmissao": "2025-01-01"}]
                if p["UnidadeJurisdicionadaTCE"] == 170 else []
            ),
        }
    )


def test_coleta_tce_substitui_ano_e_ignora_consorcio(db: Session) -> None:
    s = Settings(_env_file=None, tce_municipios="Carpina")  # type: ignore[call-arg]
    empenhos = [EMPENHO, {**EMPENHO, "ID_EMPENHO": "2", "ID_UNIDADE_GESTORA": "1301"}]  # consórcio fica de fora
    hoje = date(2025, 9, 1)  # 2025 ainda aberto: é relido a cada coleta
    assert pernambuco.coletar_tce(_tce(empenhos), db, [2025], s, Resumo(), hoje=hoje) == 1  # type: ignore[arg-type]
    assert {u.id for u in db.scalars(select(UnidadeGestora))} == {169, 170}
    assert db.scalar(select(func.count()).select_from(ServidorMunicipal)) == 1

    # Recoleta do ano troca tudo (sem duplicar).
    pernambuco.coletar_tce(_tce([{**EMPENHO, "VALORPAGO": "450.00"}]), db, [2025], s, Resumo(),  # type: ignore[arg-type]
                           hoje=hoje)
    assert [d.valor_pago_centavos for d in db.scalars(select(DespesaMunicipal))] == [45_000]


def test_coleta_tce_contratos_pagamentos_e_checkpoint(db: Session) -> None:
    from civic.models import ContratoMunicipal, Municipio, PagamentoMunicipal, SyncMunicipioAno

    db.add(Municipio(codigo_ibge="2604007", nome="Carpina", nome_normalizado="CARPINA", sigla_uf="PE"))
    db.commit()
    s = Settings(_env_file=None, tce_municipios="todos")  # type: ignore[call-arg]
    cliente = _tce([EMPENHO])
    pernambuco.coletar_tce(cliente, db, [2023, 2025], s, Resumo(), hoje=date(2025, 9, 1))  # type: ignore[arg-type]
    # "todos": Abreu e Lima também entra (sem par no IBGE, fica com o nome do TCE).
    assert {u.municipio for u in db.scalars(select(UnidadeGestora))} == {"Carpina", "Abreu e Lima"}
    [contrato] = db.scalars(select(ContratoMunicipal))
    assert (contrato.unidade_gestora_id, contrato.cpf_cnpj, contrato.valor_centavos) == (169, "***.***.724-69", 4_699_920)
    assert contrato.vigencia_fim == date(2026, 8, 11) and contrato.url_documento.endswith(".pdf")
    assert "03267972469" not in str({c.name: getattr(contrato, c.name) for c in ContratoMunicipal.__table__.columns})
    assert db.scalar(select(func.count()).select_from(PagamentoMunicipal)) == 1
    # 2023 (fechado) ganhou checkpoint; 2025 não. Na segunda vez, 2023 não é pedido de novo.
    assert set(db.scalars(select(SyncMunicipioAno.ano).where(SyncMunicipioAno.fonte == "TCE-PE"))) == {2023}
    cliente2 = _tce([EMPENHO])
    pernambuco.coletar_tce(cliente2, db, [2023, 2025], s, Resumo(), hoje=date(2025, 9, 2))  # type: ignore[arg-type]
    pedidos = [p.get("ANOREFERENCIA") for u, p in cliente2.chamadas if "DespesasMunicipais" in u]
    assert 2023 not in pedidos and 2025 in pedidos
    assert not any("ListaServidores" in u for u, _ in cliente2.chamadas)  # pessoal relido só após 7 dias


def test_resposta_vazia_nao_apaga_o_que_ja_existe(db: Session) -> None:
    """A API do TCE-PE já respondeu "OK" sem conteúdo para anos inteiros: os dados ficam."""
    s = Settings(_env_file=None, tce_municipios="Carpina")  # type: ignore[call-arg]
    hoje = date(2025, 9, 1)
    pernambuco.coletar_tce(_tce([EMPENHO]), db, [2025], s, Resumo(), hoje=hoje)  # type: ignore[arg-type]
    resumo = Resumo()
    pernambuco.coletar_tce(_tce([]), db, [2025], s, resumo, hoje=hoje)  # type: ignore[arg-type]
    assert db.scalar(select(func.count()).select_from(DespesaMunicipal)) == 1
    assert any("devolveu vazio" in f for f in resumo.falhas)


def test_despesas_acima_do_limite_vao_por_orgao() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    cheio = {"resposta": {"status": "OK", "limiteResultado": "1", "conteudo": [EMPENHO]}}
    por_ug = {"resposta": {"status": "OK", "limiteResultado": "100000", "conteudo": [EMPENHO]}}
    cliente = ClienteFalso({"DespesasMunicipais": lambda p: por_ug if "ID_UNIDADE_GESTORA" in p else cheio})
    linhas = pernambuco._despesas(cliente, s, "P042", [169, 170], 2025)  # type: ignore[arg-type]
    assert len(linhas) == 1 and sum("ID_UNIDADE_GESTORA" in p for _, p in cliente.chamadas) == 2


def test_conteudo_tce_erro() -> None:
    cliente = ClienteFalso({"X": {"resposta": {"status": "ERRO", "conteudo": []}}})
    with pytest.raises(ValueError):
        pernambuco.conteudo_tce(cliente, "http://tce/X", {})  # type: ignore[arg-type]


# --------------------------------------------------------------------------- consultas e API


def _popular_pe(db: Session) -> None:
    db.add_all(
        [
            UnidadeGestora(id=169, nome="Prefeitura Municipal de Carpina", natureza="Prefeitura Municipal",
                           codigo_municipio_tce="P042", municipio="Carpina", municipio_normalizado="CARPINA"),
            UnidadeGestora(id=170, nome="Câmara Municipal de Carpina", natureza="Câmara Municipal",
                           codigo_municipio_tce="P042", municipio="Carpina", municipio_normalizado="CARPINA"),
            DeputadoEstadual(id=4508, nome="Abimael Santos", nome_normalizado="ABIMAEL SANTOS", sigla_partido="PL",
                             em_exercicio=True, atualizado_em=AGORA),
            DeputadoEstadual(id=4432, nome="Ex Deputado", nome_normalizado="EX DEPUTADO", em_exercicio=False,
                             atualizado_em=AGORA),
        ]
    )
    db.flush()
    db.add_all(
        [
            ServidorMunicipal(unidade_gestora_id=170, nome="SEVERINO BORGES DA SILVA",
                              nome_normalizado="SEVERINO BORGES DA SILVA", cargo="VEREADOR", vinculo="Eletivo",
                              data_admissao=date(2025, 1, 1)),
            ServidorMunicipal(unidade_gestora_id=170, nome="ERALDO JOSE DO NASCIMENTO",
                              nome_normalizado="ERALDO JOSE DO NASCIMENTO", cargo="VEREADOR", vinculo="Eletivo",
                              data_admissao=date(2021, 1, 1)),
            ServidorMunicipal(unidade_gestora_id=170, nome="ASSESSOR UM", nome_normalizado="ASSESSOR UM",
                              cargo="CHEFE DE GABINETE", vinculo="Cargo Comissionado", data_admissao=date(2025, 2, 1)),
            DespesaMunicipal(**despesa_municipal_do_tce(EMPENHO)),
            DespesaMunicipal(**despesa_municipal_do_tce(
                {**EMPENHO, "ID_EMPENHO": "2", "FORNECEDOR": "Eraldo José do Nascimento", "VALORPAGO": "5000.00"})),
            DespesaMunicipal(**despesa_municipal_do_tce(
                {**EMPENHO, "ID_EMPENHO": "3", "ID_UNIDADE_GESTORA": "169", "FORNECEDOR": "Construtora Y",
                 "CPF_CNPJ": "12345678000195", "VALORPAGO": "100000.00", "VALOREMPENHADO": "150000.00",
                 "FUNCAO": "Urbanismo", "HISTORICO": "PAVIMENTACAO DA RUA A"})),
            VerbaIndenizatoria(docid="1", deputado_estadual_id=4508, ano=2025, mes=1, rubrica=3,
                               rubrica_nome="ASSESSORIA JURÍDICA", data=date(2025, 1, 31), cnpj_cpf="12345678000195",
                               tipo_pessoa="PJ", fornecedor="Construtora Y", valor_centavos=2_188_000),
        ]
    )
    db.commit()


@pytest.fixture()
def cliente_pe(fabrica: sessionmaker[Session]) -> Iterator[TestClient]:
    with fabrica() as db:
        _popular_pe(db)

    def _db() -> Iterator[Session]:
        with fabrica() as sessao:
            yield sessao

    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_camara_atribui_pagamentos_a_vereadores(cliente_pe: TestClient) -> None:
    corpo = cliente_pe.get("/api/municipios/PE/carpina/camara", params={"ano": 2025}).json()
    assert corpo["orgao"]["id"] == 170
    assert corpo["total_pago"] == "5300.00"
    vereadores = {v["nome"]: v for v in corpo["vereadores"]}
    assert vereadores["ERALDO JOSE DO NASCIMENTO"]["total_recebido"] == "5000.00"
    assert vereadores["ERALDO JOSE DO NASCIMENTO"]["mandato_atual"] is False
    assert vereadores["SEVERINO BORGES DA SILVA"]["mandato_atual"] is True
    assert vereadores["SEVERINO BORGES DA SILVA"]["por_tipo"] == [{"nome": "Diárias - Civil", "total_pago": "300.00"}]
    assert corpo["qtd_vereadores_mandato"] == 1
    assert corpo["nomeados_no_mandato"] == 2
    assert corpo["comissionados_por_cargo"] == [{"nome": "CHEFE DE GABINETE", "qtd": 1}]


def test_api_prefeitura_e_empenhos(cliente_pe: TestClient) -> None:
    corpo = cliente_pe.get("/api/municipios/PE/Carpina/prefeitura", params={"ano": 2025}).json()
    assert corpo["total_pago"] == "100000.00"
    assert corpo["total_empenhado"] == "150000.00"
    assert corpo["por_funcao"] == [{"nome": "Urbanismo", "total_pago": "100000.00"}]
    assert corpo["fornecedores"][0]["cpf_cnpj"] == "12345678000195"
    for termo in ("pavimentação", "Pavimentacao da rua", "construtora"):
        busca = cliente_pe.get("/api/municipios/PE/Carpina/empenhos", params={"busca": termo}).json()
        assert [e["fornecedor"] for e in busca["itens"]] == ["Construtora Y"], termo
    todos = cliente_pe.get("/api/municipios/PE/Carpina/empenhos", params={"orgao_id": 170}).json()
    assert todos["total"] == 2 and {e["orgao"] for e in todos["itens"]} == {"Câmara Municipal de Carpina"}
    assert cliente_pe.get("/api/municipios/SP/Campinas/prefeitura").status_code == 404
    assert cliente_pe.get("/api/municipios/SP/Campinas/camara").status_code == 404


def test_api_estaduais(cliente_pe: TestClient) -> None:
    lista = cliente_pe.get("/api/estaduais").json()
    assert [(i["deputado"]["nome"], i["total"]) for i in lista] == [("Abimael Santos", "21880.00")]
    resumo = cliente_pe.get("/api/estaduais/resumo").json()
    assert resumo["por_rubrica"] == [{"rubrica": "ASSESSORIA JURÍDICA", "total": "21880.00"}]
    det = cliente_pe.get("/api/estaduais/4508").json()
    assert det["notas"]["total"] == 1 and det["notas"]["itens"][0]["valor"] == "21880.00"
    assert det["por_fornecedor"][0]["cnpj"] == "12345678000195"
    assert cliente_pe.get("/api/estaduais/1").status_code == 404


def test_api_fornecedor_soma_as_tres_fontes(cliente_pe: TestClient) -> None:
    corpo = cliente_pe.get("/api/fornecedores/12345678000195").json()
    assert corpo["total_estadual"] == "21880.00"
    assert corpo["total_municipal"] == "100000.00"
    assert corpo["total_cota"] == "0.00"
    assert corpo["total_recebido"] == "121880.00"
    assert corpo["por_deputado_estadual"][0]["deputado"]["nome"] == "Abimael Santos"
    assert corpo["por_orgao"][0]["orgao"]["nome"] == "Prefeitura Municipal de Carpina"


def test_folha_sem_credor_fica_fora_do_ranking(fabrica: sessionmaker[Session]) -> None:
    with fabrica() as db:
        _popular_pe(db)
        db.add(DespesaMunicipal(**despesa_municipal_do_tce(
            {**EMPENHO, "ID_EMPENHO": "9", "ID_UNIDADE_GESTORA": "169", "CPF_CNPJ": "",
             "FORNECEDOR": "Fornecedor não cadastrado na Receita Federal", "VALORPAGO": "900000.00",
             "ELEMENTODESPESA": "Vencimentos e Vantagens Fixas - Pessoal Civil"})))
        db.commit()
        dados = queries.prefeitura_municipio(db, "PE", "Carpina", 2025)
    assert dados is not None
    assert dados["sem_credor_identificado"] == 90_000_000
    assert [f["nome"] for f in dados["fornecedores"]] == ["Construtora Y"]
    assert dados["total_pago"] == 100_000_00 + 90_000_000


def test_api_documentos_do_fornecedor(cliente_pe: TestClient) -> None:
    corpo = cliente_pe.get("/api/fornecedores/12345678000195/documentos").json()
    assert corpo["total"] == 2
    fontes = {i["fonte"]: i for i in corpo["itens"]}
    assert fontes["empenho_municipal"]["pagador"] == "Prefeitura Municipal de Carpina"
    assert fontes["empenho_municipal"]["descricao"] == "PAVIMENTACAO DA RUA A"
    assert fontes["empenho_municipal"]["url"] is None
    assert fontes["verba_estadual"]["pagador"] == "Abimael Santos"
    assert fontes["verba_estadual"]["valor"] == "21880.00"
    assert cliente_pe.get("/api/fornecedores/123/documentos").status_code == 422


def test_url_contrato_pncp() -> None:
    assert queries.url_contrato_pncp("08985624000117-2-000001/2025") == "https://pncp.gov.br/app/contratos/08985624000117/2025/1"
    assert queries.url_contrato_pncp("invalido") is None
