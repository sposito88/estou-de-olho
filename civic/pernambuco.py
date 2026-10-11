"""Coleta de Pernambuco: verba indenizatória dos deputados estaduais (ALEPE) e
contas municipais (prefeitura, câmara e autarquias) do TCE-PE.

Uso:
    python -m civic.pernambuco [--ano 2025 ...] [--so-alepe | --so-tce] [--forcar] [--sem-progresso]

ALEPE: usa os mesmos endpoints JSON públicos que o portal transparencia.alepe.pe.gov.br
(lista de deputados -> meses -> documentos -> notas), a no máximo ALEPE_REQ_PER_SEC.
Meses antigos com checkpoint são pulados; os 3 meses mais recentes são sempre relidos.

TCE-PE: para cada município de TCE_MUNICIPIOS ("todos" = os 184 de PE), baixa os
empenhos do ano (uma chamada; órgão por órgão se passar do limite da API), os
pagamentos de cada órgão (com a data em que o dinheiro saiu), os contratos (LICON,
com link do PDF) e, uma vez por semana, a lista de vínculos de pessoal. Anos
fechados já baixados são pulados (o anterior é relido até junho).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

import requests
from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from civic.alertas import recalcular_se_configurado
from civic.cleaning import (
    contrato_do_tce,
    despesa_municipal_do_tce,
    normalizar_nome,
    pagamento_do_tce,
    para_inteiro,
    servidor_do_tce,
    verba_da_alepe,
)
from civic.config import ANO_INICIAL_CEAP, Settings, get_settings
from civic.database import SessionLocal, init_db
from civic.models import (
    ContratoMunicipal,
    DeputadoEstadual,
    DespesaMunicipal,
    PagamentoMunicipal,
    Municipio,
    ServidorMunicipal,
    SyncCheckpointEstadual,
    SyncMunicipioAno,
    UnidadeGestora,
    VerbaIndenizatoria,
)
from civic.scraper import RateLimiter, Resumo, barra, criar_sessao, em_lotes, registrar_execucao

logger = logging.getLogger("civic.pernambuco")

MESES_SEMPRE_RELIDOS = 3
FONTE_TCE = "TCE-PE"
FONTE_PESSOAL = "TCE-PE-PESSOAL"
DIAS_PESSOAL = 7  # a lista de pessoal muda pouco: relê uma vez por semana
NATUREZAS_EXCLUIDAS = {"Consórcio"}  # atende vários municípios; distorceria a conta da cidade


class ClienteJson:
    """GET de JSON com rate limit. `latin1=True` para o TCE-PE, que não manda UTF-8."""

    def __init__(self, req_por_segundo: float, timeout: float, sessao: requests.Session | None = None) -> None:
        self.sessao = sessao or criar_sessao()
        self.limiter = RateLimiter(req_por_segundo)
        self.timeout = timeout

    def get(self, url: str, params: dict[str, Any] | None = None, *, latin1: bool = False) -> Any:
        self.limiter.aguardar()
        resposta = self.sessao.get(url, params=params, timeout=self.timeout)
        resposta.raise_for_status()
        if resposta.status_code == 204 or not resposta.content:
            return None
        return json.loads(resposta.content.decode("latin1" if latin1 else "utf-8"))


def conteudo_tce(cliente: ClienteJson, url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Lista `resposta.conteudo` do TCE-PE; falha se o status não for OK ou se bater no limite."""
    corpo = cliente.get(url, params, latin1=True)["resposta"]
    if corpo.get("status") != "OK":
        raise ValueError(f"TCE-PE respondeu {corpo.get('status')} para {url} {params}")
    itens = corpo.get("conteudo") or []
    if corpo.get("limiteResultado") and len(itens) >= int(corpo["limiteResultado"]):
        logger.warning("Resultado truncado no limite do TCE-PE (%s linhas): %s %s", len(itens), url, params)
    return itens


# --------------------------------------------------------------------------- ALEPE


def sincronizar_deputados_estaduais(cliente: ClienteJson, db: Session, s: Settings) -> int:
    """Cadastro de deputados (todas as legislaturas listadas) e quem está em exercício."""
    lista = cliente.get(f"{s.alepe_url}/dep/deputados.php", {"leg": -16})
    try:
        em_exercicio = {
            normalizar_nome(p.get("nomeParlamentar"))
            for p in cliente.get(f"{s.alepe_dados_abertos_url}/parlamentares/")
        }
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Lista de deputados em exercício indisponível (%s)", exc)
        em_exercicio = set()
    agora = datetime.now()
    linhas = []
    for d in lista:
        nome = (d.get("nome") or "").strip()
        foto = (d.get("foto") or "").strip()
        linhas.append(
            {
                "id": int(d["id"]),
                "nome": nome,
                "nome_normalizado": normalizar_nome(nome) or "",
                "sigla_partido": (d.get("partido") or "").strip() or None,
                "email": (d.get("email") or "").strip() or None,
                "url_foto": f"{s.alepe_site_url}{foto}" if foto.startswith("/") else (foto or None),
                "em_exercicio": normalizar_nome(nome) in em_exercicio,
                "atualizado_em": agora,
            }
        )
    if linhas:
        stmt = sqlite_insert(DeputadoEstadual).values(linhas)
        stmt = stmt.on_conflict_do_update(
            index_elements=[DeputadoEstadual.id], set_={c: stmt.excluded[c] for c in linhas[0] if c != "id"}
        )
        db.execute(stmt)
    db.commit()
    logger.info(
        "%d deputados estaduais (%d em exercício)", len(linhas), sum(1 for l in linhas if l["em_exercicio"])
    )
    return len(linhas)


def recente(ano: int, mes: int, hoje: date) -> bool:
    """O mês está entre os mais recentes (que a ALEPE ainda pode completar)?"""
    return (hoje.year * 12 + hoje.month) - (ano * 12 + mes) < MESES_SEMPRE_RELIDOS


def coletar_verbas(
    cliente: ClienteJson,
    db: Session,
    anos: list[int],
    s: Settings,
    resumo: Resumo,
    forcar: bool = False,
    progresso: bool = True,
) -> int:
    """Baixa as notas da verba indenizatória por deputado e mês e substitui o mês inteiro.

    Checkpoint por (deputado, ano, mês); `mes = 0` marca um ano fechado já
    verificado, para não perguntar de novo por deputados sem gasto naquele ano.
    """
    hoje = date.today()
    deputados = list(db.scalars(select(DeputadoEstadual.id).order_by(DeputadoEstadual.id)))
    concluidos = {
        tuple(r)
        for r in db.execute(
            select(SyncCheckpointEstadual.deputado_estadual_id, SyncCheckpointEstadual.ano, SyncCheckpointEstadual.mes)
        )
    }
    rubricas: dict[int, dict[int, str]] = {}
    notas_gravadas = 0

    def marcar(dep: int, ano: int, mes: int) -> None:
        stmt = sqlite_insert(SyncCheckpointEstadual).values(
            deputado_estadual_id=dep, ano=ano, mes=mes, concluido_em=datetime.now()
        )
        db.execute(stmt.on_conflict_do_update(
            index_elements=["deputado_estadual_id", "ano", "mes"], set_={"concluido_em": stmt.excluded.concluido_em}
        ))

    for dep in barra(deputados, progresso, desc="Verba ALEPE", unit="dep"):
        for ano in anos:
            ano_fechado = ano < hoje.year
            if ano_fechado and not forcar and (dep, ano, 0) in concluidos:
                continue
            try:
                if ano not in rubricas:
                    rubricas[ano] = {
                        int(r["numero_categoria"]): r["nome_categoria"].strip()
                        for r in cliente.get(f"{s.alepe_url}/adm/verbaindenizatoria-rubricas.php", {"ano": ano})
                    }
                meses = [int(m["mes"]) for m in cliente.get(
                    f"{s.alepe_url}/adm/verbaindenizatoria-dep-meses.php", {"dep": dep, "ano": ano}
                )]
                for mes in meses:
                    if not forcar and (dep, ano, mes) in concluidos and not recente(ano, mes, hoje):
                        continue
                    linhas: list[dict[str, Any]] = []
                    for doc in cliente.get(
                        f"{s.alepe_url}/adm/verbaindenizatoria.php", {"dep": dep, "ano": ano, "mes": mes}
                    ):
                        notas = cliente.get(f"{s.alepe_url}/adm/verbaindenizatorianotas.php", {"docid": doc["docid"]})
                        for nota in notas:
                            try:
                                linhas.append(verba_da_alepe(nota, doc["docid"], dep, ano, mes, rubricas[ano]))
                            except (KeyError, TypeError, ValueError) as exc:
                                logger.warning("Nota ignorada (dep %s %s/%s): %s", dep, mes, ano, exc)
                    db.execute(
                        delete(VerbaIndenizatoria).where(
                            VerbaIndenizatoria.deputado_estadual_id == dep,
                            VerbaIndenizatoria.ano == ano,
                            VerbaIndenizatoria.mes == mes,
                        )
                    )
                    if linhas:
                        db.execute(insert(VerbaIndenizatoria), linhas)
                    marcar(dep, ano, mes)
                    db.commit()
                    notas_gravadas += len(linhas)
                if ano_fechado:
                    marcar(dep, ano, 0)
                    db.commit()
            except Exception as exc:  # noqa: BLE001 - uma falha não pode abortar a coleta
                db.rollback()
                resumo.registrar_falha(f"ALEPE deputado {dep} / {ano}", exc)
    logger.info("Verba indenizatória: %d notas gravadas nesta execução", notas_gravadas)
    registrar_execucao(db, "alepe", notas_gravadas)
    return notas_gravadas


# --------------------------------------------------------------------------- TCE-PE


def sincronizar_unidades(cliente: ClienteJson, db: Session, s: Settings) -> dict[str, dict[str, Any]]:
    """Órgãos municipais dos municípios configurados (TCE_MUNICIPIOS, ou "todos").

    O nome do município vem do TCE-PE e é casado com o do IBGE (grafias diferem às vezes),
    para que as páginas da cidade encontrem os órgãos. Retorna
    {código TCE do município: {"ids": [...], "nome_tce": "...", "nome": "..."}}.
    """
    from civic.tse import MapaMunicipios

    todos = any(normalizar_nome(m) == "TODOS" for m in s.tce_municipios)
    alvo = {normalizar_nome(m) for m in s.tce_municipios}
    ibge = {codigo: nome for codigo, nome in db.execute(
        select(Municipio.codigo_ibge, Municipio.nome_normalizado).where(Municipio.sigla_uf == "PE")
    )}
    mapa = MapaMunicipios([(c, "PE", n) for c, n in ibge.items()])
    unidades = conteudo_tce(cliente, f"{s.tce_url}/UnidadesJurisdicionadas!json", {})
    linhas, nomes_tce = [], {}
    sem_ibge: set[str] = set()
    for u in unidades:
        municipio = (u.get("MUNICIPIO") or "").strip()
        if (
            (u.get("ESFERA") or "").strip() != "Municipal"
            or (not todos and normalizar_nome(municipio) not in alvo)
            or (u.get("NATUREZA") or "").strip() in NATUREZAS_EXCLUIDAS
        ):
            continue
        codigo_ibge = mapa.get(("PE", normalizar_nome(municipio) or ""))
        if codigo_ibge is None:
            sem_ibge.add(municipio)
        codigo = u["CODIGOMUNICIPIO"].strip()
        nomes_tce[codigo] = municipio
        linhas.append(
            {
                "id": int(u["ID_UNIDADE_GESTORA"]),
                "nome": u["ORGAO"].strip(),
                "natureza": (u.get("NATUREZA") or "").strip() or None,
                "fonte": "TCE-PE",
                "codigo_origem": str(int(u["ID_UNIDADE_GESTORA"])),
                "codigo_municipio_tce": codigo,
                "municipio": municipio,
                "municipio_normalizado": ibge.get(codigo_ibge or "", normalizar_nome(municipio) or ""),
                "sigla_uf": "PE",
            }
        )
    for lote in em_lotes(linhas, 500):
        stmt = sqlite_insert(UnidadeGestora).values(list(lote))
        stmt = stmt.on_conflict_do_update(
            index_elements=[UnidadeGestora.id], set_={c: stmt.excluded[c] for c in linhas[0] if c != "id"}
        )
        db.execute(stmt)
    db.commit()
    por_municipio: dict[str, dict[str, Any]] = {}
    for l in linhas:
        item = por_municipio.setdefault(l["codigo_municipio_tce"], {"ids": [], "nome_tce": nomes_tce[l["codigo_municipio_tce"]],
                                                                    "nome": l["municipio"]})
        item["ids"].append(l["id"])
    if sem_ibge:
        logger.warning("Municípios do TCE-PE sem par no IBGE (ficam sem página da cidade): %s", sorted(sem_ibge))
    if not todos:
        faltando = alvo - {normalizar_nome(l["municipio"]) for l in linhas}
        if faltando:
            logger.warning("Municípios sem órgão no TCE-PE: %s", sorted(faltando))
    logger.info("%d órgãos municipais em %d município(s)", len(linhas), len(por_municipio))
    return por_municipio


def ano_fechado(ano: int, hoje: date) -> bool:
    """O ano já não muda mais no tribunal? (o anterior ainda recebe correções até junho)"""
    return ano < hoje.year - 1 or (ano == hoje.year - 1 and hoje.month > 6)


def _substituir(db: Session, modelo: Any, ids: list[int], ano: int | None, linhas: list[dict[str, Any]]) -> None:
    filtro = [modelo.unidade_gestora_id.in_(ids)]
    if ano is not None:
        filtro.append(modelo.ano == ano)
    db.execute(delete(modelo).where(*filtro))
    for lote in em_lotes(linhas, 2_000):
        db.execute(insert(modelo), list(lote))


def _despesas(cliente: ClienteJson, s: Settings, codigo: str, ids: list[int], ano: int) -> list[dict[str, Any]]:
    """Empenhos do município no ano; se a resposta bater no limite da API, pede órgão por órgão."""
    corpo = cliente.get(f"{s.tce_url}/DespesasMunicipais!json", {"CODIGO_MUNICIPIO": codigo, "ANOREFERENCIA": ano},
                        latin1=True)["resposta"]
    itens = corpo.get("conteudo") or []
    if corpo.get("status") != "OK":
        raise ValueError(f"TCE-PE respondeu {corpo.get('status')} para despesas {codigo}/{ano}")
    if corpo.get("limiteResultado") and len(itens) >= int(corpo["limiteResultado"]):
        logger.info("TCE-PE %s/%d passou do limite: consultando órgão por órgão", codigo, ano)
        itens = []
        for ug in ids:
            itens += conteudo_tce(cliente, f"{s.tce_url}/DespesasMunicipais!json",
                                  {"ID_UNIDADE_GESTORA": ug, "ANOREFERENCIA": ano})
    linhas = [despesa_municipal_do_tce(i) for i in itens if int(i["ID_UNIDADE_GESTORA"]) in ids]
    return list({l["chave"]: l for l in linhas}.values())


def _contratos(cliente: ClienteJson, s: Settings, nome_tce: str, ids: list[int], ano: int) -> list[dict[str, Any]]:
    """Contratos (LICON) do município no ano. O filtro por nome precisa ir em latin1, como a API."""
    url = f"{s.tce_url}/Contratos!json?Municipio={quote(nome_tce, encoding='latin1')}&AnoContrato={ano}"
    itens = conteudo_tce(cliente, url, {})
    linhas = [contrato_do_tce(i, int(i["CodigoUG"])) for i in itens if para_inteiro(i.get("CodigoUG")) in ids]
    return list({(l["unidade_gestora_id"], l["codigo"]): l for l in linhas}.values())


def coletar_tce(
    cliente: ClienteJson,
    db: Session,
    anos: list[int],
    s: Settings,
    resumo: Resumo,
    forcar: bool = False,
    hoje: date | None = None,
) -> int:
    """Por município: empenhos, pagamentos e contratos de cada ano (substitui o ano inteiro) e o
    pessoal de cada órgão. Anos fechados já baixados são pulados; o pessoal é relido a cada 7 dias."""
    hoje = hoje or date.today()
    por_municipio = sincronizar_unidades(cliente, db, s)
    feitos = {(m, a) for m, a in db.execute(
        select(SyncMunicipioAno.municipio, SyncMunicipioAno.ano).where(SyncMunicipioAno.fonte == FONTE_TCE)
    )}
    pessoal_recente = {m for m, quando in db.execute(
        select(SyncMunicipioAno.municipio, SyncMunicipioAno.concluido_em).where(SyncMunicipioAno.fonte == FONTE_PESSOAL)
    ) if quando and (datetime.now() - quando).days < DIAS_PESSOAL}
    total = 0

    def marcar(fonte: str, codigo: str, ano: int, registros: int) -> None:
        stmt = sqlite_insert(SyncMunicipioAno).values(fonte=fonte, municipio=codigo, ano=ano, registros=registros,
                                                      concluido_em=datetime.now())
        db.execute(stmt.on_conflict_do_update(
            index_elements=["fonte", "municipio", "ano"],
            set_={"registros": stmt.excluded.registros, "concluido_em": stmt.excluded.concluido_em},
        ))

    for codigo, info in por_municipio.items():
        ids, nome = info["ids"], info["nome"]
        for ano in anos:
            if not forcar and (codigo, ano) in feitos and ano_fechado(ano, hoje):
                continue
            try:
                despesas = _despesas(cliente, s, codigo, ids, ano)
                pagamentos = []
                for ug in ids:
                    itens = conteudo_tce(cliente, f"{s.tce_url}/EmpenhoPagamento!json",
                                         {"ID_UNIDADE_GESTORA": ug, "ANOREFERENCIA": ano})
                    pagamentos += [pagamento_do_tce(i) for i in itens if int(i["ID_UNIDADE_GESTORA"]) == ug]
                contratos = _contratos(cliente, s, info["nome_tce"], ids, ano)
                _substituir(db, DespesaMunicipal, ids, ano, despesas)
                _substituir(db, PagamentoMunicipal, ids, ano, pagamentos)
                _substituir(db, ContratoMunicipal, ids, ano, contratos)
                if ano_fechado(ano, hoje):
                    marcar(FONTE_TCE, codigo, ano, len(despesas))
                db.commit()
                total += len(despesas)
                logger.info("TCE-PE %s/%d: %d empenhos, %d pagamentos, %d contratos",
                            nome, ano, len(despesas), len(pagamentos), len(contratos))
            except Exception as exc:  # noqa: BLE001 - um município com erro não para a carga
                db.rollback()
                resumo.registrar_falha(f"TCE-PE {nome}/{ano}", exc)
        if not forcar and codigo in pessoal_recente:
            continue
        try:
            vinculos = []
            for ug in ids:
                itens = conteudo_tce(cliente, f"{s.tce_url}/ListaServidores!json", {"UnidadeJurisdicionadaTCE": ug})
                vinculos += [servidor_do_tce(i) for i in itens if int(i["UnidadeJurisdicionadaTCE"]) == ug]
            _substituir(db, ServidorMunicipal, ids, None, vinculos)
            marcar(FONTE_PESSOAL, codigo, 0, len(vinculos))
            db.commit()
            logger.info("TCE-PE %s: %d vínculos de pessoal", nome, len(vinculos))
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            resumo.registrar_falha(f"TCE-PE pessoal {nome}", exc)
    registrar_execucao(db, "tce", total)
    return total


# --------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m civic.pernambuco", description=__doc__.splitlines()[0])
    parser.add_argument("--ano", type=int, nargs="+", help="anos (padrão: ANOS do .env)")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--so-alepe", action="store_true", help="só a verba dos deputados estaduais")
    grupo.add_argument("--so-tce", action="store_true", help="só as contas municipais do TCE-PE")
    parser.add_argument("--forcar", action="store_true", help="ignora checkpoints")
    parser.add_argument("--sem-progresso", action="store_true")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args(argv)

    s = get_settings()
    logging.basicConfig(
        level=(args.log_level or s.log_level).upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    anos = sorted({a for a in (args.ano or s.anos) if ANO_INICIAL_CEAP <= a <= date.today().year})
    progresso = not args.sem_progresso and sys.stderr.isatty()
    init_db()
    resumo = Resumo()
    db = SessionLocal()
    inicio = time.monotonic()
    try:
        if not args.so_tce:
            alepe = ClienteJson(s.alepe_req_per_sec, s.timeout)
            try:
                sincronizar_deputados_estaduais(alepe, db, s)
                coletar_verbas(alepe, db, anos, s, resumo, args.forcar, progresso)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                resumo.registrar_falha("ALEPE", exc)
        if not args.so_alepe:
            tce = ClienteJson(s.req_per_sec, max(s.timeout, 300))
            try:
                coletar_tce(tce, db, anos, s, resumo, args.forcar)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                resumo.registrar_falha("TCE-PE", exc)
        try:
            logger.info("Alertas recalculados: %s", recalcular_se_configurado(db, s))
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            resumo.registrar_falha("alertas", exc)
    finally:
        db.close()
    logger.info("Pernambuco concluído em %.1f min; falhas: %d", (time.monotonic() - inicio) / 60, len(resumo.falhas))
    for falha in resumo.falhas:
        logger.info("  - %s", falha)
    return 1 if resumo.falhas else 0


if __name__ == "__main__":
    sys.exit(main())
