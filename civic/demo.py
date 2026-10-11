"""Banco de exemplo para desenvolvimento: sobe o site sem baixar nada das fontes.

Uso:
    DATABASE_URL=sqlite:///data/demo.db python -m civic.demo

Todos os nomes, CNPJs e valores são FICTÍCIOS (CNPJs com raiz 99...), só para que
cada página tenha algo para mostrar: cota de deputados, emendas e Emenda Pix de uma
cidade, prefeitura e câmara (TCE), pessoal, contratos (PNCP), contas (Siconfi),
eleitos e doadores, sinais de alerta e a busca por nome.
"""

from __future__ import annotations

import logging
import random
import sys
from datetime import date, datetime

from sqlalchemy.orm import Session

from civic.alertas import recalcular_alertas
from civic.busca import reconstruir_indice
from civic.cleaning import normalizar_nome
from civic.config import get_settings
from civic.database import SessionLocal, init_db
from civic.models import (
    Candidato,
    ContaMunicipal,
    ContratoPncp,
    Deputado,
    Despesa,
    DespesaMunicipal,
    DoacaoCampanha,
    EmendaPagamento,
    EnteSiconfi,
    Fornecedor,
    Municipio,
    PagamentoMunicipal,
    PlanoPix,
    RepassePix,
    ServidorMunicipal,
    Socio,
    SyncExecucao,
    SyncPncpDia,
    UnidadeGestora,
)

logger = logging.getLogger("civic.demo")

AGORA = datetime(2026, 9, 1, 12, 0)
CIDADE = ("2699901", "Vila Exemplo", "PE")  # código IBGE fictício
VIZINHAS = [(f"26999{i:02d}", f"Cidade Vizinha {i}", "PE") for i in range(2, 8)]
EMPRESAS = [
    ("99000001000101", "CONSTRUTORA EXEMPLO LTDA", "2062", date(2024, 11, 20), 1_000_000_00),
    ("99000002000102", "POSTO MODELO LTDA", "2062", date(2015, 3, 2), 25_000_000),
    ("99000003000103", "GRAFICA FICTICIA ME", "2135", date(2020, 6, 1), 1_000_000),
    ("99000004000104", "LOCADORA DEMONSTRACAO LTDA", "2062", date(2019, 1, 10), 50_000_000),
]


def _brl(reais: float) -> int:
    return int(round(reais * 100))


def popular(db: Session) -> None:
    rnd = random.Random(42)
    ibge, nome, uf = CIDADE
    for codigo, n, u in [CIDADE, *VIZINHAS]:
        db.add(Municipio(codigo_ibge=codigo, nome=n, nome_normalizado=normalizar_nome(n), sigla_uf=u,
                         populacao=rnd.randint(30_000, 120_000)))
        db.add(EnteSiconfi(codigo_ibge=codigo, nome=n, sigla_uf=u, cnpj=f"9911{codigo}000"[:14].ljust(14, "0")))
        for ano in (2024, 2025):
            for cod, conta, base in (("TOTAL", "Despesas Exceto Intraorçamentárias", 300), ("10", "10 - Saúde", 90),
                                     ("12", "12 - Educação", 110), ("04.131", "04.131 - Comunicação Social", 2)):
                valor = _brl(base * 1_000_000 * rnd.uniform(0.7, 1.3))
                db.add(ContaMunicipal(codigo_ibge=codigo, ano=ano, cod_conta=cod, conta=conta,
                                      nivel="total" if cod == "TOTAL" else ("subfuncao" if "." in cod else "funcao"),
                                      empenhado_centavos=valor, liquidado_centavos=valor, pago_centavos=valor))

    # Deputados e cota
    deputados = [(900001, "Fulana de Exemplo", "PXX"), (900002, "Beltrano Fictício", "PYY")]
    for id_, n, partido in deputados:
        db.add(Deputado(id=id_, nome=n, nome_normalizado=normalizar_nome(n), sigla_partido=partido, sigla_uf=uf,
                        id_legislatura=57, atualizado_em=AGORA))
    db.flush()
    for cnpj, razao, natureza, abertura, capital in EMPRESAS:
        db.add(Fornecedor(cnpj=cnpj, razao_social=razao, natureza_juridica=natureza, data_inicio_atividade=abertura,
                          capital_social_centavos=capital, situacao_cadastral="ATIVA", municipio=nome.upper(),
                          sigla_uf=uf, codigo_municipio_ibge=ibge, referencia="2026-09", atualizado_em=AGORA))
    for i in range(40):
        dep = deputados[i % 2][0]
        cnpj, razao, *_ = EMPRESAS[2 if i % 3 else 3]
        valor = _brl(rnd.uniform(800, 9000))
        db.add(Despesa(hash_unico=f"demo-{i}", deputado_id=dep, ano=2025, mes=1 + i % 12,
                       data_documento=date(2025, 1 + i % 12, 1 + i % 27),
                       tipo_despesa="DIVULGAÇÃO DA ATIVIDADE PARLAMENTAR." if i % 3 == 0 else "LOCAÇÃO OU FRETAMENTO DE VEÍCULOS AUTOMOTORES",
                       fornecedor=razao, cnpj_cpf=cnpj, num_documento=str(1000 + i),
                       valor_documento_centavos=valor, valor_glosa_centavos=0, valor_liquido_centavos=valor))

    # Emendas e Emenda Pix
    for i, (tipo, valor) in enumerate((("Emenda Individual - Transferências Especiais", 990_000),
                                       ("Emenda Individual - Transferências com Finalidade Definida", 500_000))):
        db.add(EmendaPagamento(codigo_emenda=f"2025{i}", ano_emenda=2025, ano=2025, mes=12, tipo_emenda=tipo,
                               nome_autor="FULANA DE EXEMPLO", nome_autor_normalizado="FULANA DE EXEMPLO",
                               deputado_id=900001, favorecido=f"MUNICIPIO DE {nome.upper()}", sigla_uf=uf,
                               municipio=nome.upper(), municipio_normalizado=normalizar_nome(nome),
                               valor_recebido_centavos=_brl(valor)))
    db.add(PlanoPix(id=1, ano=2025, situacao="CIENTE", municipio_ibge=ibge, parlamentar="Fulana de Exemplo",
                    objeto="Reforma da praça central com acessibilidade", metas="Reforma da praça central",
                    investimento_centavos=_brl(990_000), custeio_centavos=0, atualizado_em=AGORA))
    db.add(RepassePix(id=1, plano_id=1, data=date(2025, 12, 2), valor_centavos=_brl(990_000)))

    # Prefeitura e câmara (formato do TCE-PE)
    for id_, orgao, natureza in ((9169, f"Prefeitura Municipal de {nome}", "Prefeitura Municipal"),
                                 (9170, f"Câmara Municipal de {nome}", "Câmara Municipal")):
        db.add(UnidadeGestora(id=id_, nome=orgao, natureza=natureza, fonte="TCE-PE", codigo_origem=str(id_),
                              codigo_municipio_tce="X999", municipio=nome, municipio_normalizado=normalizar_nome(nome),
                              sigla_uf=uf))
    db.flush()
    for i in range(60):
        cnpj, razao, *_ = EMPRESAS[i % len(EMPRESAS)]
        ano = 2025 if i % 2 else 2026
        valor = _brl(rnd.uniform(5_000, 400_000))
        pix = i % 10 == 0
        db.add(DespesaMunicipal(
            chave=f"demo|{i}", unidade_gestora_id=9169 if i % 7 else 9170, ano=ano, mes=1 + i % 8,
            data_empenho=date(ano, 1 + i % 8, 5), numero_empenho=f"{i:04d}", id_empenho=str(i), fornecedor=razao,
            fornecedor_normalizado=normalizar_nome(razao), cpf_cnpj=cnpj, tipo_pessoa="PJ",
            elemento_despesa="Material de Consumo" if i % 2 else "Obras e Instalações",
            funcao="Saúde" if i % 2 else "Urbanismo", historico=f"Despesa de exemplo número {i}",
            historico_normalizado=f"DESPESA DE EXEMPLO NUMERO {i}",
            fonte_recurso="Transferência Especial da União" if pix else "Recursos Ordinários",
            categoria_economica="Despesa Corrente" if i % 2 else "Despesa de Capital",
            valor_empenhado_centavos=valor, valor_liquidado_centavos=valor, valor_pago_centavos=valor))
        db.add(PagamentoMunicipal(unidade_gestora_id=9169 if i % 7 else 9170, ano=ano, id_empenho=str(i),
                                  data=date(ano, 1 + i % 8, 20), tipo="Pagamento", valor_centavos=valor))
    for mes in range(1, 9):
        valor = _brl(rnd.uniform(4_000_000, 5_000_000))
        db.add(DespesaMunicipal(
            chave=f"demo|folha|{mes}", unidade_gestora_id=9169, ano=2026, mes=mes, data_empenho=date(2026, mes, 1),
            id_empenho=f"f{mes}", fornecedor="SECRETARIA DE ADMINISTRACAO", fornecedor_normalizado="SECRETARIA DE ADMINISTRACAO",
            elemento_despesa="Vencimentos e Vantagens Fixas - Pessoal Civil", historico="Folha do mês",
            valor_empenhado_centavos=valor, valor_liquidado_centavos=valor, valor_pago_centavos=valor))
        db.add(PagamentoMunicipal(unidade_gestora_id=9169, ano=2026, id_empenho=f"f{mes}", data=date(2026, mes, 28),
                                  tipo="Pagamento", valor_centavos=valor))
    pessoas = [("MARIA EXEMPLAR DA SILVA", "SECRETARIA DE OBRAS", "Cargo Comissionado", date(2025, 1, 2), "111222"),
               ("JOAO DEMONSTRATIVO", "PROFESSOR", "Efetivo / Vitalício", date(2012, 3, 1), "333444"),
               ("ANA FICTICIA SOUZA", "AUXILIAR", "Contratação por Excepcional Interesse Público", date(2025, 2, 1), "555666"),
               ("PEDRO VEREADOR EXEMPLO", "VEREADOR", "Eletivo", date(2025, 1, 1), "777888")]
    for n, cargo, vinculo, admissao, cpf in pessoas:
        db.add(ServidorMunicipal(unidade_gestora_id=9170 if cargo == "VEREADOR" else 9169, nome=n,
                                 nome_normalizado=n, cargo=cargo, vinculo=vinculo, data_admissao=admissao,
                                 cpf_meio=cpf, hash_cpf=f"H{cpf}", ano_remessa=2026, mes_remessa=8))
    # A secretária é sócia da construtora: aparece no alerta "servidor sócio" e na busca.
    db.add(Socio(cnpj_basico="99000001", tipo="PF", nome="MARIA EXEMPLAR DA SILVA",
                 nome_normalizado="MARIA EXEMPLAR DA SILVA", documento="111222", qualificacao="Sócio-Administrador"))

    # Contratos (PNCP), eleitos e doadores
    for i, (cnpj, razao, *_) in enumerate(EMPRESAS):
        db.add(ContratoPncp(numero_controle=f"99999999000199-2-{i:06d}/2025", orgao_cnpj="99999999000199",
                            orgao_nome=f"MUNICIPIO DE {nome.upper()}", municipio_ibge=ibge, fornecedor_ni=cnpj,
                            fornecedor_nome=razao, tipo_pessoa="PJ", objeto=f"Contrato de exemplo {i}",
                            objeto_normalizado=f"CONTRATO DE EXEMPLO {i}", categoria="Serviços",
                            valor_global_centavos=_brl(rnd.uniform(50_000, 2_000_000)),
                            data_assinatura=date(2025, 2 + i, 10), ano=2025, atualizado_em=AGORA))
    db.add(SyncPncpDia(data=date(2025, 1, 1), registros=0, concluido_em=AGORA))
    db.add(Candidato(sq_candidato="demo1", ano=2024, cargo="PREFEITO", sigla_uf=uf, municipio_ibge=ibge,
                     nome="CARLOS PREFEITO EXEMPLO", nome_normalizado="CARLOS PREFEITO EXEMPLO",
                     sigla_partido="PXX", eleito=True, bens_centavos=_brl(850_000)))
    db.add(DoacaoCampanha(ano=2024, sq_candidato="demo1", doador_nome="MARIA EXEMPLAR DA SILVA",
                          doador_nome_normalizado="MARIA EXEMPLAR DA SILVA", doador_cpf_meio="111222",
                          valor_centavos=_brl(5_000)))
    for fonte in ("camara-bulk", "emendas", "tce", "pncp", "siconfi", "tse", "cnpj", "transferegov"):
        db.add(SyncExecucao(fonte=fonte, concluido_em=AGORA, registros=1))
    db.commit()


def main() -> int:
    logging.basicConfig(level="INFO", format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    s = get_settings()
    if "demo" not in s.database_url:
        logger.error("Por segurança, use um banco com 'demo' no nome: DATABASE_URL=sqlite:///data/demo.db")
        return 2
    init_db()
    with SessionLocal() as db:
        if db.query(Municipio).count():
            logger.info("O banco de exemplo já tem dados; apague o arquivo para gerar de novo.")
            return 0
        popular(db)
        logger.info("Alertas: %s", recalcular_alertas(db, s))
        logger.info("Busca: %s", reconstruir_indice(db))
    logger.info("Pronto. Cidade de exemplo: /cidade/PE/Vila Exemplo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
