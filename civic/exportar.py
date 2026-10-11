"""Exporta os dados consolidados em CSV (gzip) para download público, com dicionário de dados.

Uso:
    python -m civic.exportar [--pasta data/publico]

Gera um arquivo por conjunto e um `indice.json` (o site lê para montar a página
"Dados abertos"). Os arquivos são escritos com nome temporário e trocados no fim,
então quem estiver baixando não pega um arquivo pela metade.

Privacidade: qualquer CPF completo que apareça é mascarado (***.456.789-**), o hash
de CPF dos servidores não sai, e os doadores de campanha (pessoas comuns) ficam de
fora — quem precisar pode baixar direto do TSE.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import logging
import os
import re
import sys
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from civic import __version__
from civic.config import DATA_DIR, get_settings
from civic.database import engine, init_db

logger = logging.getLogger("civic.exportar")

_CPF = re.compile(r"^\d{11}$")


def mascarar(valor: Any) -> Any:
    """CPF completo (11 dígitos) vira ***.456.789-**; o resto passa igual."""
    if isinstance(valor, str) and _CPF.match(valor):
        return f"***.{valor[3:6]}.{valor[6:9]}-**"
    return valor


# nome do arquivo -> (descrição, SQL). Valores em centavos ficam com o sufixo _centavos.
CONJUNTOS: dict[str, tuple[str, str]] = {
    "cota_deputados_federais": (
        "Despesas da Cota Parlamentar (CEAP) dos deputados federais, nota a nota.",
        """SELECT dep.id_legislatura, dep.id AS deputado_id, dep.nome AS deputado, dep.sigla_partido, dep.sigla_uf,
                  d.ano, d.mes, d.data_documento, d.tipo_despesa, d.fornecedor, d.cnpj_cpf, d.num_documento,
                  d.valor_documento_centavos, d.valor_glosa_centavos, d.valor_liquido_centavos, d.url_documento
           FROM despesas d JOIN deputados dep ON dep.id = d.deputado_id""",
    ),
    "cota_senadores": (
        "Despesas da cota dos senadores (CEAPS).",
        """SELECT senador_id, nome_senador, ano, mes, data, tipo_despesa, fornecedor, cnpj_cpf, documento,
                  valor_centavos FROM despesas_senado""",
    ),
    "emendas_pagamentos_por_municipio": (
        "Pagamentos de emendas parlamentares por município favorecido (Portal da Transparência).",
        """SELECT ano, mes, codigo_emenda, ano_emenda, tipo_emenda, nome_autor, deputado_id, favorecido,
                  tipo_favorecido, sigla_uf, municipio, valor_recebido_centavos FROM emendas_pagamentos""",
    ),
    "emenda_pix_planos": (
        "Planos de ação das transferências especiais (Emenda Pix) no Transferegov, com objeto e metas.",
        """SELECT id AS plano_id, codigo, ano, situacao, motivo_impedimento, cnpj_beneficiario, nome_beneficiario,
                  sigla_uf, municipio_ibge, parlamentar, numero_emenda, area, objeto, metas, custeio_centavos,
                  investimento_centavos, relatorio_situacao, relatorio_parecer FROM planos_pix""",
    ),
    "emenda_pix_repasses": (
        "Repasses enviados de cada Emenda Pix (data e valor).",
        "SELECT id AS repasse_id, plano_id, data, valor_centavos FROM repasses_pix",
    ),
    "despesas_municipais": (
        "Despesas de prefeituras, câmaras e autarquias (TCE-PE: por empenho; TCE-SP: por órgão, credor e ano).",
        """SELECT ug.fonte, ug.sigla_uf, ug.municipio, ug.nome AS orgao, d.ano, d.mes, d.data_empenho,
                  d.numero_empenho, d.fornecedor, d.cpf_cnpj, d.tipo_pessoa, d.elemento_despesa, d.funcao,
                  d.fonte_recurso, d.categoria_economica, d.historico, d.qtd_empenhos,
                  d.valor_empenhado_centavos, d.valor_liquidado_centavos, d.valor_pago_centavos
           FROM despesas_municipais d JOIN unidades_gestoras ug ON ug.id = d.unidade_gestora_id""",
    ),
    "pessoal_municipal": (
        "Vínculos de pessoal informados ao TCE-PE (nome, cargo, vínculo, admissão; sem salário).",
        """SELECT ug.municipio, ug.nome AS orgao, sv.nome, sv.cargo, sv.vinculo, sv.data_admissao, sv.matricula,
                  CASE WHEN sv.cpf_meio IS NOT NULL
                       THEN '***.' || substr(sv.cpf_meio, 1, 3) || '.' || substr(sv.cpf_meio, 4, 3) || '-**' END AS cpf,
                  sv.ano_remessa, sv.mes_remessa
           FROM servidores_municipais sv JOIN unidades_gestoras ug ON ug.id = sv.unidade_gestora_id""",
    ),
    "contratos_pncp": (
        "Contratos de órgãos municipais publicados no Portal Nacional de Contratações Públicas.",
        """SELECT numero_controle, orgao_cnpj, orgao_nome, municipio_ibge, fornecedor_ni, fornecedor_nome,
                  tipo_pessoa, objeto, categoria, valor_inicial_centavos, valor_global_centavos, data_assinatura,
                  ano FROM contratos_pncp""",
    ),
    "contas_municipais": (
        "Despesa por função e subfunção de cada município (Siconfi: DCA anual; RREO no ano corrente).",
        """SELECT codigo_ibge, ano, demonstrativo, periodo, cod_conta, conta, nivel, dotacao_centavos,
                  empenhado_centavos, liquidado_centavos, pago_centavos FROM contas_municipais""",
    ),
    "fornecedores": (
        "Cadastro na Receita Federal dos fornecedores (CNPJ) que receberam dinheiro público.",
        """SELECT cnpj, razao_social, nome_fantasia, situacao_cadastral, data_inicio_atividade, cnae_principal,
                  natureza_juridica, capital_social_centavos, porte, opcao_mei, sigla_uf, municipio,
                  codigo_municipio_ibge, referencia FROM fornecedores""",
    ),
    "candidatos": (
        "Candidatos de 2022 e 2024 (TSE), com resultado e bens declarados.",
        """SELECT ano, cargo, sigla_uf, municipio_ibge, nome, nome_urna, numero, sigla_partido, situacao_candidatura,
                  resultado, eleito, bens_centavos FROM candidatos""",
    ),
    "alertas": (
        "Sinais de alerta calculados pelo projeto (não são acusação), com a nota de prioridade.",
        """SELECT id, tipo, gravidade, prioridade, esfera, deputado_id, deputado_estadual_id, senador_id,
                  unidade_gestora_id, orgao_cnpj, municipio_ibge, cnpj, ano, valor_centavos, titulo, descricao,
                  calculado_em FROM alertas""",
    ),
}


def exportar(pasta: Path) -> list[dict[str, Any]]:
    pasta.mkdir(parents=True, exist_ok=True)
    itens = []
    with engine.connect() as conexao:
        for nome, (descricao, sql) in CONJUNTOS.items():
            inicio = time.monotonic()
            destino = pasta / f"{nome}.csv.gz"
            temporario = pasta / f".{nome}.csv.gz.tmp"
            resultado = conexao.execution_options(stream_results=True).execute(text(sql))
            colunas = list(resultado.keys())
            linhas = 0
            with gzip.open(temporario, "wt", encoding="utf-8", newline="") as arquivo:
                escritor = csv.writer(arquivo)
                escritor.writerow(colunas)
                for linha in resultado:
                    escritor.writerow([mascarar(v) for v in linha])
                    linhas += 1
            os.replace(temporario, destino)
            itens.append({
                "arquivo": destino.name, "descricao": descricao, "colunas": colunas, "linhas": linhas,
                "bytes": destino.stat().st_size,
            })
            logger.info("%s: %d linhas em %.0f s", destino.name, linhas, time.monotonic() - inicio)
    indice = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "versao": __version__,
        "licenca_codigo": "AGPL-3.0",
        "observacoes": [
            "Valores em centavos de real (colunas *_centavos).",
            "CPF sempre mascarado (***.456.789-**). Doadores de campanha não são exportados.",
            "Alertas são padrões calculados automaticamente para orientar a verificação; não são acusação.",
        ],
        "conjuntos": itens,
    }
    temporario = pasta / ".indice.json.tmp"
    temporario.write_text(json.dumps(indice, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporario, pasta / "indice.json")
    return itens


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m civic.exportar", description=__doc__.splitlines()[0])
    parser.add_argument("--pasta", type=Path, default=DATA_DIR / "publico")
    args = parser.parse_args(argv)
    s = get_settings()
    logging.basicConfig(level=s.log_level.upper(), format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stderr)
    init_db()
    inicio = time.monotonic()
    itens = exportar(args.pasta)
    logger.info("Exportação pronta em %.1f min: %d arquivos", (time.monotonic() - inicio) / 60, len(itens))
    return 0


if __name__ == "__main__":
    sys.exit(main())
