from __future__ import annotations

from civic.cleaning import despesa_senado_do_csv
from civic.senado import MapaSenadores

MAPA = MapaSenadores([(5672, "Alan Rick", "Alan Rick Miranda"), (5899, "Weverton", "Weverton Rocha Marques de Sousa"),
                      (1, "José Silva", "José da Silva"), (2, "José Souza", "José de Souza Silva")])


def test_mapa_de_senadores() -> None:
    assert MAPA.get("ALAN RICK") == 5672
    assert MAPA.get("ALAN RICK MIRANDA") == 5672
    assert MAPA.get("WEVERTON ROCHA") == 5899  # palavras contidas no nome completo de um único senador
    assert MAPA.get("JOSE") is None  # ambíguo
    assert MAPA.get("FULANO") is None


def test_despesa_senado_do_csv() -> None:
    linha = {"ANO": "2025", "MES": "1", "SENADOR": "WEVERTON ROCHA", "TIPO_DESPESA": "Divulgação da atividade parlamentar",
             "CNPJ_CPF": "860.691.872-53", "FORNECEDOR": "Fulano", "DOCUMENTO": "1", "DATA": "18/01/2025",
             "DETALHAMENTO": "", "VALOR_REEMBOLSADO": "7096,25", "COD_DOCUMENTO": "2248419"}
    d = despesa_senado_do_csv(linha, MAPA)
    assert d["senador_id"] == 5899
    assert (d["cnpj_cpf"], d["tipo_pessoa"]) == ("***.691.872-**", "PF")
    assert d["valor_centavos"] == 709_625
    assert d["detalhamento"] is None
