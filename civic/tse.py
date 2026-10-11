"""Candidatos e eleitos (TSE): prefeitos e vereadores (2024), deputados, senadores e governadores (2022).

Uso:
    python -m civic.tse [--ano 2024 ...]

Baixa `consulta_cand_{ano}.zip` e `bem_candidato_{ano}.zip` do CDN do TSE e
substitui os candidatos do ano. O município vem do nome (UF + nome sem acento),
porque o TSE usa um código próprio e não o do IBGE.
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import sys
import zipfile
from collections import defaultdict
from collections.abc import Iterator, Sequence
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from civic.cleaning import candidato_do_tse, doacao_do_tse, normalizar_nome, para_centavos
from civic.config import Settings, get_settings
from civic.database import SessionLocal, init_db
from civic.models import Candidato, Deputado, DeputadoEstadual, DoacaoCampanha, Municipio, Senador
from civic.scraper import DOWNLOAD_DIR, Resumo, baixar_arquivo, criar_sessao, em_lotes, registrar_execucao

logger = logging.getLogger("civic.tse")


# Nomes que o TSE ainda usa e o IBGE já mudou (ou abrevia de outro jeito).
APELIDOS_MUNICIPIOS: dict[tuple[str, str], str] = {
    ("RN", "BOA SAUDE"): "2405306",  # IBGE: Januário Cicco
    ("RR", "SAO LUIZ"): "1400605",  # IBGE: São Luiz do Anauá
}


class MapaMunicipios:
    """(UF, nome normalizado) -> código IBGE, com busca aproximada na mesma UF para grafias
    diferentes entre TSE e IBGE ("CAMACA"/"CAMACAN", "ESPIGAO DO OESTE"/"ESPIGAO D OESTE")."""

    def __init__(self, linhas: list[tuple[str, str, str]]) -> None:
        self.exatos = {(uf, nome): codigo for codigo, uf, nome in linhas} | APELIDOS_MUNICIPIOS
        self.por_uf: dict[str, dict[str, str]] = defaultdict(dict)
        for codigo, uf, nome in linhas:
            self.por_uf[uf][nome] = codigo
        self.cache: dict[tuple[str, str], str | None] = {}

    def get(self, chave: tuple[str, str], padrao: str | None = None) -> str | None:
        if chave in self.exatos:
            return self.exatos[chave]
        if chave not in self.cache:
            uf, nome = chave
            parecidos = get_close_matches(nome, list(self.por_uf.get(uf, {})), n=1, cutoff=0.85)
            self.cache[chave] = self.por_uf[uf][parecidos[0]] if parecidos else None
        return self.cache[chave] if self.cache[chave] is not None else padrao


def linhas_do_zip(caminho: Path) -> Iterator[dict[str, str]]:
    """Todas as linhas dos CSVs por UF do zip (ignora o arquivo BRASIL, que repete tudo)."""
    with zipfile.ZipFile(caminho) as zf:
        for nome in sorted(zf.namelist()):
            if not nome.endswith(".csv") or nome.upper().endswith("_BRASIL.CSV"):
                continue
            with zf.open(nome) as arquivo:
                yield from csv.DictReader(io.TextIOWrapper(arquivo, encoding="latin1"), delimiter=";")


def carregar_ano(db: Session, ano: int, s: Settings, sessao: Any) -> int:
    pasta = DOWNLOAD_DIR / "tse"
    candidatos_zip = baixar_arquivo(
        sessao, f"{s.tse_cdn_url}/consulta_cand/consulta_cand_{ano}.zip", pasta / f"consulta_cand_{ano}.zip",
        timeout=600, reaproveitar=False,
    )
    bens_zip = baixar_arquivo(
        sessao, f"{s.tse_cdn_url}/bem_candidato/bem_candidato_{ano}.zip", pasta / f"bem_candidato_{ano}.zip",
        timeout=600, reaproveitar=False,
    )
    municipios = MapaMunicipios([tuple(l) for l in db.execute(
        select(Municipio.codigo_ibge, Municipio.sigla_uf, Municipio.nome_normalizado)
    )])
    bens: dict[str, int] = defaultdict(int)
    for linha in linhas_do_zip(bens_zip):
        try:
            bens[linha["SQ_CANDIDATO"].strip()] += para_centavos(linha.get("VR_BEM_CANDIDATO"))
        except ValueError:
            continue

    registros: dict[str, dict[str, Any]] = {}
    sem_municipio: set[tuple[str, str]] = set()
    for linha in linhas_do_zip(candidatos_zip):
        try:
            c = candidato_do_tse(linha, municipios)
        except (KeyError, ValueError) as exc:
            logger.warning("Candidato ignorado: %s", exc)
            continue
        c["bens_centavos"] = bens.get(c["sq_candidato"], 0)
        if (linha.get("TP_ABRANGENCIA") or "").upper() == "MUNICIPAL" and c["municipio_ibge"] is None:
            sem_municipio.add((c["sigla_uf"] or "", c["nome_ue"] or ""))
        # Em 2º turno o candidato aparece de novo: fica o registro mais recente (resultado final).
        registros[c["sq_candidato"]] = c
    db.execute(delete(Candidato).where(Candidato.ano == ano))
    for lote in em_lotes(list(registros.values()), 5_000):
        db.execute(insert(Candidato), list(lote))
    db.commit()
    if sem_municipio:
        logger.warning("TSE %d: %d municípios sem código IBGE: %s", ano, len(sem_municipio), sorted(sem_municipio)[:15])
    eleitos = sum(1 for c in registros.values() if c["eleito"])
    logger.info("TSE %d: %d candidaturas, %d eleitos", ano, len(registros), eleitos)
    return len(registros)


ORIGEM_PESSOA_FISICA = "Recursos de pessoas físicas"

# Cargo no TSE -> (modelo do cadastro, coluna em `candidatos`, filtro de UF do cadastro)
CARGOS_PARLAMENTARES: dict[str, tuple[Any, str]] = {
    "DEPUTADO FEDERAL": (Deputado, "deputado_id"),
    "SENADOR": (Senador, "senador_id"),
    "DEPUTADO ESTADUAL": (DeputadoEstadual, "deputado_estadual_id"),
}


def vincular_parlamentares(db: Session, ano: int) -> dict[str, int]:
    """Liga eleitos (deputado federal, senador, deputado estadual de PE) ao cadastro do parlamentar.

    Casa o nome de urna (ou o nome civil) com o nome parlamentar, dentro da mesma UF.
    Só vincula quando há exatamente um parlamentar com aquele nome na UF.
    """
    contagem: dict[str, int] = {}
    for cargo, (modelo, coluna) in CARGOS_PARLAMENTARES.items():
        cadastro: dict[tuple[str, str], list[int]] = defaultdict(list)
        uf_col = getattr(modelo, "sigla_uf", None)
        colunas = [modelo.id, modelo.nome_normalizado] + ([uf_col] if uf_col is not None else [])
        for linha in db.execute(select(*colunas)):
            uf = linha[2] if uf_col is not None else "PE"  # ALEPE: só Pernambuco
            cadastro[(uf or "", linha[1])].append(linha[0])
        vinculados = 0
        for c in db.scalars(select(Candidato).where(Candidato.ano == ano, Candidato.cargo == cargo, Candidato.eleito.is_(True))):
            for nome in (normalizar_nome(c.nome_urna), c.nome_normalizado):
                ids = cadastro.get((c.sigla_uf or "", nome or ""), [])
                if len(ids) == 1:
                    setattr(c, coluna, ids[0])
                    vinculados += 1
                    break
        contagem[cargo] = vinculados
    db.commit()
    logger.info("TSE %d: eleitos ligados ao cadastro: %s", ano, contagem)
    return contagem


def carregar_doacoes(db: Session, ano: int, s: Settings, sessao: Any) -> int:
    """Doações de pessoas físicas aos eleitos do ano (prestação de contas: ~1,3 GB em 2024, ~0,5 GB em 2022)."""
    caminho = baixar_arquivo(
        sessao,
        f"{s.tse_cdn_url}/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_{ano}.zip",
        DOWNLOAD_DIR / "tse" / f"prestacao_de_contas_eleitorais_candidatos_{ano}.zip",
        timeout=3600,
        reaproveitar=True,
    )
    eleitos = set(db.scalars(select(Candidato.sq_candidato).where(Candidato.ano == ano, Candidato.eleito.is_(True))))
    linhas: list[dict[str, Any]] = []
    with zipfile.ZipFile(caminho) as zf:
        for nome in sorted(zf.namelist()):
            if not (nome.startswith(f"receitas_candidatos_{ano}_") and nome.endswith(".csv")) or "BRASIL" in nome:
                continue
            with zf.open(nome) as arquivo:
                for l in csv.DictReader(io.TextIOWrapper(arquivo, encoding="latin1"), delimiter=";"):
                    if l.get("DS_ORIGEM_RECEITA") != ORIGEM_PESSOA_FISICA or l["SQ_CANDIDATO"].strip() not in eleitos:
                        continue
                    linhas.append(doacao_do_tse(l, ano))
    db.execute(delete(DoacaoCampanha).where(DoacaoCampanha.ano == ano))
    for lote in em_lotes(linhas, 5_000):
        db.execute(insert(DoacaoCampanha), list(lote))
    db.commit()
    logger.info("TSE %d: %d doações de pessoas físicas a eleitos", ano, len(linhas))
    return len(linhas)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m civic.tse", description=__doc__.splitlines()[0])
    parser.add_argument("--ano", type=int, nargs="+", help="eleições (padrão: TSE_ELEICOES)")
    parser.add_argument("--sem-doacoes", action="store_true", help="não carrega as doações (arquivo grande)")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args(argv)
    s = get_settings()
    logging.basicConfig(
        level=(args.log_level or s.log_level).upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    init_db()
    resumo = Resumo()
    db = SessionLocal()
    sessao = criar_sessao()
    total = 0
    try:
        for ano in args.ano or s.tse_eleicoes:
            try:
                total += carregar_ano(db, ano, s, sessao)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                resumo.registrar_falha(f"TSE {ano}", exc)
        for ano in [a for a in (args.ano or s.tse_eleicoes) if a % 4 == 2]:  # eleições gerais
            try:
                vincular_parlamentares(db, ano)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                resumo.registrar_falha(f"TSE vínculo {ano}", exc)
        if not args.sem_doacoes:
            for ano in args.ano or s.tse_eleicoes:
                try:
                    carregar_doacoes(db, ano, s, sessao)
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    resumo.registrar_falha(f"TSE doações {ano}", exc)
        registrar_execucao(db, "tse", total)
    finally:
        db.close()
    for falha in resumo.falhas:
        logger.info("  - %s", falha)
    return 1 if resumo.falhas else 0


if __name__ == "__main__":
    sys.exit(main())
