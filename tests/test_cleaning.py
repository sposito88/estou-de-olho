from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

import pytest

from civic.cleaning import (
    ano_do_codigo_emenda,
    despesa_da_api,
    despesa_do_csv,
    emenda_do_csv,
    gerar_hash,
    limpar_documento,
    limpar_informacao,
    limpar_texto,
    normalizar_nome,
    pagamento_emenda_do_csv,
    para_centavos,
    para_inteiro,
    parse_data,
    tipo_pessoa,
)

# Mesmo documento, como vem da API e do CSV anual (dados reais de 2026).
ITEM_API = {
    "ano": 2026,
    "mes": 1,
    "tipoDespesa": "MANUTENÇÃO DE ESCRITÓRIO DE APOIO À ATIVIDADE PARLAMENTAR",
    "codDocumento": "8045644",
    "tipoDocumento": "Recibos/Outros",
    "codTipoDocumento": 1,
    "dataDocumento": "2026-01-25T00:00:00",
    "numDocumento": "34126012",
    "valorDocumento": 833.12,
    "urlDocumento": "https://www.camara.leg.br/cota-parlamentar/documentos/publ/3419/2026/8045644.pdf",
    "nomeFornecedor": "2WS Soluções em tecnologia e desenvolvimento profi",
    "cnpjCpfFornecedor": "14668041000165",
    "valorLiquido": 833.12,
    "valorGlosa": 0.0,
    "parcela": 0,
}
LINHA_CSV = {
    "ideCadastro": "157130",
    "txtDescricao": "MANUTENÇÃO DE ESCRITÓRIO DE APOIO À ATIVIDADE PARLAMENTAR",
    "txtFornecedor": "2WS Soluções em tecnologia e desenvolvimento profi",
    "txtCNPJCPF": "146.680.410/0016-5",
    "txtNumero": "34126012",
    "indTipoDocumento": "1",
    "datEmissao": "2026-01-25T00:00:00",
    "vlrDocumento": "833.12",
    "vlrGlosa": "0",
    "vlrLiquido": "833.12",
    "numMes": "1",
    "numAno": "2026",
    "numParcela": "0",
    "ideDocumento": "8045644",
    "urlDocumento": "https://www.camara.leg.br/cota-parlamentar/documentos/publ/3419/2026/8045644.pdf",
}


class TestLimparDocumento:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("12.345.678/0001-95", "12345678000195"),
            ("146.680.410/0016-5", "14668041000165"),
            ("123.456.789-09", "12345678909"),
            ("  12345678909 ", "12345678909"),
        ],
    )
    def test_extrai_digitos(self, entrada: str, esperado: str) -> None:
        assert limpar_documento(entrada) == esperado

    @pytest.mark.parametrize("entrada", [None, "", "   ", "---", "abc"])
    def test_vazio_vira_none(self, entrada: str | None) -> None:
        assert limpar_documento(entrada) is None

    def test_tamanho_invalido_vira_none_e_loga(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            assert limpar_documento("1234567") is None
        assert "7 dígitos" in caplog.text


class TestTipoPessoa:
    @pytest.mark.parametrize(
        ("doc", "esperado"),
        [("12345678000195", "PJ"), ("12345678909", "PF"), (None, None), ("123", None)],
    )
    def test_tipo(self, doc: str | None, esperado: str | None) -> None:
        assert tipo_pessoa(doc) == esperado


class TestParseData:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("2023-05-17", date(2023, 5, 17)),
            ("2023-05-17T00:00:00", date(2023, 5, 17)),
            ("2023-05-17 13:45:00", date(2023, 5, 17)),
            ("2023-05-17T13:45:00.123", date(2023, 5, 17)),
            ("17/05/2023", date(2023, 5, 17)),
        ],
    )
    def test_formatos(self, entrada: str, esperado: date) -> None:
        assert parse_data(entrada) == esperado

    @pytest.mark.parametrize("entrada", [None, "", "  ", "ontem", "2023-13-40"])
    def test_invalido_vira_none(self, entrada: str | None) -> None:
        assert parse_data(entrada) is None


class TestParaCentavos:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            (None, 0),
            ("", 0),
            (0, 0),
            (10, 1000),
            (833.12, 83312),
            (0.1 + 0.2, 30),  # 0.30000000000000004
            (1.005, 101),  # float "1.005" -> HALF_UP
            ("1467", 146700),
            ("833.12", 83312),
            ("10.000,00", 1000000),
            ("245850,00", 24585000),
            ("R$ 1.234,56", 123456),
            ("-50.25", -5025),
            ("0.005", 1),
            ("0.004", 0),
            (Decimal("19.999"), 2000),
        ],
    )
    def test_conversao(self, entrada: object, esperado: int) -> None:
        assert para_centavos(entrada) == esperado  # type: ignore[arg-type]

    def test_retorna_int(self) -> None:
        assert type(para_centavos("1,50")) is int

    @pytest.mark.parametrize("entrada", ["abc", "1,2,3", True, float("nan")])
    def test_invalido_levanta(self, entrada: object) -> None:
        with pytest.raises(ValueError):
            para_centavos(entrada)  # type: ignore[arg-type]


class TestTexto:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("  Posto   Ipiranga \n LTDA ", "Posto Ipiranga LTDA"),
            ("", None),
            ("   ", None),
            (None, None),
            ("ok", "ok"),
        ],
    )
    def test_limpar_texto(self, entrada: str | None, esperado: str | None) -> None:
        assert limpar_texto(entrada) == esperado

    @pytest.mark.parametrize("entrada", ["Sem informação", "S/I", " -1 ", ""])
    def test_limpar_informacao(self, entrada: str) -> None:
        assert limpar_informacao(entrada) is None

    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("Túlio Gadêlha", "TULIO GADELHA"),
            ("Dr. Frederico", "DR FREDERICO"),
            ("POÇO  REDONDO", "POCO REDONDO"),
            ("Carpina", "CARPINA"),
            (None, None),
        ],
    )
    def test_normalizar_nome(self, entrada: str | None, esperado: str | None) -> None:
        assert normalizar_nome(entrada) == esperado

    @pytest.mark.parametrize(
        ("entrada", "esperado"), [("12", 12), ("0012", 12), ("12.0", 12), ("", None), ("x", None), (7, 7)]
    )
    def test_para_inteiro(self, entrada: object, esperado: int | None) -> None:
        assert para_inteiro(entrada) == esperado


class TestHash:
    def test_deterministico(self) -> None:
        a = gerar_hash(1, 2024, 3, 10, "NF1", "12345678000195", 1000, 0)
        b = gerar_hash(1, 2024, 3, 10, "NF1", "12345678000195", 1000, 0)
        assert a == b
        assert len(a) == 64

    @pytest.mark.parametrize(
        "alterado",
        [
            (2, 2024, 3, 10, "NF1", "12345678000195", 1000, 0),
            (1, 2024, 4, 10, "NF1", "12345678000195", 1000, 0),
            (1, 2024, 3, 11, "NF1", "12345678000195", 1000, 0),
            (1, 2024, 3, 10, "NF2", "12345678000195", 1000, 0),
            (1, 2024, 3, 10, "NF1", None, 1000, 0),
            (1, 2024, 3, 10, "NF1", "12345678000195", 1001, 0),
            (1, 2024, 3, 10, "NF1", "12345678000195", 1000, 1),
        ],
    )
    def test_qualquer_campo_muda_o_hash(self, alterado: tuple) -> None:  # type: ignore[type-arg]
        base = gerar_hash(1, 2024, 3, 10, "NF1", "12345678000195", 1000, 0)
        assert gerar_hash(*alterado) != base

    def test_none_e_vazio_sao_equivalentes(self) -> None:
        assert gerar_hash(1, 2024, 3, None, None, None, 0, 0) == gerar_hash(
            1, 2024, 3, None, "", "", 0, 0
        )


class TestDespesa:
    def test_api_e_csv_geram_o_mesmo_registro(self) -> None:
        da_api = despesa_da_api(ITEM_API, deputado_id=157130)
        do_csv = despesa_do_csv(LINHA_CSV)
        assert da_api == do_csv
        assert da_api["hash_unico"] == do_csv["hash_unico"]

    def test_campos_normalizados(self) -> None:
        d = despesa_da_api(ITEM_API, deputado_id=157130)
        assert d["cnpj_cpf"] == "14668041000165"
        assert d["tipo_pessoa"] == "PJ"
        assert d["valor_liquido_centavos"] == 83312
        assert d["data_documento"] == date(2026, 1, 25)
        assert d["cod_documento"] == 8045644
        assert d["tipo_documento"] == "Recibos/Outros"

    def test_sem_documento_fiscal(self) -> None:
        item = {
            **ITEM_API,
            "codDocumento": 0,
            "cnpjCpfFornecedor": "",
            "urlDocumento": None,
            "dataDocumento": None,
        }
        d = despesa_da_api(item, deputado_id=1)
        assert d["cod_documento"] is None
        assert d["cnpj_cpf"] is None
        assert d["tipo_pessoa"] is None
        assert d["url_documento"] is None
        assert d["data_documento"] is None

    def test_csv_sem_ide_cadastro(self) -> None:
        with pytest.raises(ValueError):
            despesa_do_csv({**LINHA_CSV, "ideCadastro": ""})


class TestEmendas:
    def test_ano_do_codigo(self) -> None:
        assert ano_do_codigo_emenda("202440340007") == 2024
        assert ano_do_codigo_emenda(None) is None
        assert ano_do_codigo_emenda("Sem") is None

    def test_emenda_com_municipio(self) -> None:
        linha = {
            "Código da Emenda": "202041750001",
            "Ano da Emenda": "2020",
            "Tipo de Emenda": "Emenda Individual - Transferências com Finalidade Definida",
            "Código do Autor da Emenda": "4175",
            "Nome do Autor da Emenda": "TULIO GADELHA",
            "Número da emenda": "0001",
            "Localidade de aplicação do recurso": "CARPINA - PE",
            "Código Município IBGE": "2604007",
            "Município": "CARPINA",
            "Nome Função": "Saúde",
            "Valor Empenhado": "500000,00",
            "Valor Pago": "500.000,00",
            "Valor Liquidado": "",
        }
        e = emenda_do_csv(linha)
        assert e["sigla_uf"] == "PE"
        assert e["codigo_municipio_ibge"] == "2604007"
        assert e["nome_autor_normalizado"] == "TULIO GADELHA"
        assert e["valor_empenhado_centavos"] == 50_000_000
        assert e["valor_pago_centavos"] == 50_000_000
        assert e["valor_liquidado_centavos"] == 0

    def test_emenda_sem_municipio(self) -> None:
        e = emenda_do_csv(
            {
                "Código da Emenda": "Sem informação",
                "Ano da Emenda": "2024",
                "Nome do Autor da Emenda": "Sem informação",
                "Código Município IBGE": "-1",
                "Município": "Sem informação",
                "Localidade de aplicação do recurso": "MÚLTIPLO",
            }
        )
        assert e["codigo_emenda"] is None
        assert e["nome_autor"] is None
        assert e["codigo_municipio_ibge"] is None
        assert e["municipio"] is None
        assert e["sigla_uf"] is None
        assert e["localidade"] == "MÚLTIPLO"

    def test_pagamento(self) -> None:
        p = pagamento_emenda_do_csv(
            {
                "Código da Emenda": "202443910005",
                "Código do Autor da Emenda": "4391",
                "Nome do Autor da Emenda": "CLARISSA TÉRCIO",
                "Ano/Mês": "202609",
                "Favorecido": "MUNICIPIO DE CARPINA",
                "Tipo Favorecido": "Pessoa Jurídica",
                "UF Favorecido": "pe",
                "Município Favorecido": "CARPINA",
                "Valor Recebido": "87976,25",
            }
        )
        assert (p["ano"], p["mes"], p["ano_emenda"]) == (2026, 9, 2024)
        assert p["sigla_uf"] == "PE"
        assert p["municipio_normalizado"] == "CARPINA"
        assert p["nome_autor_normalizado"] == "CLARISSA TERCIO"
        assert p["valor_recebido_centavos"] == 8_797_625

    def test_pagamento_ano_mes_invalido(self) -> None:
        with pytest.raises(ValueError):
            pagamento_emenda_do_csv({"Ano/Mês": "2026"})
