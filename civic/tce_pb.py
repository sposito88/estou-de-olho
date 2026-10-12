"""Quadro de pessoal com salário dos municípios da Paraíba (TCE-PB, dados abertos consolidados).

Uso:
    python -m civic.tce_pb [--ano 2026] [--sem-progresso]

O TCE-PB publica, por ano, um arquivo com cada servidor de cada órgão municipal em cada
mês: nome, CPF mascarado, cargo, tipo de vínculo, admissão e o valor recebido. Guardamos:

- em `servidores_municipais`, uma linha por pessoa e órgão, com o cargo e o salário do mês
  mais recente, o total recebido no ano e quantos meses recebeu;
- em `folhas_mensais`, a folha somada por órgão, mês e tipo de vínculo.

O arquivo do ano corrente é atualizado quase todo dia; a rotina baixa de novo e substitui.
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import sys
import time
import zipfile
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from civic.cleaning import cpf_meio, limpar_texto, normalizar_nome, parse_data
from civic.config import DATA_DIR, Settings, get_settings
from civic.database import SessionLocal, init_db
from civic.models import FolhaMensal, Municipio, ServidorMunicipal
from civic.scraper import Resumo, baixar_arquivo, criar_sessao, em_lotes, registrar_execucao
from civic.tce_sp import Orgaos, natureza_do_orgao
from civic.tse import MapaMunicipios

logger = logging.getLogger("civic.tce_pb")

FONTE = "TCE-PB"
PASTA = DATA_DIR / "downloads" / "tce_pb"


def valor_pb(texto: str | None) -> int:
    """Valor do TCE-PB em centavos: '1.734,8' -> 173480; '6.000' -> 600000 (ponto é milhar)."""
    limpo = (texto or "").strip().replace(".", "").replace(",", ".")
    if not limpo:
        return 0
    return int(round(float(limpo) * 100))


@dataclass
class Pessoa:
    ug: str
    municipio: str
    orgao: str
    nome: str
    cpf: str | None
    cargo: str | None
    vinculo: str | None
    admissao: date | None
    matricula: str | None
    ultimo_mes: int
    ultimo_valor: int
    total: int
    meses: int


def linhas_do_zip(caminho: Path) -> Iterator[dict[str, str]]:
    with zipfile.ZipFile(caminho) as zf:
        for info in zf.infolist():
            if info.filename.lower().endswith(".csv"):
                with zf.open(info) as arquivo:
                    yield from csv.DictReader(io.TextIOWrapper(arquivo, encoding="utf-8-sig"), delimiter=";")


def agregar(linhas: Iterator[dict[str, str]]) -> tuple[dict[tuple[str, str, str], Pessoa], dict[tuple[str, int, str], list[int]]]:
    """Uma Pessoa por (órgão, matrícula, CPF) e a folha por (órgão, mês, vínculo) = [qtd, total]."""
    pessoas: dict[tuple[str, str, str], Pessoa] = {}
    folha: dict[tuple[str, int, str], list[int]] = defaultdict(lambda: [0, 0])
    for l in linhas:
        ug = (l.get("codigo_unidade_gestora") or "").strip()
        ano_mes = int(l.get("ano_mes") or 0)
        if not ug or not ano_mes:
            continue
        valor = valor_pb(l.get("valor_vantagem"))
        vinculo = limpar_texto(l.get("tipo_cargo"))
        chave = (ug, (l.get("matricula") or "").strip(), (l.get("cpf_cnpj") or "").strip())
        cargo = limpar_texto(l.get("descricao_cargo"))
        if cargo and " - " in cargo and cargo.split(" - ", 1)[0].strip().isdigit():
            cargo = cargo.split(" - ", 1)[1].strip()  # "00000014 - AUXILIAR" -> "AUXILIAR"
        p = pessoas.get(chave)
        if p is None:
            p = pessoas[chave] = Pessoa(
                ug=ug, municipio=(l.get("nome_municipio") or "").strip(),
                orgao=(l.get("descricao_unidade_gestora") or "").strip(), nome=(l.get("nome_servidor") or "").strip(),
                cpf=chave[2] or None, cargo=cargo, vinculo=vinculo,
                admissao=parse_data(l.get("data_admissao")), matricula=chave[1] or None,
                ultimo_mes=0, ultimo_valor=0, total=0, meses=0,
            )
        p.total += valor
        p.meses += 1
        if ano_mes >= p.ultimo_mes:
            if ano_mes > p.ultimo_mes:
                p.ultimo_valor = 0
            p.ultimo_mes, p.ultimo_valor = ano_mes, p.ultimo_valor + valor
            p.cargo, p.vinculo = cargo or p.cargo, vinculo or p.vinculo
        item = folha[(ug, ano_mes, vinculo or "Não informado")]
        item[0] += 1
        item[1] += valor
    return pessoas, folha


def carregar_ano(db: Session, s: Settings, ano: int, caminho: Path, resumo: Resumo) -> int:
    db.rollback()  # não segura leitura aberta enquanto lê o arquivo
    pessoas, folha = agregar(linhas_do_zip(caminho))
    if not pessoas:
        raise ValueError(f"Arquivo do TCE-PB de {ano} veio vazio; nada foi substituído")

    nomes = {codigo: (nome, norm) for codigo, nome, norm in db.execute(
        select(Municipio.codigo_ibge, Municipio.nome, Municipio.nome_normalizado).where(Municipio.sigla_uf == "PB")
    )}
    mapa = MapaMunicipios([(c, "PB", n) for c, (_, n) in nomes.items()])
    orgaos = Orgaos(db, fonte=FONTE, uf="PB")
    ug_id: dict[str, int] = {}
    sem_ibge: set[str] = set()
    for p in pessoas.values():
        if p.ug in ug_id:
            continue
        ibge = mapa.get(("PB", normalizar_nome(p.municipio) or ""))
        if ibge is None:
            sem_ibge.add(p.municipio)
            continue
        natureza = natureza_do_orgao(p.orgao)
        if natureza is None:
            continue  # consórcio: atende vários municípios, distorceria a conta da cidade
        nome, norm = nomes[ibge]
        ug_id[p.ug] = orgaos.obter(ibge, p.orgao, natureza, ibge, nome, norm, codigo_orgao=p.ug)
    if sem_ibge:
        resumo.registrar_falha("TCE-PB municípios sem par no IBGE", ValueError(", ".join(sorted(sem_ibge))))

    ids = sorted(set(ug_id.values()))
    vinculos = []
    for p in pessoas.values():
        if p.ug not in ug_id:
            continue
        vinculos.append({
            "unidade_gestora_id": ug_id[p.ug], "nome": p.nome, "nome_normalizado": normalizar_nome(p.nome) or "",
            "cargo": p.cargo, "vinculo": p.vinculo, "data_admissao": p.admissao, "matricula": p.matricula,
            "cpf_meio": cpf_meio(p.cpf), "ano_remessa": p.ultimo_mes // 100, "mes_remessa": p.ultimo_mes % 100,
            "remuneracao_centavos": p.ultimo_valor, "remuneracao_mes": p.ultimo_mes,
            "remuneracao_ano_centavos": p.total, "meses_pagos": p.meses,
        })
    folhas = [
        {"unidade_gestora_id": ug_id[ug], "ano": am // 100, "mes": am % 100, "vinculo": vinculo, "qtd": qtd,
         "total_centavos": total}
        for (ug, am, vinculo), (qtd, total) in folha.items() if ug in ug_id
    ]
    db.execute(delete(ServidorMunicipal).where(ServidorMunicipal.unidade_gestora_id.in_(ids)))
    for lote in em_lotes(vinculos, 5_000):
        db.execute(insert(ServidorMunicipal), list(lote))
    db.execute(delete(FolhaMensal).where(FolhaMensal.unidade_gestora_id.in_(ids), FolhaMensal.ano == ano))
    for lote in em_lotes(folhas, 5_000):
        db.execute(insert(FolhaMensal), list(lote))
    db.commit()
    logger.info("TCE-PB %d: %d pessoas em %d órgãos, %d linhas de folha mensal", ano, len(vinculos), len(ids), len(folhas))
    return len(vinculos)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m civic.tce_pb", description=__doc__.splitlines()[0])
    parser.add_argument("--ano", type=int, default=date.today().year, help="ano do quadro (padrão: o corrente)")
    parser.add_argument("--sem-progresso", action="store_true")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args(argv)
    s = get_settings()
    logging.basicConfig(level=(args.log_level or s.log_level).upper(),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    init_db()
    resumo = Resumo()
    inicio = time.monotonic()
    with SessionLocal() as db:
        try:
            caminho = baixar_arquivo(
                criar_sessao(), f"{s.tce_pb_url}/servidores/servidores-{args.ano}.zip",
                PASTA / f"servidores-{args.ano}.zip", timeout=900, reaproveitar=False,
            )
            total = carregar_ano(db, s, args.ano, caminho, resumo)
            registrar_execucao(db, "tce_pb", total)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            resumo.registrar_falha(f"TCE-PB {args.ano}", exc)
    logger.info("TCE-PB concluído em %.1f min; falhas: %d", (time.monotonic() - inicio) / 60, len(resumo.falhas))
    for falha in resumo.falhas:
        logger.info("  - %s", falha)
    return 1 if resumo.falhas else 0


if __name__ == "__main__":
    sys.exit(main())
