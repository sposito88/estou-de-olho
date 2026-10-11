from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from civic import alertas
from civic.config import Settings
from civic.models import (
    Alerta,
    DeputadoEstadual,
    DespesaMunicipal,
    Fornecedor,
    UnidadeGestora,
    VerbaIndenizatoria,
)
from tests.conftest import AGORA, deputado, despesa

NICHO = "11111111000111"
GRANDE = "22222222000122"


def _fornecedor(cnpj: str, **campos: object) -> Fornecedor:
    return Fornecedor(cnpj=cnpj, referencia="2026-09", atualizado_em=AGORA, **campos)


def test_formatar_brl() -> None:
    assert alertas.formatar_brl(123456) == "R$ 1.234,56"
    assert alertas.formatar_brl(5) == "R$ 0,05"
    assert alertas.formatar_brl(-100) == "-R$ 1,00"
    assert alertas.formatar_brl(10_000_000_00) == "R$ 10.000.000,00"


class TestNumerosEmSequencia:
    def test_sequencia_quase_continua(self) -> None:
        assert alertas.numeros_em_sequencia(["39", "40", "41", "43", "44", "45"], 6) == (6, 39, 45)

    def test_ignora_nao_numericos_e_repetidos(self) -> None:
        nums = ["NF-101", "102", "102", "103", "104", "105", "106", "abc", ""]
        assert alertas.numeros_em_sequencia(nums, 6) == (6, 101, 106)

    def test_numeros_espalhados_nao_sao_sequencia(self) -> None:
        assert alertas.numeros_em_sequencia(["10", "500", "1200", "3000", "4500", "9000"], 6) is None

    def test_poucos_numeros(self) -> None:
        assert alertas.numeros_em_sequencia(["1", "2", "3"], 6) is None


def test_concentracao_so_para_fornecedor_de_nicho(db: Session, settings: Settings) -> None:
    db.add_all([deputado(1, "Ana"), deputado(2, "Bia"), deputado(3, "Caio"), deputado(4, "Duda"),
                deputado(5, "Eva"), deputado(6, "Fabi")])
    db.flush()
    # Ana: 80% da cota com uma empresa que só atende ela.
    db.add(despesa(1, 2025, 1, 4_000_000, cnpj=NICHO, fornecedor="Agência Nicho", num="1"))
    db.add(despesa(1, 2025, 2, 1_000_000, cnpj=GRANDE, fornecedor="Aérea", num="2"))
    # A "Aérea" atende 6 deputados: nunca entra, mesmo com 100% da cota de alguém.
    for dep in range(2, 7):
        db.add(despesa(dep, 2025, 1, 5_000_000, cnpj=GRANDE, fornecedor="Aérea", num=f"9{dep}"))
    db.commit()

    resultado = alertas.alertas_concentracao(db, settings)
    assert len(resultado) == 1
    a = resultado[0]
    assert (a["pessoa"], a["cnpj"], a["ano"], a["gravidade"]) == (1, NICHO, 2025, "alta")
    assert "80%" in a["titulo"]
    assert "só este deputado" in a["descricao"]


def test_concentracao_respeita_valor_minimo(db: Session, settings: Settings) -> None:
    db.add(deputado(1, "Ana"))
    db.flush()
    db.add(despesa(1, 2025, 1, 100_000, cnpj=NICHO, num="1"))  # R$ 1.000: abaixo do mínimo
    db.commit()
    assert alertas.alertas_concentracao(db, settings) == []


def test_notas_sequenciais(db: Session, settings: Settings) -> None:
    db.add(deputado(1, "Ana"))
    db.flush()
    for i, num in enumerate(["39", "40", "41", "42", "44", "45"]):
        db.add(despesa(1, 2025, i + 1, 100_000, cnpj=NICHO, fornecedor="CK Design", num=num))
    # Recibos não contam (numeração pode ser do próprio gabinete).
    for i in range(6):
        db.add(despesa(1, 2025, i + 1, 100_000, cnpj=GRANDE, num=str(i + 1), tipo_documento="Recibos/Outros"))
    db.commit()
    resultado = alertas.alertas_notas_sequenciais(db, settings)
    assert [(a["cnpj"], a["titulo"]) for a in resultado] == [(NICHO, "6 notas quase seguidas de CK Design em 2025")]


def test_empresa_nova(db: Session, settings: Settings) -> None:
    db.add(deputado(1, "Ana"))
    db.add(_fornecedor(NICHO, data_inicio_atividade=date(2025, 1, 1)))
    db.add(_fornecedor(GRANDE, data_inicio_atividade=date(2010, 1, 1)))
    db.flush()
    db.add(despesa(1, 2025, 2, 2_000_000, cnpj=NICHO, num="1", data=date(2025, 2, 15)))
    db.add(despesa(1, 2025, 2, 2_000_000, cnpj=GRANDE, num="2", data=date(2025, 2, 15)))
    db.commit()
    resultado = alertas.alertas_empresa_nova(db, settings, alertas.FONTES["federal"])
    assert len(resultado) == 1
    assert resultado[0]["cnpj"] == NICHO
    assert resultado[0]["gravidade"] == "alta"  # 45 dias e R$ 20 mil
    assert resultado[0]["titulo"].endswith("45 dias antes da primeira nota")


def test_fornecedor_inativo(db: Session, settings: Settings) -> None:
    db.add(deputado(1, "Ana"))
    db.add(_fornecedor(NICHO, situacao_cadastral="BAIXADA", data_situacao_cadastral=date(2025, 3, 1)))
    db.flush()
    db.add(despesa(1, 2025, 2, 100_000, cnpj=NICHO, num="1", data=date(2025, 2, 20)))  # antes: ok
    db.add(despesa(1, 2025, 4, 300_000, cnpj=NICHO, num="2", data=date(2025, 4, 2)))  # depois: alerta
    db.commit()
    resultado = alertas.alertas_fornecedor_inativo(db, settings, alertas.FONTES["federal"])
    assert len(resultado) == 1
    assert resultado[0]["valor_centavos"] == 300_000
    assert "1 notas" in resultado[0]["titulo"] and "baixada" in resultado[0]["titulo"]


def test_mei_acima_do_limite(db: Session, settings: Settings) -> None:
    db.add_all([deputado(1, "Ana"), deputado(2, "Bia")])
    db.add(_fornecedor(NICHO, opcao_mei=True, data_opcao_mei=date(2020, 1, 1)))
    # Deixou de ser MEI antes de 2025: não conta.
    db.add(_fornecedor(GRANDE, opcao_mei=False, data_opcao_mei=date(2018, 1, 1), data_exclusao_mei=date(2024, 6, 30)))
    db.flush()
    db.add(despesa(1, 2025, 1, 5_000_000, cnpj=NICHO, num="1"))
    db.add(despesa(2, 2025, 2, 4_000_000, cnpj=NICHO, num="2"))  # total R$ 90 mil > R$ 81 mil
    db.add(despesa(1, 2025, 3, 9_000_000, cnpj=GRANDE, num="3"))
    db.commit()
    resultado = sorted(alertas.alertas_mei_acima_limite(db, settings), key=lambda a: a["pessoa"])
    assert [(a["pessoa"], a["valor_centavos"]) for a in resultado] == [(1, 5_000_000), (2, 4_000_000)]
    assert "R$ 90.000,00" in resultado[0]["titulo"]


def test_divulgacao_eleitoral(db: Session, settings: Settings) -> None:
    db.add_all([deputado(1, "Ana"), deputado(2, "Bia")])
    db.flush()
    tipo = "DIVULGAÇÃO DA ATIVIDADE PARLAMENTAR."
    db.add(despesa(1, 2025, 3, 1_000_000, tipo=tipo, num="1"))
    db.add(despesa(1, 2026, 3, 5_000_000, tipo=tipo, num="2"))  # 5x em ano de eleição
    db.add(despesa(1, 2026, 9, 9_000_000, tipo=tipo, num="3"))  # 2º semestre não entra
    db.add(despesa(2, 2025, 3, 3_000_000, tipo=tipo, num="4"))
    db.add(despesa(2, 2026, 3, 4_000_000, tipo=tipo, num="5"))  # só 1,3x
    db.commit()
    resultado = alertas.alertas_divulgacao_eleitoral(db, settings, alertas.FONTES["federal"])
    assert [(a["pessoa"], a["ano"], a["valor_centavos"]) for a in resultado] == [(1, 2026, 5_000_000)]
    assert "5.0×" in resultado[0]["titulo"]


def test_padrao_atipico_fim_de_semana(db: Session) -> None:
    s = Settings(_env_file=None, alerta_padrao_min_notas=10)  # type: ignore[call-arg]
    db.add_all([deputado(i, f"Dep {i}") for i in range(1, 5)])
    db.flush()
    sabado, terca = date(2025, 3, 8), date(2025, 3, 11)
    for dep in range(1, 5):
        for i in range(10):
            fds = dep == 1 and i < 6  # deputado 1: 60% em fim de semana; demais: 0%
            db.add(despesa(dep, 2025, 3, 10_000, num=f"{dep}{i}", data=sabado if fds else terca))
    db.commit()
    resultado = alertas.alertas_padrao_atipico(db, s)
    assert [(a["pessoa"], a["titulo"]) for a in resultado] == [(1, "60% das notas com data em fim de semana em 2025")]


def test_recalcular_substitui_tudo(db: Session, settings: Settings) -> None:
    db.add(deputado(1, "Ana"))
    db.flush()
    db.add(despesa(1, 2025, 1, 4_000_000, cnpj=NICHO, num="1"))
    db.commit()
    assert alertas.recalcular_alertas(db, settings) == {"concentracao": 1}
    assert alertas.recalcular_alertas(db, settings) == {"concentracao": 1}
    assert len(db.scalars(select(Alerta)).all()) == 1


# --------------------------------------------------------------------------- estadual e municipal


def _estadual(db: Session) -> None:
    db.add(DeputadoEstadual(id=4508, nome="Abimael Santos", nome_normalizado="ABIMAEL SANTOS", em_exercicio=True,
                            atualizado_em=AGORA))
    db.add(UnidadeGestora(id=169, nome="Prefeitura Municipal de Carpina", natureza="Prefeitura Municipal",
                          codigo_municipio_tce="P042", municipio="Carpina", municipio_normalizado="CARPINA"))
    db.flush()


def _verba(valor: int, data: date, cnpj: str = NICHO, mes: int = 1) -> VerbaIndenizatoria:
    return VerbaIndenizatoria(docid="1", deputado_estadual_id=4508, ano=data.year, mes=mes, rubrica=3,
                              rubrica_nome="ASSESSORIA JURÍDICA", data=data, cnpj_cpf=cnpj, tipo_pessoa="PJ",
                              fornecedor="Advocacia X", valor_centavos=valor)


def _empenho(chave: str, valor: int, data: date, cnpj: str = NICHO) -> DespesaMunicipal:
    return DespesaMunicipal(chave=chave, unidade_gestora_id=169, ano=data.year, mes=data.month, data_empenho=data,
                            fornecedor="Construtora Y", cpf_cnpj=cnpj, tipo_pessoa="PJ",
                            valor_pago_centavos=valor, valor_empenhado_centavos=valor)


def test_empresa_nova_estadual_e_municipal(db: Session, settings: Settings) -> None:
    _estadual(db)
    db.add(_fornecedor(NICHO, data_inicio_atividade=date(2025, 1, 1)))
    db.add(_verba(2_000_000, date(2025, 1, 31)))
    db.add(_empenho("e1", 5_000_000, date(2025, 3, 1)))
    db.add(_empenho("e2", 0, date(2025, 1, 2)))  # empenho sem pagamento não conta
    db.commit()
    estadual = alertas.alertas_empresa_nova(db, settings, alertas.FONTES["estadual"])
    assert [(a["pessoa"], a["titulo"]) for a in estadual] == [
        (4508, "Advocacia X foi aberta 30 dias antes da primeira nota")
    ]
    municipal = alertas.alertas_empresa_nova(db, settings, alertas.FONTES["municipal"])
    assert [(a["pessoa"], a["titulo"]) for a in municipal] == [
        (169, "Construtora Y foi aberta 59 dias antes do primeiro empenho")
    ]
    assert "para o órgão" in municipal[0]["descricao"]


def test_mei_soma_todas_as_fontes(db: Session, settings: Settings) -> None:
    _estadual(db)
    db.add(deputado(1, "Ana"))
    db.add(_fornecedor(NICHO, opcao_mei=True, data_opcao_mei=date(2020, 1, 1)))
    db.flush()
    # Cada fonte sozinha fica abaixo de R$ 81 mil; somadas passam.
    db.add(despesa(1, 2025, 1, 3_000_000, cnpj=NICHO, num="1"))
    db.add(_verba(3_000_000, date(2025, 2, 1)))
    db.add(_empenho("e1", 3_000_000, date(2025, 3, 1)))
    db.commit()
    resultado = sorted(alertas.alertas_mei_acima_limite(db, settings), key=lambda a: a["fonte"])
    assert [(a["fonte"], a["pessoa"], a["valor_centavos"]) for a in resultado] == [
        ("estadual", 4508, 3_000_000),
        ("federal", 1, 3_000_000),
        ("municipal", 169, 3_000_000),
    ]
    assert "R$ 90.000,00" in resultado[0]["titulo"]


def test_recalcular_grava_esfera_e_coluna_certa(db: Session, settings: Settings) -> None:
    _estadual(db)
    db.add(_fornecedor(NICHO, data_inicio_atividade=date(2025, 1, 1)))
    db.add(_verba(2_000_000, date(2025, 1, 31)))
    db.add(_empenho("e1", 5_000_000, date(2025, 3, 1)))
    db.commit()
    assert alertas.recalcular_alertas(db, settings) == {"empresa_nova": 2}
    gravados = {(a.esfera, a.deputado_id, a.deputado_estadual_id, a.unidade_gestora_id) for a in db.scalars(select(Alerta))}
    assert gravados == {("estadual", None, 4508, None), ("municipal", None, None, 169)}


# --------------------------------------------------------------------------- cruzamentos com sócios


def test_servidor_socio_e_eleito_socio(db: Session, settings: Settings) -> None:
    from civic.models import Candidato, ContratoPncp, Municipio, ServidorMunicipal, Socio

    _estadual(db)  # cria a Prefeitura de Carpina (169)
    db.add(_fornecedor(NICHO, natureza_juridica="2062"))
    db.add(Municipio(codigo_ibge="2604007", nome="Carpina", nome_normalizado="CARPINA", sigla_uf="PE"))
    db.add(Socio(cnpj_basico=NICHO[:8], tipo="PF", nome="JOSE DA SILVA SANTOS", nome_normalizado="JOSE DA SILVA SANTOS",
                 documento="063774", qualificacao="Sócio-Administrador"))
    # Mesmo nome, CPF diferente: não pode casar no alerta de servidor.
    db.add(ServidorMunicipal(unidade_gestora_id=169, nome="JOSE DA SILVA SANTOS", nome_normalizado="JOSE DA SILVA SANTOS",
                             cargo="ASSESSOR", cpf_meio="999999"))
    db.add(ServidorMunicipal(unidade_gestora_id=169, nome="JOSÉ DA SILVA SANTOS", nome_normalizado="JOSE DA SILVA SANTOS",
                             cargo="VEREADOR", cpf_meio="063774"))
    db.add(_empenho("e1", 5_000_000, date(2025, 3, 1)))
    db.add(Candidato(sq_candidato="1", ano=2024, cargo="VEREADOR", sigla_uf="PE", municipio_ibge="2604007",
                     nome="JOSE DA SILVA SANTOS", nome_normalizado="JOSE DA SILVA SANTOS", sigla_partido="DC", eleito=True))
    db.add(Candidato(sq_candidato="2", ano=2024, cargo="VEREADOR", sigla_uf="PE", municipio_ibge="2604007",
                     nome="JOSE SILVA", nome_normalizado="JOSE SILVA", eleito=True))  # nome curto demais
    db.add(ContratoPncp(numero_controle="x", orgao_cnpj="11111111000199", orgao_nome="MUNICIPIO DE CARPINA",
                        municipio_ibge="2604007", fornecedor_ni=NICHO, fornecedor_nome="Construtora Y", tipo_pessoa="PJ",
                        valor_global_centavos=9_000_000, ano=2025, atualizado_em=AGORA))
    db.commit()

    servidor = alertas.alertas_servidor_socio(db, settings)
    assert len(servidor) == 1
    assert servidor[0]["unidade_gestora_id"] == 169 and servidor[0]["gravidade"] == "alta"
    assert "(vereador)" in servidor[0]["titulo"]

    eleito = sorted(alertas.alertas_eleito_socio(db, settings), key=lambda a: a["valor_centavos"])
    assert [(a["unidade_gestora_id"], a["orgao_cnpj"], a["valor_centavos"]) for a in eleito] == [
        (169, None, 5_000_000), (None, "11111111000199", 9_000_000)
    ]
    assert all("homônimo" in a["descricao"] for a in eleito)

    contagem = alertas.recalcular_alertas(db, settings)
    assert contagem["servidor_socio"] == 1 and contagem["eleito_socio"] == 2


def test_cruzamentos_ignoram_administracao_publica(db: Session, settings: Settings) -> None:
    from civic.models import ServidorMunicipal, Socio

    _estadual(db)
    db.add(_fornecedor(NICHO, natureza_juridica="1104"))  # autarquia: o "sócio" é o dirigente
    db.add(Socio(cnpj_basico=NICHO[:8], tipo="PF", nome="JOSE DA SILVA SANTOS", nome_normalizado="JOSE DA SILVA SANTOS",
                 documento="063774"))
    db.add(ServidorMunicipal(unidade_gestora_id=169, nome="JOSE DA SILVA SANTOS", nome_normalizado="JOSE DA SILVA SANTOS",
                             cargo="DIRETOR", cpf_meio="063774", data_admissao=date(2021, 1, 1)))
    db.add(_empenho("e1", 5_000_000, date(2025, 3, 1)))
    db.commit()
    assert alertas.alertas_servidor_socio(db, settings) == []

    db.get(Fornecedor, NICHO).natureza_juridica = "3999"  # type: ignore[union-attr]  # associação
    db.commit()
    assert alertas.alertas_servidor_socio(db, settings) == []
    db.get(Fornecedor, NICHO).natureza_juridica = "2062"  # type: ignore[union-attr]  # LTDA
    db.commit()
    [a] = alertas.alertas_servidor_socio(db, settings)
    assert "admissão em 01/01/2021" in a["descricao"]



def test_servidor_socio_nao_multiplica_por_vinculos(db: Session, settings: Settings) -> None:
    """Pessoa com 5 vínculos e sócia repetida no quadro: o valor e os empenhos não podem se multiplicar."""
    from civic.models import ServidorMunicipal, Socio

    _estadual(db)
    db.add(_fornecedor(NICHO, natureza_juridica="2062"))
    for qualificacao in ("Sócio-Administrador", "Administrador"):
        db.add(Socio(cnpj_basico=NICHO[:8], tipo="PF", nome="ORLANDO FRANCISCO DA SILVA",
                     nome_normalizado="ORLANDO FRANCISCO DA SILVA", documento="931274", qualificacao=qualificacao))
    for ano, cargo in enumerate(["COORDENADOR", "DIRETOR DE GABINETE", "CHEFE DE GABINETE", "ASSESSOR", "DIRETOR"],
                                start=2017):
        db.add(ServidorMunicipal(unidade_gestora_id=169, nome="ORLANDO FRANCISCO DA SILVA",
                                 nome_normalizado="ORLANDO FRANCISCO DA SILVA", cargo=cargo, cpf_meio="931274",
                                 data_admissao=date(ano, 1, 15)))
    db.add(_empenho("e1", 5_000_000, date(2025, 3, 1)))
    db.add(_empenho("e2", 1_000_000, date(2025, 4, 1)))
    db.commit()
    [a] = alertas.alertas_servidor_socio(db, settings)
    assert a["valor_centavos"] == 6_000_000
    assert "em 2 empenho(s)" in a["descricao"]
    assert "(diretor)" in a["titulo"]  # o vínculo mais recente
    assert "admissão em 15/01/2021" in a["descricao"] and "5 vínculos na base desde 15/01/2017" in a["descricao"]


def test_doador_socio(db: Session, settings: Settings) -> None:
    from civic.models import Candidato, ContratoPncp, DoacaoCampanha, Municipio, Socio

    db.add(_fornecedor(NICHO, natureza_juridica="2062"))
    db.add(Municipio(codigo_ibge="2604007", nome="Carpina", nome_normalizado="CARPINA", sigla_uf="PE"))
    db.add(Candidato(sq_candidato="1", ano=2024, cargo="PREFEITO", sigla_uf="PE", municipio_ibge="2604007",
                     nome="MARIA PREFEITA", nome_normalizado="MARIA PREFEITA", sigla_partido="PSB", eleito=True))
    db.add(Socio(cnpj_basico=NICHO[:8], tipo="PF", nome="JOAO DOADOR SOUZA", nome_normalizado="JOAO DOADOR SOUZA",
                 documento="123456"))
    for _ in range(2):  # duas doações de R$ 2.500 = R$ 5.000
        db.add(DoacaoCampanha(ano=2024, sq_candidato="1", doador_nome="JOAO DOADOR SOUZA",
                              doador_nome_normalizado="JOAO DOADOR SOUZA", doador_cpf_meio="123456", valor_centavos=250_000))
    db.add(ContratoPncp(numero_controle="c2", orgao_cnpj="11111111000199", orgao_nome="MUNICIPIO DE CARPINA",
                        municipio_ibge="2604007", fornecedor_ni=NICHO, fornecedor_nome="Construtora Y", tipo_pessoa="PJ",
                        valor_global_centavos=0, ano=2025, atualizado_em=AGORA))
    # Homônimo com CPF diferente não conta.
    db.add(DoacaoCampanha(ano=2024, sq_candidato="1", doador_nome="JOAO DOADOR SOUZA",
                          doador_nome_normalizado="JOAO DOADOR SOUZA", doador_cpf_meio="999999", valor_centavos=1))
    db.add(ContratoPncp(numero_controle="c1", orgao_cnpj="11111111000199", orgao_nome="MUNICIPIO DE CARPINA",
                        municipio_ibge="2604007", fornecedor_ni=NICHO, fornecedor_nome="Construtora Y", tipo_pessoa="PJ",
                        valor_global_centavos=90_000_000, ano=2025, atualizado_em=AGORA))
    db.commit()
    [a] = alertas.alertas_doador_socio(db, settings)
    assert a["orgao_cnpj"] == "11111111000199" and a["gravidade"] == "alta"
    assert "Maria Prefeita" in a["titulo"]
    assert "doou R$ 5.000,00" in a["descricao"] and "R$ 900.000,00" in a["descricao"]


def test_doacao_do_tse_guarda_so_o_meio_do_cpf() -> None:
    from civic.cleaning import doacao_do_tse

    d = doacao_do_tse({"SQ_CANDIDATO": "1", "NM_DOADOR": "Ronaldo Felix", "NM_DOADOR_RFB": "RONALDO MANOEL FELIX DE SOUZA",
                       "NR_CPF_CNPJ_DOADOR": "10715979493", "VR_RECEITA": "513,60"}, 2024)
    assert d["doador_cpf_meio"] == "159794"
    assert "10715979493" not in str(d)
    assert d["doador_nome_normalizado"] == "RONALDO MANOEL FELIX DE SOUZA"
    assert d["valor_centavos"] == 51_360



def test_doador_socio_da_cota(db: Session, settings: Settings) -> None:
    from civic.models import Candidato, DoacaoCampanha, Socio

    db.add(deputado(1, "Ana Deputada", uf="PE"))
    db.flush()
    db.add(Candidato(sq_candidato="d1", ano=2022, cargo="DEPUTADO FEDERAL", sigla_uf="PE", nome="ANA MARIA DEPUTADA",
                     nome_normalizado="ANA MARIA DEPUTADA", nome_urna="ANA DEPUTADA", eleito=True, deputado_id=1))
    db.add(DoacaoCampanha(ano=2022, sq_candidato="d1", doador_nome="CARLOS DOADOR", doador_nome_normalizado="CARLOS DOADOR",
                          doador_cpf_meio="654321", valor_centavos=1_000_000))
    db.add(Socio(cnpj_basico=NICHO[:8], tipo="PF", nome="CARLOS DOADOR", nome_normalizado="CARLOS DOADOR",
                 documento="654321", qualificacao="Sócio-Administrador"))
    db.add(despesa(1, 2024, 3, 3_000_000, cnpj=NICHO, fornecedor="Agência do Doador", num="1"))
    db.add(despesa(1, 2024, 4, 3_000_000, cnpj=GRANDE, fornecedor="Outra", num="2"))
    db.commit()
    [a] = alertas.alertas_doador_socio_cota(db, settings, alertas.FONTES["federal"])
    assert (a["pessoa"], a["cnpj"], a["valor_centavos"]) == (1, NICHO, 3_000_000)
    assert "Agência do Doador" in a["titulo"] and "R$ 10.000,00" in a["descricao"]


def test_vincular_parlamentares(db: Session) -> None:
    from civic.models import Candidato
    from civic.tse import vincular_parlamentares

    db.add(deputado(1, "Túlio Gadêlha", uf="PE"))
    db.add(deputado(2, "Túlio Gadêlha", uf="SP"))  # mesmo nome em outra UF não atrapalha
    db.flush()
    db.add(Candidato(sq_candidato="x", ano=2022, cargo="DEPUTADO FEDERAL", sigla_uf="PE", nome="TULIO GADELHA SAKAI DE MELO",
                     nome_normalizado="TULIO GADELHA SAKAI DE MELO", nome_urna="TÚLIO GADÊLHA", eleito=True))
    db.add(Candidato(sq_candidato="y", ano=2022, cargo="DEPUTADO FEDERAL", sigla_uf="PE", nome="FULANO",
                     nome_normalizado="FULANO", nome_urna="FULANO", eleito=True))
    db.commit()
    assert vincular_parlamentares(db, 2022)["DEPUTADO FEDERAL"] == 1
    assert db.get(Candidato, "x").deputado_id == 1  # type: ignore[union-attr]
