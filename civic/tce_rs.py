"""Despesas dos municípios gaúchos pelo TCE-RS (dados abertos, um arquivo por ano).

Uso:
    python -m civic.tce_rs [--ano 2025 ...] [--forcar]

O arquivo anual (~1,4 GB compactado) traz cada operação de cada empenho de todos os
órgãos municipais: empenho (E), liquidação (L) e pagamento (P), com credor, CNPJ/CPF,
função, elemento, fonte de recurso e histórico. Guardamos uma linha por órgão × credor
× elemento de despesa × ano, com as somas e a quantidade de empenhos (o histórico, a
função e a fonte são os do maior empenho do grupo). O CPF de pessoa física vem completo
no arquivo e é mascarado na leitura: nunca é gravado inteiro.

Órgãos: o código 4XXYY é município XX (tabela de municípios do TCE-RS) e YY 00 =
prefeitura, 01 = câmara; os demais são ligados à cidade pelo nome. Consórcios ficam de
fora (atendem várias cidades). Anos fechados ganham checkpoint.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import logging
import sys
import time
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from civic.cleaning import limpar_texto, normalizar_nome, para_centavos, parse_data
from civic.config import ANO_INICIAL_CEAP, DATA_DIR, Settings, get_settings
from civic.database import SessionLocal, init_db
from civic.models import DespesaMunicipal, Municipio, SyncMunicipioAno
from civic.scraper import Resumo, criar_sessao, em_lotes, registrar_execucao
from civic.tce_sp import Orgaos, ano_fechado, natureza_do_orgao
from civic.tse import MapaMunicipios

logger = logging.getLogger("civic.tce_rs")

FONTE = "TCE-RS"
PASTA = DATA_DIR / "downloads" / "tce_rs"


def documento_rs(tp_pessoa: str | None, documento: str | None) -> tuple[str | None, str | None, str]:
    """(documento para gravar, tipo, chave de agrupamento). CPF sai mascarado; a chave usa um hash."""
    digitos = "".join(c for c in (documento or "") if c.isdigit())
    tipo = (tp_pessoa or "").strip().upper() or None
    if tipo == "PJ" and digitos:
        cnpj = digitos.zfill(14)
        return cnpj, "PJ", cnpj
    if tipo == "PF" and digitos:
        cpf = digitos.zfill(11)
        chave = "PF:" + hashlib.sha1(cpf.encode()).hexdigest()[:16]  # agrupa sem guardar o CPF
        return f"***.{cpf[3:6]}.{cpf[6:9]}-**", "PF", chave
    return None, tipo, f"?:{digitos}"


@dataclass
class Grupo:
    orgao: str
    credor: str
    elemento: str
    fornecedor: str | None
    documento: str | None
    tipo_pessoa: str | None
    empenhado: int = 0
    liquidado: int = 0
    pago: int = 0
    empenhos: int = 0
    primeira_data: date | None = None
    maior: int = -1
    historico: str | None = None
    funcao: str | None = None
    rubrica: str | None = None
    recurso: str | None = None


def agregar(linhas: Iterator[dict[str, str]]) -> tuple[dict[tuple[str, str, str], Grupo], dict[str, str]]:
    """Grupos órgão × credor × elemento, e o nome de cada órgão."""
    grupos: dict[tuple[str, str, str], Grupo] = {}
    nomes: dict[str, str] = {}
    for l in linhas:
        orgao = (l.get("cd_orgao") or "").strip()
        if not orgao:
            continue
        nomes.setdefault(orgao, (l.get("nome_orgao") or "").strip())
        documento, tipo, credor = documento_rs(l.get("tp_pessoa"), l.get("cnpj_cpf"))
        if credor.startswith("?:"):
            credor = f"?:{l.get('cd_credor')}"
        elemento = (l.get("cd_elemento") or "").strip()
        chave = (orgao, credor, elemento)
        g = grupos.get(chave)
        if g is None:
            g = grupos[chave] = Grupo(orgao, credor, elemento, limpar_texto(l.get("nm_credor")), documento, tipo)
        operacao = (l.get("tipo_operacao") or "").strip().upper()
        if operacao == "E":
            valor = para_centavos(l.get("vl_empenho"))
            g.empenhado += valor
            g.empenhos += 1
            dia = parse_data(l.get("dt_empenho"))
            if dia and (g.primeira_data is None or dia < g.primeira_data):
                g.primeira_data = dia
            if valor > g.maior:
                g.maior = valor
                g.historico = limpar_texto(l.get("historico"))
                g.funcao = limpar_texto(l.get("ds_funcao"))
                g.rubrica = limpar_texto(l.get("ds_rubrica"))
                g.recurso = limpar_texto(l.get("nm_recurso"))
        elif operacao == "L":
            g.liquidado += para_centavos(l.get("vl_liquidacao"))
        elif operacao == "P":
            g.pago += para_centavos(l.get("vl_pagamento"))
        if g.rubrica is None:  # grupo só com liquidação/pagamento de restos a pagar
            g.rubrica, g.funcao = limpar_texto(l.get("ds_rubrica")), limpar_texto(l.get("ds_funcao"))
            g.historico = g.historico or limpar_texto(l.get("historico"))
            g.recurso = g.recurso or limpar_texto(l.get("nm_recurso"))
    return grupos, nomes


def linha_do_grupo(g: Grupo, ug_id: int, ano: int) -> dict[str, Any]:
    categoria = {"3": "Despesa Corrente", "4": "Despesa de Capital"}.get(g.elemento[:1])
    return {
        "chave": f"RS|{ug_id}|{ano}|{hashlib.sha1(f'{g.credor}|{g.elemento}'.encode()).hexdigest()[:20]}",
        "unidade_gestora_id": ug_id,
        "ano": ano,
        "mes": g.primeira_data.month if g.primeira_data and g.primeira_data.year == ano else None,
        "data_empenho": g.primeira_data,
        "fornecedor": g.fornecedor,
        "fornecedor_normalizado": normalizar_nome(g.fornecedor),
        "cpf_cnpj": g.documento,
        "tipo_pessoa": g.tipo_pessoa,
        "elemento_despesa": g.rubrica,
        "funcao": g.funcao,
        "historico": (g.historico or "")[:2000] or None,
        "historico_normalizado": normalizar_nome((g.historico or "")[:2000]),
        "fonte_recurso": g.recurso,
        "categoria_economica": categoria,
        "qtd_empenhos": max(g.empenhos, 1),
        "valor_empenhado_centavos": g.empenhado,
        "valor_liquidado_centavos": g.liquidado,
        "valor_pago_centavos": g.pago,
    }


def baixar(sessao: requests.Session, url: str, destino: Path) -> Path:
    """Baixa só se o arquivo remoto mudou de tamanho (os anuais têm mais de 1 GB)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    cabecalho = sessao.head(url, timeout=120, allow_redirects=True)
    cabecalho.raise_for_status()
    tamanho = int(cabecalho.headers.get("content-length") or 0)
    if destino.exists() and tamanho and destino.stat().st_size == tamanho:
        logger.info("Reaproveitando %s (mesmo tamanho na fonte)", destino.name)
        return destino
    parcial = destino.with_suffix(destino.suffix + ".part")
    with sessao.get(url, stream=True, timeout=600) as resposta:
        resposta.raise_for_status()
        with parcial.open("wb") as arquivo:
            for bloco in resposta.iter_content(1 << 20):
                arquivo.write(bloco)
    parcial.replace(destino)
    logger.info("Baixado %s (%.0f MB)", destino.name, destino.stat().st_size / 1e6)
    return destino


def linhas_do_zip(caminho: Path) -> Iterator[dict[str, str]]:
    with zipfile.ZipFile(caminho) as zf:
        for info in zf.infolist():
            if info.filename.lower().endswith(".csv"):
                with zf.open(info) as arquivo:
                    yield from csv.DictReader(io.TextIOWrapper(arquivo, encoding="utf-8-sig"))


def municipios_rs(sessao: requests.Session, s: Settings) -> dict[int, str]:
    """Código do município no TCE-RS -> código IBGE."""
    resposta = sessao.get(f"{s.tce_rs_url}/auxiliar/municipios.csv", timeout=120)
    resposta.raise_for_status()
    leitor = csv.DictReader(io.StringIO(resposta.content.decode("utf-8-sig")))
    return {int(l["COD_MUNICIPIO"]): l["CD_MUNICIPIO_IBGE"].strip() for l in leitor if l.get("COD_MUNICIPIO")}


def ibge_do_orgao(codigo: str, nome: str, por_codigo: dict[int, str], mapa: MapaMunicipios) -> str | None:
    """4XXYY com YY 00/01 (prefeitura/câmara) pelo código; os demais pelo nome ("... DE <CIDADE>")."""
    try:
        numero = int(codigo)
    except ValueError:
        return None
    if 40000 <= numero < 100000 and numero % 100 in (0, 1):
        ibge = por_codigo.get((numero - 40000) // 100)
        if ibge:
            return ibge
    norm = normalizar_nome(nome) or ""
    for separador in (" DE ", " DO ", " DA "):
        if separador in norm:
            ibge = mapa.get(("RS", norm.rsplit(separador, 1)[1]))
            if ibge:
                return ibge
    return None


def natureza_rs(codigo: str, nome: str) -> str | None:
    norm = normalizar_nome(nome) or ""
    if norm.startswith("PM "):
        return "Prefeitura Municipal"
    if norm.startswith("CM "):
        return "Câmara Municipal"
    if norm.startswith(("CON", "CIS")):
        return None  # consórcio
    return natureza_do_orgao(nome)


def carregar_ano(db: Session, s: Settings, ano: int, caminho: Path, por_codigo: dict[int, str], resumo: Resumo) -> int:
    grupos, nomes_orgaos = agregar(linhas_do_zip(caminho))
    if not grupos:
        raise ValueError(f"Arquivo do TCE-RS de {ano} veio vazio; nada foi substituído")
    municipios = {c: (n, norm) for c, n, norm in db.execute(
        select(Municipio.codigo_ibge, Municipio.nome, Municipio.nome_normalizado).where(Municipio.sigla_uf == "RS")
    )}
    mapa = MapaMunicipios([(c, "RS", norm) for c, (_, norm) in municipios.items()])
    orgaos = Orgaos(db, fonte=FONTE, uf="RS")
    ug_id: dict[str, int] = {}
    sem_cidade = []
    for codigo, nome in nomes_orgaos.items():
        natureza = natureza_rs(codigo, nome)
        if natureza is None:
            continue
        ibge = ibge_do_orgao(codigo, nome, por_codigo, mapa)
        if ibge is None or ibge not in municipios:
            sem_cidade.append(nome)
            continue
        cidade, norm = municipios[ibge]
        rotulo = {"Prefeitura Municipal": f"Prefeitura Municipal de {cidade}",
                  "Câmara Municipal": f"Câmara Municipal de {cidade}"}.get(natureza, nome)
        ug_id[codigo] = orgaos.obter(ibge, rotulo, natureza, ibge, cidade, norm, codigo_orgao=codigo)
    if sem_cidade:
        logger.info("TCE-RS %d: %d órgãos sem cidade identificada (ficam de fora): %s", ano, len(sem_cidade),
                    ", ".join(sorted(sem_cidade)[:15]))
    linhas = [linha_do_grupo(g, ug_id[g.orgao], ano) for g in grupos.values() if g.orgao in ug_id]
    ids = sorted(set(ug_id.values()))
    existentes = db.scalar(select(func.count()).select_from(DespesaMunicipal).where(
        DespesaMunicipal.unidade_gestora_id.in_(ids), DespesaMunicipal.ano == ano)) or 0
    if not linhas and existentes:
        raise ValueError(f"TCE-RS {ano} sem linhas; mantidos {existentes} registros")
    db.execute(delete(DespesaMunicipal).where(DespesaMunicipal.unidade_gestora_id.in_(ids), DespesaMunicipal.ano == ano))
    for lote in em_lotes(linhas, 5_000):
        db.execute(insert(DespesaMunicipal), list(lote))
    db.commit()
    logger.info("TCE-RS %d: %d linhas (órgão × credor × elemento) em %d órgãos", ano, len(linhas), len(ids))
    return len(linhas)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m civic.tce_rs", description=__doc__.splitlines()[0])
    parser.add_argument("--ano", type=int, nargs="+", help="anos (padrão: ANOS do .env)")
    parser.add_argument("--forcar", action="store_true", help="relê anos com checkpoint")
    parser.add_argument("--sem-progresso", action="store_true")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args(argv)
    s = get_settings()
    logging.basicConfig(level=(args.log_level or s.log_level).upper(),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    init_db()
    hoje = date.today()
    anos = sorted({a for a in (args.ano or s.anos) if ANO_INICIAL_CEAP <= a <= hoje.year})
    resumo = Resumo()
    sessao = criar_sessao()
    inicio = time.monotonic()
    total = 0
    with SessionLocal() as db:
        feitos = set(db.scalars(select(SyncMunicipioAno.ano).where(SyncMunicipioAno.fonte == FONTE)))
        try:
            por_codigo = municipios_rs(sessao, s)
        except Exception as exc:  # noqa: BLE001
            resumo.registrar_falha("TCE-RS municípios", exc)
            por_codigo = {}
        for ano in anos if por_codigo else []:
            if not args.forcar and ano in feitos:
                continue
            try:
                caminho = baixar(sessao, f"{s.tce_rs_url}/municipal/empenhos/{ano}.csv.zip", PASTA / f"{ano}.csv.zip")
                n = carregar_ano(db, s, ano, caminho, por_codigo, resumo)
                total += n
                if ano_fechado(ano, hoje):
                    stmt = sqlite_insert(SyncMunicipioAno).values(fonte=FONTE, municipio="*", ano=ano, registros=n,
                                                                  concluido_em=datetime.now())
                    db.execute(stmt.on_conflict_do_update(
                        index_elements=["fonte", "municipio", "ano"],
                        set_={"registros": stmt.excluded.registros, "concluido_em": stmt.excluded.concluido_em},
                    ))
                    db.commit()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                resumo.registrar_falha(f"TCE-RS {ano}", exc)
        registrar_execucao(db, "tce_rs", total)
    logger.info("TCE-RS concluído em %.1f min; falhas: %d", (time.monotonic() - inicio) / 60, len(resumo.falhas))
    for falha in resumo.falhas:
        logger.info("  - %s", falha)
    return 1 if resumo.falhas else 0


if __name__ == "__main__":
    sys.exit(main())
