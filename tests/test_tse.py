from __future__ import annotations

from civic.cleaning import candidato_do_tse

LINHA = {
    "ANO_ELEICAO": "2024", "TP_ABRANGENCIA": "MUNICIPAL", "SG_UF": "PE", "SG_UE": "23795", "NM_UE": "CARPINA",
    "DS_CARGO": "Vereador", "SQ_CANDIDATO": "170002156418", "NR_CANDIDATO": "27123",
    "NM_CANDIDATO": "WEDJA OLIVEIRA DE SOUSA", "NM_URNA_CANDIDATO": "WEDJA DE BILA", "NR_CPF_CANDIDATO": "-4",
    "SG_PARTIDO": "DC", "DS_SITUACAO_CANDIDATURA": "APTO", "DS_SIT_TOT_TURNO": "ELEITO POR QP",
    "DS_OCUPACAO": "VEREADOR", "DS_GENERO": "FEMININO", "DS_GRAU_INSTRUCAO": "SUPERIOR COMPLETO",
}


def test_candidato_do_tse() -> None:
    c = candidato_do_tse(LINHA, {("PE", "CARPINA"): "2604007"})
    assert c["municipio_ibge"] == "2604007"
    assert c["cargo"] == "VEREADOR"
    assert c["eleito"] is True
    assert c["nome_normalizado"] == "WEDJA OLIVEIRA DE SOUSA"
    nao = candidato_do_tse({**LINHA, "DS_SIT_TOT_TURNO": "SUPLENTE"}, {})
    assert nao["eleito"] is False and nao["municipio_ibge"] is None
    nulo = candidato_do_tse({**LINHA, "DS_SIT_TOT_TURNO": "#NULO"}, {})
    assert nulo["resultado"] is None


def test_eleicao_geral_nao_tem_municipio() -> None:
    c = candidato_do_tse({**LINHA, "TP_ABRANGENCIA": "ESTADUAL", "NM_UE": "PERNAMBUCO", "DS_CARGO": "DEPUTADO ESTADUAL"},
                         {("PE", "PERNAMBUCO"): "x"})
    assert c["municipio_ibge"] is None and c["cargo"] == "DEPUTADO ESTADUAL"


def test_mapa_municipios_aproximado() -> None:
    from civic.tse import MapaMunicipios

    mapa = MapaMunicipios([("2905206", "BA", "CAMACAN"), ("1100098", "RO", "ESPIGAO D OESTE"), ("2604007", "PE", "CARPINA")])
    assert mapa.get(("PE", "CARPINA")) == "2604007"
    assert mapa.get(("BA", "CAMACA")) == "2905206"
    assert mapa.get(("RO", "ESPIGAO DO OESTE")) == "1100098"
    assert mapa.get(("PE", "LUGAR NENHUM")) is None
    assert mapa.get(("SP", "CARPINA")) is None  # só procura na mesma UF
