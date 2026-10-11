from __future__ import annotations

from datetime import date

from civic.siconfi import contas_da_dca, nivel_da_conta


def _item(conta: str, cod: str, coluna: str, valor: float) -> dict[str, object]:
    return {"cod_ibge": 2604007, "exercicio": 2024, "conta": conta, "cod_conta": cod, "coluna": coluna, "valor": valor}


def test_nivel_da_conta() -> None:
    assert nivel_da_conta("Despesas Exceto Intraorçamentárias") == "total"
    assert nivel_da_conta("10 - Saúde") == "funcao"
    assert nivel_da_conta("04.131 - Comunicação Social") == "subfuncao"
    assert nivel_da_conta("FU04 - Demais Subfunções") is None


def test_contas_da_dca_junta_colunas() -> None:
    # No Siconfi o cod_conta é o mesmo em todas as linhas: a chave vem do nome da conta.
    itens = [
        _item("Despesas Exceto Intraorçamentárias", "TotalDespesas", "Despesas Pagas", 1000),
        _item("10 - Saúde", "TotalDespesas", "Despesas Empenhadas", 100.5),
        _item("10 - Saúde", "TotalDespesas", "Despesas Pagas", 90.25),
        _item("10 - Saúde", "TotalDespesas", "Inscrição de Restos a Pagar Processados", 5),
        _item("10.301 - Atenção Básica", "TotalDespesas", "Despesas Pagas", 50),
        _item("FU10 - Demais Subfunções", "TotalDespesas", "Despesas Pagas", 1),
    ]
    contas = {c["cod_conta"]: c for c in contas_da_dca(itens)}
    assert set(contas) == {"TOTAL", "10", "10.301"}
    assert contas["10"] == {"codigo_ibge": "2604007", "ano": 2024, "cod_conta": "10", "conta": "10 - Saúde",
                            "nivel": "funcao", "empenhado_centavos": 10050, "liquidado_centavos": 0, "pago_centavos": 9025}
    assert contas["10.301"]["nivel"] == "subfuncao" and contas["TOTAL"]["pago_centavos"] == 100_000


# --------------------------------------------------------------------------- RREO (ano corrente)


def _rreo(conta: str, coluna: str, valor: float, rotulo: str = "Total das Despesas Exceto Intra-Orçamentárias") -> dict:
    return {"exercicio": 2026, "periodo": 4, "cod_ibge": 2604007, "rotulo": rotulo, "coluna": coluna,
            "cod_conta": "RREO2TotalDespesas", "conta": conta, "valor": valor}


def test_contas_do_rreo() -> None:
    from civic.siconfi import bimestre_esperado, contas_do_rreo

    liq, dot = "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)", "DOTAÇÃO ATUALIZADA (a)"
    itens = []
    for coluna, fator in ((dot, 2), (liq, 1)):
        itens += [
            _rreo("DESPESAS (EXCETO INTRA-ORÇAMENTÁRIAS) (I)", coluna, 1000 * fator),
            _rreo("Administração", coluna, 300 * fator),
            _rreo("Comunicação Social", coluna, 50 * fator),
            _rreo("FU04 - Administração Geral", coluna, 250 * fator),
            _rreo("Saúde", coluna, 700 * fator),
            _rreo("Atenção Básica", coluna, 400 * fator),
            _rreo("Subfunção Inventada", coluna, 1 * fator),
        ]
    itens.append(_rreo("Saúde", liq, 999, rotulo="Total das Despesas Intra-Orçamentárias"))  # ignorado
    itens.append(_rreo("Saúde", "DESPESAS EMPENHADAS NO BIMESTRE", 5))  # coluna ignorada
    contas = {c["cod_conta"]: c for c in contas_do_rreo(itens, {"COMUNICACAO SOCIAL": "131", "ATENCAO BASICA": "301"})}
    assert set(contas) == {"TOTAL", "04", "04.131", "10", "10.301"}
    assert contas["10"]["conta"] == "10 - Saúde" and contas["10"]["nivel"] == "funcao"
    assert (contas["10"]["liquidado_centavos"], contas["10"]["dotacao_centavos"]) == (70_000, 140_000)
    assert contas["10.301"]["conta"] == "10.301 - Atenção Básica"
    assert contas["TOTAL"]["demonstrativo"] == "RREO" and contas["TOTAL"]["periodo"] == 4
    assert [bimestre_esperado(date(2026, m, 7)) for m in (1, 3, 10, 12)] == [0, 1, 4, 5]


def test_contas_do_ano_corrente_pelo_rreo(fabrica) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from civic import queries
    from civic.api import app
    from civic.database import get_db
    from civic.models import ContaMunicipal, Municipio

    with fabrica() as db:
        for i in range(6):
            ibge = f"26000{i:02d}"
            db.add(Municipio(codigo_ibge=ibge, nome=f"Cidade {i}", nome_normalizado=f"CIDADE {i}", sigla_uf="PE",
                             populacao=1000))
            periodo = 3 if i == 5 else 4  # a cidade 5 está atrasada: não entra na comparação
            db.add(ContaMunicipal(codigo_ibge=ibge, ano=2026, cod_conta="10", conta="10 - Saúde", nivel="funcao",
                                  demonstrativo="RREO", periodo=periodo, dotacao_centavos=10_000_000,
                                  empenhado_centavos=0, liquidado_centavos=(i + 1) * 100_000 * (10 if i == 5 else 1),
                                  pago_centavos=0))
            db.add(ContaMunicipal(codigo_ibge=ibge, ano=2025, cod_conta="10", conta="10 - Saúde", nivel="funcao",
                                  pago_centavos=1, empenhado_centavos=1, liquidado_centavos=1))
        db.commit()
    queries._MEDIANAS_CACHE.clear()

    def _db():  # type: ignore[no-untyped-def]
        with fabrica() as sessao:
            yield sessao

    app.dependency_overrides[get_db] = _db
    try:
        corpo = TestClient(app).get("/api/municipios/PE/Cidade 0/contas").json()
    finally:
        app.dependency_overrides.clear()
    assert corpo["anos"] == [2026, 2025] and corpo["demonstrativo"] == "RREO" and corpo["bimestre"] == 4
    saude = corpo["funcoes"][0]
    assert saude["pago"] == "1000.00" and saude["dotacao"] == "100000.00"  # liquidado até o 4º bimestre
    assert saude["mediana_uf"] == "3.00"  # mediana de R$ 1 a R$ 5 por habitante (só quem está no 4º bimestre)
    assert corpo["amostra_uf"] == 5
