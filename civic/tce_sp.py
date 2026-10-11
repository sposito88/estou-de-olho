"""Despesas dos municípios paulistas pelo TCE-SP (transparencia.tce.sp.gov.br).

Uso:
    python -m civic.tce_sp [--municipio Adamantina ...] [--ano 2025 ...] [--forcar] [--sem-progresso]

A API devolve, por município e mês, cada evento de cada empenho (empenhado,
anulação, liquidado, pago). Guardamos uma linha por órgão × credor × ano, com a
soma de cada fase e a quantidade de empenhos: basta para os rankings, para a
ficha do fornecedor e para os sinais de alerta por CNPJ, e cabe no banco para
os 644 municípios. A capital não está aqui: presta contas ao TCM-SP.

Anos fechados ganham checkpoint por município; o ano corrente (e o anterior,
até junho, enquanto as prefeituras ainda corrigem a prestação) é sempre relido.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from civic.alertas import recalcular_se_configurado
from civic.cleaning import limpar_documento, limpar_texto, normalizar_nome, para_centavos, parse_data
from civic.config import ANO_INICIAL_CEAP, Settings, get_settings
from civic.database import SessionLocal, init_db
from civic.models import DespesaMunicipal, Municipio, SyncMunicipioAno, UnidadeGestora
from civic.pernambuco import ClienteJson
from civic.pncp import sessao_paciente
from civic.scraper import Resumo, barra, em_lotes, registrar_execucao
from civic.tse import MapaMunicipios

logger = logging.getLogger("civic.tce_sp")

FONTE = "TCE-SP"
PRIMEIRO_ID = 10_000_000  # ids de órgão do TCE-PE são os do próprio tribunal; os demais começam aqui
MES_LIMITE_ANO_ANTERIOR = 6  # até junho o ano anterior ainda é relido


# --------------------------------------------------------------------------- limpeza (funções puras)


def credor_do_tce_sp(id_fornecedor: str | None) -> tuple[str | None, str | None, str]:
    """'CNPJ - PESSOA JURÍDICA - 22669384000172' -> ('22669384000172', 'PJ', chave do credor).

    Pessoa física e credor internacional vêm só com um código interno do TCE-SP
    (sem CPF): o código entra na chave de agrupamento, mas não vira documento.
    """
    texto = limpar_texto(id_fornecedor) or ""
    codigo = texto.rsplit(" - ", 1)[-1].strip() if " - " in texto else texto
    if texto.upper().startswith("CNPJ"):
        cnpj = limpar_documento(codigo)
        if cnpj and len(cnpj) == 14:
            return cnpj, "PJ", cnpj
    if "FÍSICA" in texto.upper() or "FISICA" in texto.upper():
        return None, "PF", f"PF:{codigo}"
    return None, None, f"OUTRO:{codigo or texto}"


def natureza_do_orgao(nome: str) -> str | None:
    """Classifica o órgão pelo nome; `None` para consórcios (atendem vários municípios)."""
    norm = normalizar_nome(nome) or ""
    if "CONSORCIO" in norm:
        return None
    if norm.startswith("CAMARA"):
        return "Câmara Municipal"
    if norm.startswith("PREFEITURA"):
        return "Prefeitura Municipal"
    if "PREVID" in norm or "APOSENT" in norm:
        return "Previdência"
    return "Administração Indireta"


@dataclass
class _Soma:
    orgao: str
    credor: str
    fornecedor: str | None
    cpf_cnpj: str | None
    tipo_pessoa: str | None
    empenhado: int = 0
    liquidado: int = 0
    pago: int = 0
    empenhos: set[str] = field(default_factory=set)
    primeira_data: date | None = None
    primeiro_empenho: date | None = None


def agregar_eventos(eventos: Iterable[dict[str, Any]]) -> list[_Soma]:
    """Soma os eventos por órgão × credor. Anulação abate o empenhado."""
    somas: dict[tuple[str, str], _Soma] = {}
    desconhecidos: set[str] = set()
    for ev in eventos:
        orgao = limpar_texto(ev.get("orgao"))
        if not orgao:
            continue
        cnpj, tipo, credor = credor_do_tce_sp(ev.get("id_fornecedor"))
        chave = (orgao, credor)
        soma = somas.get(chave)
        if soma is None:
            soma = somas[chave] = _Soma(orgao, credor, limpar_texto(ev.get("nm_fornecedor")), cnpj, tipo)
        valor = para_centavos(ev.get("vl_despesa"))
        evento = normalizar_nome(ev.get("evento")) or ""
        dia = parse_data(ev.get("dt_emissao_despesa"))
        if evento == "EMPENHADO":
            soma.empenhado += valor
            if dia and (soma.primeiro_empenho is None or dia < soma.primeiro_empenho):
                soma.primeiro_empenho = dia
        elif evento.startswith("ANULA"):
            soma.empenhado -= valor
        elif evento == "VALOR LIQUIDADO":
            soma.liquidado += valor
        elif evento == "VALOR PAGO":
            soma.pago += valor
        else:
            desconhecidos.add(evento)
            continue
        if ev.get("nr_empenho"):
            soma.empenhos.add(str(ev["nr_empenho"]))
        if dia and (soma.primeira_data is None or dia < soma.primeira_data):
            soma.primeira_data = dia
    if desconhecidos:
        logger.warning("Eventos do TCE-SP ignorados: %s", sorted(desconhecidos))
    return list(somas.values())


def linha_da_soma(soma: _Soma, ug_id: int, ano: int) -> dict[str, Any]:
    data = soma.primeiro_empenho or soma.primeira_data
    um_so = len(soma.empenhos) == 1
    return {
        "chave": f"SP|{ug_id}|{ano}|{hashlib.sha1(soma.credor.encode()).hexdigest()[:20]}",
        "unidade_gestora_id": ug_id,
        "ano": ano,
        "mes": data.month if data and data.year == ano else None,
        "data_empenho": data,
        "numero_empenho": next(iter(soma.empenhos)) if um_so else None,
        "fornecedor": soma.fornecedor,
        "fornecedor_normalizado": normalizar_nome(soma.fornecedor),
        "cpf_cnpj": soma.cpf_cnpj,
        "tipo_pessoa": soma.tipo_pessoa,
        "qtd_empenhos": max(len(soma.empenhos), 1),
        "valor_empenhado_centavos": soma.empenhado,
        "valor_liquidado_centavos": soma.liquidado,
        "valor_pago_centavos": soma.pago,
    }


def ano_fechado(ano: int, hoje: date) -> bool:
    """O ano já não muda mais na fonte (pode ganhar checkpoint)?"""
    return ano < hoje.year - 1 or (ano == hoje.year - 1 and hoje.month > MES_LIMITE_ANO_ANTERIOR)


# --------------------------------------------------------------------------- coleta


def municipios_alvo(cliente: ClienteJson, s: Settings) -> list[tuple[str, str]]:
    """[(código do TCE-SP, nome por extenso)] conforme TCE_SP_MUNICIPIOS."""
    lista = [(m["municipio"], m["municipio_extenso"]) for m in cliente.get(f"{s.tce_sp_url}/municipios")]
    if any(normalizar_nome(m) == "TODOS" for m in s.tce_sp_municipios):
        return lista
    alvo = {normalizar_nome(m) for m in s.tce_sp_municipios}
    escolhidos = [(c, n) for c, n in lista if normalizar_nome(n) in alvo]
    faltando = alvo - {normalizar_nome(n) for _, n in escolhidos}
    if faltando:
        logger.warning("Municípios fora do TCE-SP: %s", sorted(faltando))
    return escolhidos


class Orgaos:
    """Cadastro dos órgãos do TCE-SP em `unidades_gestoras`, criando ids novos conforme aparecem."""

    def __init__(self, db: Session, fonte: str = FONTE, uf: str = "SP") -> None:
        self.db = db
        self.fonte, self.uf = fonte, uf
        self.por_codigo = {
            ug.codigo_origem: ug.id
            for ug in db.scalars(select(UnidadeGestora).where(UnidadeGestora.fonte == fonte))
        }
        maior = db.scalar(select(func.max(UnidadeGestora.id)).where(UnidadeGestora.id >= PRIMEIRO_ID))
        self.proximo = max(int(maior or 0) + 1, PRIMEIRO_ID)
        self.gravados: set[str] = set()

    def ids_do_municipio(self, codigo_municipio: str) -> list[int]:
        return [i for c, i in self.por_codigo.items() if c.startswith(f"{codigo_municipio}|")]

    def obter(self, codigo_municipio: str, orgao: str, natureza: str, ibge: str, nome: str, nome_norm: str,
              codigo_orgao: str | None = None) -> int:
        codigo = f"{codigo_municipio}|{codigo_orgao or normalizar_nome(orgao)}"
        ug_id = self.por_codigo.get(codigo)
        if ug_id is None:
            ug_id, self.proximo = self.proximo, self.proximo + 1
            self.por_codigo[codigo] = ug_id
        if codigo in self.gravados:
            return ug_id
        self.gravados.add(codigo)
        stmt = sqlite_insert(UnidadeGestora).values(
            id=ug_id, nome=orgao, natureza=natureza, fonte=self.fonte, codigo_origem=codigo,
            codigo_municipio_tce=ibge, municipio=nome, municipio_normalizado=nome_norm, sigla_uf=self.uf,
        )
        self.db.execute(stmt.on_conflict_do_update(
            index_elements=[UnidadeGestora.id],
            set_={c: stmt.excluded[c] for c in ("nome", "natureza", "codigo_municipio_tce", "municipio",
                                                 "municipio_normalizado")},
        ))
        return ug_id


def eventos_do_ano(cliente: ClienteJson, s: Settings, codigo: str, ano: int, hoje: date) -> list[dict[str, Any]]:
    ultimo_mes = hoje.month if ano == hoje.year else 12
    eventos: list[dict[str, Any]] = []
    for mes in range(1, ultimo_mes + 1):
        corpo = cliente.get(f"{s.tce_sp_url}/despesas/{codigo}/{ano}/{mes}")
        if corpo is None:
            continue
        if not isinstance(corpo, list):
            raise ValueError(f"Resposta inesperada do TCE-SP para {codigo}/{ano}/{mes}: {str(corpo)[:200]}")
        eventos.extend(corpo)
    return eventos


def coletar_municipio_ano(
    cliente: ClienteJson,
    db: Session,
    s: Settings,
    orgaos: Orgaos,
    codigo: str,
    ibge: str,
    nome: str,
    nome_norm: str,
    ano: int,
    hoje: date,
) -> int:
    """Baixa o ano inteiro do município e substitui o que havia."""
    somas = agregar_eventos(eventos_do_ano(cliente, s, codigo, ano, hoje))
    linhas = []
    for soma in somas:
        natureza = natureza_do_orgao(soma.orgao)
        if natureza is None:
            continue
        ug = orgaos.obter(codigo, soma.orgao, natureza, ibge, nome, nome_norm)
        linhas.append(linha_da_soma(soma, ug, ano))
    ids = orgaos.ids_do_municipio(codigo)
    if ids and not linhas:
        existentes = db.scalar(select(func.count()).select_from(DespesaMunicipal).where(
            DespesaMunicipal.unidade_gestora_id.in_(ids), DespesaMunicipal.ano == ano)) or 0
        if existentes:
            # API fora do ar responde vazio: não apaga o que já foi coletado.
            raise ValueError(f"TCE-SP devolveu vazio para {nome}/{ano}; mantidos {existentes} registros")
    if ids:
        db.execute(delete(DespesaMunicipal).where(DespesaMunicipal.unidade_gestora_id.in_(ids),
                                                  DespesaMunicipal.ano == ano))
    for lote in em_lotes(linhas, 2_000):
        db.execute(insert(DespesaMunicipal), list(lote))
    if ano_fechado(ano, hoje):
        stmt = sqlite_insert(SyncMunicipioAno).values(
            fonte=FONTE, municipio=codigo, ano=ano, registros=len(linhas), concluido_em=datetime.now()
        )
        db.execute(stmt.on_conflict_do_update(
            index_elements=["fonte", "municipio", "ano"],
            set_={"registros": stmt.excluded.registros, "concluido_em": stmt.excluded.concluido_em},
        ))
    db.commit()
    return len(linhas)


def coletar_tce_sp(
    cliente: ClienteJson,
    db: Session,
    s: Settings,
    anos: list[int],
    resumo: Resumo,
    forcar: bool = False,
    progresso: bool = True,
    hoje: date | None = None,
) -> int:
    hoje = hoje or date.today()
    municipios = municipios_alvo(cliente, s)
    nomes = {
        codigo: (nome, nome_norm)
        for codigo, nome, nome_norm in db.execute(
            select(Municipio.codigo_ibge, Municipio.nome, Municipio.nome_normalizado).where(Municipio.sigla_uf == "SP")
        )
    }
    mapa = MapaMunicipios([(c, "SP", n) for c, (_, n) in nomes.items()])
    feitos = {
        (m, a) for m, a in db.execute(
            select(SyncMunicipioAno.municipio, SyncMunicipioAno.ano).where(SyncMunicipioAno.fonte == FONTE)
        )
    }
    orgaos = Orgaos(db)
    total = 0
    for codigo, extenso in barra(municipios, progresso, desc="TCE-SP", unit="mun"):
        ibge = mapa.get(("SP", normalizar_nome(extenso) or ""))
        if ibge is None:
            resumo.registrar_falha(f"TCE-SP {extenso}", ValueError("município sem código IBGE"))
            continue
        nome, nome_norm = nomes[ibge]
        for ano in anos:
            if not forcar and (codigo, ano) in feitos:
                continue
            try:
                n = coletar_municipio_ano(cliente, db, s, orgaos, codigo, ibge, nome, nome_norm, ano, hoje)
                total += n
                logger.info("TCE-SP %s/%d: %d linhas (órgão × credor)", nome, ano, n)
            except Exception as exc:  # noqa: BLE001 - um município com erro não pode parar a carga
                db.rollback()
                orgaos = Orgaos(db)  # descarta ids alocados na transação desfeita
                resumo.registrar_falha(f"TCE-SP {nome}/{ano}", exc)
    registrar_execucao(db, "tce_sp", total)
    return total


# --------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m civic.tce_sp", description=__doc__.splitlines()[0])
    parser.add_argument("--municipio", nargs="+", help="nomes dos municípios (padrão: TCE_SP_MUNICIPIOS)")
    parser.add_argument("--ano", type=int, nargs="+", help="anos (padrão: ANOS do .env)")
    parser.add_argument("--forcar", action="store_true", help="relê anos com checkpoint")
    parser.add_argument("--sem-alertas", action="store_true", help="não recalcula os alertas ao final")
    parser.add_argument("--sem-progresso", action="store_true")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args(argv)

    s = get_settings()
    if args.municipio:
        s = s.model_copy(update={"tce_sp_municipios": args.municipio})
    logging.basicConfig(
        level=(args.log_level or s.log_level).upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    anos = sorted({a for a in (args.ano or s.anos) if ANO_INICIAL_CEAP <= a <= date.today().year})
    init_db()
    resumo = Resumo()
    db = SessionLocal()
    inicio = time.monotonic()
    try:
        cliente = ClienteJson(s.tce_sp_req_per_sec, max(s.timeout, 300), sessao_paciente())
        coletar_tce_sp(cliente, db, s, anos, resumo, args.forcar,
                       progresso=not args.sem_progresso and sys.stderr.isatty())
        if not args.sem_alertas:
            try:
                logger.info("Alertas recalculados: %s", recalcular_se_configurado(db, s))
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                resumo.registrar_falha("alertas", exc)
    finally:
        db.close()
    logger.info("TCE-SP concluído em %.1f min; falhas: %d", (time.monotonic() - inicio) / 60, len(resumo.falhas))
    for falha in resumo.falhas[:30]:
        logger.info("  - %s", falha)
    return 1 if resumo.falhas else 0


if __name__ == "__main__":
    sys.exit(main())
