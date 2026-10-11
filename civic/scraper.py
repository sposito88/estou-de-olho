"""Coleta de deputados, despesas da cota parlamentar (CEAP) e emendas parlamentares.

Uso:
    python -m civic.scraper [--ano 2025 ...] [--bulk] [--so-deputados] [--forcar]
                            [--sem-emendas | --so-emendas] [--sem-progresso]

Fontes:
    - API de Dados Abertos da Câmara: deputados e despesas (modo padrão).
    - CSV anual da Câmara (`--bulk`): mesmas despesas, num download por ano.
    - Download em lote do Portal da Transparência: emendas e pagamentos por favorecido.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import zipfile
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, TypeVar

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import and_, delete, func, insert, or_, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
from urllib3.util import Retry

from civic import __version__
from civic.alertas import recalcular_se_configurado
from civic.avisos import notificar_telegram
from civic.cleaning import (
    convenio_do_csv,
    despesa_da_api,
    despesa_do_csv,
    emenda_do_csv,
    normalizar_nome,
    pagamento_emenda_do_csv,
)
from civic.config import ANO_INICIAL_CEAP, DATA_DIR, Settings, get_settings
from civic.database import SessionLocal, init_db
from civic.ibge import atualizar_municipios
from civic.models import (
    Deputado,
    Despesa,
    Emenda,
    EmendaConvenio,
    EmendaPagamento,
    Municipio,
    SyncCheckpoint,
    SyncExecucao,
)

logger = logging.getLogger("civic.scraper")

T = TypeVar("T")

TAMANHO_LOTE = 500
LINHAS_POR_BLOCO_CSV = 50_000
DOWNLOAD_DIR = DATA_DIR / "downloads"
VALIDADE_DOWNLOAD_EMENDAS_S = 24 * 3600

COLUNAS_CSV_CAMARA = [
    "ideCadastro", "codLegislatura", "txtDescricao", "txtFornecedor", "txtCNPJCPF",
    "txtNumero", "indTipoDocumento", "datEmissao", "vlrDocumento", "vlrGlosa",
    "vlrLiquido", "numMes", "numAno", "numParcela", "ideDocumento", "urlDocumento",
]
COLUNAS_ATUALIZAVEIS_DESPESA = [
    c.name for c in Despesa.__table__.columns if c.name not in ("id", "hash_unico")
]


# --------------------------------------------------------------------------- utilidades


@dataclass
class ContagemUpsert:
    inseridas: int = 0
    atualizadas: int = 0


@dataclass
class Resumo:
    """Totais acumulados de uma execução, impressos ao final."""

    deputados: int = 0
    pares_processados: int = 0
    pares_pulados: int = 0
    despesas_inseridas: int = 0
    despesas_atualizadas: int = 0
    despesas_removidas: int = 0
    emendas: int = 0
    pagamentos_emendas: int = 0
    falhas: list[str] = field(default_factory=list)
    inicio: float = field(default_factory=time.monotonic)

    def somar(self, contagem: ContagemUpsert, removidas: int) -> None:
        self.pares_processados += 1
        self.despesas_inseridas += contagem.inseridas
        self.despesas_atualizadas += contagem.atualizadas
        self.despesas_removidas += removidas

    def registrar_falha(self, contexto: str, exc: BaseException) -> None:
        mensagem = f"{contexto}: {type(exc).__name__}: {exc}"
        self.falhas.append(mensagem)
        logger.error("Falha em %s", mensagem)

    def log(self) -> None:
        duracao = time.monotonic() - self.inicio
        minutos, segundos = divmod(int(duracao), 60)
        logger.info("=" * 60)
        logger.info("Resumo da coleta")
        logger.info("  Deputados sincronizados ......... %d", self.deputados)
        logger.info("  Pares deputado/ano processados .. %d", self.pares_processados)
        logger.info("  Pares pulados (checkpoint) ...... %d", self.pares_pulados)
        logger.info("  Despesas inseridas .............. %d", self.despesas_inseridas)
        logger.info("  Despesas atualizadas ............ %d", self.despesas_atualizadas)
        logger.info("  Despesas removidas na origem .... %d", self.despesas_removidas)
        logger.info("  Emendas carregadas .............. %d", self.emendas)
        logger.info("  Pagamentos de emendas ........... %d", self.pagamentos_emendas)
        logger.info("  Falhas .......................... %d", len(self.falhas))
        for falha in self.falhas:
            logger.info("    - %s", falha)
        logger.info("  Tempo total ..................... %dmin %02ds", minutos, segundos)
        logger.info("=" * 60)


def em_lotes(itens: Sequence[T], tamanho: int = TAMANHO_LOTE) -> Iterator[Sequence[T]]:
    for i in range(0, len(itens), tamanho):
        yield itens[i : i + tamanho]


def barra(iteravel: Iterable[T], ativo: bool, **kwargs: Any) -> Iterable[T]:
    """Barra de progresso opcional (tqdm)."""
    return tqdm(iteravel, disable=not ativo, dynamic_ncols=True, **kwargs)


def registrar_execucao(db: Session, fonte: str, registros: int, detalhes: str | None = None) -> None:
    db.add(
        SyncExecucao(
            fonte=fonte, concluido_em=datetime.now(), registros=registros, detalhes=detalhes
        )
    )
    db.commit()


# --------------------------------------------------------------------------- HTTP


class RateLimiter:
    """Garante um intervalo mínimo entre requisições (single-thread)."""

    def __init__(self, req_por_segundo: float) -> None:
        self.intervalo = 1.0 / req_por_segundo
        self._ultima = 0.0

    def aguardar(self) -> None:
        espera = self._ultima + self.intervalo - time.monotonic()
        if espera > 0:
            time.sleep(espera)
        self._ultima = time.monotonic()


def criar_sessao() -> requests.Session:
    """Sessão HTTP com retry exponencial para 429/5xx, respeitando `Retry-After`."""
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        respect_retry_after_header=True,
        allowed_methods=frozenset({"GET", "HEAD"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    sessao = requests.Session()
    sessao.mount("https://", adapter)
    sessao.mount("http://", adapter)
    sessao.headers.update(
        {"Accept": "application/json", "User-Agent": f"estou-de-olho/{__version__}"}
    )
    return sessao


class CamaraClient:
    """Cliente da API de Dados Abertos da Câmara com rate limit e paginação."""

    def __init__(self, settings: Settings, sessao: requests.Session | None = None) -> None:
        self.base_url = settings.api_base_url
        self.timeout = settings.timeout
        self.itens = settings.itens_por_pagina
        self.sessao = sessao or criar_sessao()
        self.limiter = RateLimiter(settings.req_per_sec)

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not url.startswith("http"):
            url = f"{self.base_url}{url}"
        self.limiter.aguardar()
        resposta = self.sessao.get(url, params=params, timeout=self.timeout)
        resposta.raise_for_status()
        return resposta.json()

    def paginar(self, caminho: str, params: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        """Itera os itens de `dados` de todas as páginas.

        Pede `itens` por página e segue o link `rel="next"` da resposta até ele
        sumir. O href de `next` já carrega todos os parâmetros, então só a
        primeira requisição envia `params`. Um link repetido encerra o laço.
        """
        url: str | None = caminho
        parametros: dict[str, Any] | None = {**(params or {}), "itens": self.itens}
        visitados: set[str] = set()
        while url:
            corpo = self.get_json(url, parametros)
            yield from corpo.get("dados") or []
            proximo = next(
                (link["href"] for link in corpo.get("links", []) if link.get("rel") == "next"),
                None,
            )
            if proximo is None or proximo in visitados:
                break
            visitados.add(proximo)
            url, parametros = proximo, None


def baixar_arquivo(
    sessao: requests.Session, url: str, destino: Path, timeout: float, reaproveitar: bool
) -> Path:
    """Baixa `url` em streaming para `destino` (via arquivo .part, renomeado no fim)."""
    if reaproveitar and destino.exists():
        logger.info("Reaproveitando download existente: %s", destino.name)
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(destino.suffix + ".part")
    logger.info("Baixando %s", url)
    with sessao.get(url, stream=True, timeout=timeout, headers={"Accept": "*/*"}) as resposta:
        resposta.raise_for_status()
        with temporario.open("wb") as arquivo:
            for bloco in resposta.iter_content(chunk_size=1 << 20):
                arquivo.write(bloco)
    temporario.replace(destino)
    logger.info("Download concluído: %s (%.1f MB)", destino.name, destino.stat().st_size / 1e6)
    return destino


# --------------------------------------------------------------------------- persistência


def upsert_deputados(db: Session, linhas: list[dict[str, Any]]) -> None:
    """Insere ou atualiza deputados pela chave primária (id da Câmara)."""
    if not linhas:
        return
    stmt = sqlite_insert(Deputado).values(linhas)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Deputado.id],
        set_={c: stmt.excluded[c] for c in linhas[0] if c != "id"},
    )
    db.execute(stmt)


def upsert_despesas(db: Session, registros: list[dict[str, Any]]) -> ContagemUpsert:
    """Grava despesas de forma idempotente, em lotes.

    Usa `INSERT ... ON CONFLICT(hash_unico) DO UPDATE`. Repetições do mesmo hash
    dentro da entrada são colapsadas (a última vence). Para separar inseridas de
    atualizadas, conta antes de cada lote quantos hashes já existiam. Não faz commit.
    """
    unicos = list({r["hash_unico"]: r for r in registros}.values())
    contagem = ContagemUpsert()
    for lote in em_lotes(unicos):
        hashes = [r["hash_unico"] for r in lote]
        existentes = db.scalar(
            select(func.count()).select_from(Despesa).where(Despesa.hash_unico.in_(hashes))
        ) or 0
        stmt = sqlite_insert(Despesa).values(list(lote))
        stmt = stmt.on_conflict_do_update(
            index_elements=[Despesa.hash_unico],
            set_={c: stmt.excluded[c] for c in COLUNAS_ATUALIZAVEIS_DESPESA},
        )
        db.execute(stmt)
        contagem.atualizadas += existentes
        contagem.inseridas += len(lote) - existentes
    return contagem


def remover_obsoletas(db: Session, deputado_id: int, ano: int, hashes_vistos: set[str]) -> int:
    """Apaga despesas de (deputado, ano) que não vieram na coleta completa mais recente.

    Necessário porque uma correção de valor na origem gera um hash novo; sem
    isso, a versão antiga continuaria somando. Se a coleta não trouxe nada, nada
    é apagado (proteção contra respostas vazias intermitentes da API).
    """
    if not hashes_vistos:
        return 0
    resultado = db.execute(
        delete(Despesa).where(
            Despesa.deputado_id == deputado_id,
            Despesa.ano == ano,
            Despesa.hash_unico.not_in(hashes_vistos),
        )
    )
    return resultado.rowcount or 0


def marcar_checkpoint(db: Session, deputado_id: int, ano: int, fonte: str) -> None:
    stmt = sqlite_insert(SyncCheckpoint).values(
        deputado_id=deputado_id, ano=ano, concluido_em=datetime.now(), fonte=fonte
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[SyncCheckpoint.deputado_id, SyncCheckpoint.ano],
        set_={"concluido_em": stmt.excluded.concluido_em, "fonte": stmt.excluded.fonte},
    )
    db.execute(stmt)


def gravar_par(
    db: Session, deputado_id: int, ano: int, registros: list[dict[str, Any]], fonte: str
) -> tuple[ContagemUpsert, int]:
    """Upsert + limpeza de obsoletas + checkpoint de um (deputado, ano), com commit."""
    registros = [r for r in registros if r["ano"] == ano]
    contagem = upsert_despesas(db, registros)
    removidas = remover_obsoletas(db, deputado_id, ano, {r["hash_unico"] for r in registros})
    marcar_checkpoint(db, deputado_id, ano, fonte)
    db.commit()
    return contagem, removidas


def pares_concluidos(db: Session) -> set[tuple[int, int]]:
    return {(d, a) for d, a in db.execute(select(SyncCheckpoint.deputado_id, SyncCheckpoint.ano))}


def deve_pular(par: tuple[int, int], concluidos: set[tuple[int, int]], forcar: bool) -> bool:
    """Pula pares já coletados, exceto no ano corrente (dados mudam retroativamente)."""
    return not forcar and par[1] != date.today().year and par in concluidos


# --------------------------------------------------------------------------- deputados


def sincronizar_deputados(client: CamaraClient, db: Session, id_legislatura: int) -> int:
    """Baixa todos os deputados da legislatura e faz upsert.

    A lista repete o mesmo id quando o deputado trocou de partido; nesses casos
    o partido/UF atual vem de `GET /deputados/{id}` (`ultimoStatus`).
    """
    por_id: dict[int, list[dict[str, Any]]] = {}
    for item in client.paginar("/deputados", {"idLegislatura": id_legislatura}):
        por_id.setdefault(int(item["id"]), []).append(item)

    agora = datetime.now()
    linhas: list[dict[str, Any]] = []
    for deputado_id, itens in por_id.items():
        item = itens[-1]
        if len(itens) > 1:
            try:
                status = client.get_json(f"/deputados/{deputado_id}")["dados"]["ultimoStatus"]
                item = {**item, **{k: status.get(k) or item.get(k) for k in ("nome", "siglaPartido", "siglaUf", "urlFoto")}}
            except (requests.RequestException, KeyError, ValueError) as exc:
                logger.warning("Sem ultimoStatus do deputado %s (%s); usando a lista", deputado_id, exc)
        nome = item.get("nome") or str(deputado_id)
        linhas.append(
            {
                "id": deputado_id,
                "nome": nome,
                "nome_normalizado": normalizar_nome(nome) or "",
                "sigla_partido": item.get("siglaPartido"),
                "sigla_uf": item.get("siglaUf"),
                "url_foto": item.get("urlFoto"),
                "id_legislatura": id_legislatura,
                "atualizado_em": agora,
            }
        )
    upsert_deputados(db, linhas)
    db.commit()
    registrar_execucao(db, "deputados", len(linhas))
    logger.info("%d deputados sincronizados (legislatura %d)", len(linhas), id_legislatura)
    return len(linhas)


def ids_deputados(db: Session, id_legislatura: int) -> list[int]:
    return list(
        db.scalars(
            select(Deputado.id).where(Deputado.id_legislatura == id_legislatura).order_by(Deputado.id)
        )
    )


# --------------------------------------------------------------------------- despesas


def coletar_despesas_api(
    client: CamaraClient,
    db: Session,
    anos: list[int],
    settings: Settings,
    resumo: Resumo,
    forcar: bool = False,
    progresso: bool = True,
) -> None:
    """Coleta `GET /deputados/{id}/despesas` para cada deputado e ano.

    A API só devolve dados quando recebe `idLegislatura` junto com `ano`.
    Uma falha num par é registrada e a coleta segue para o próximo.
    """
    deputados = ids_deputados(db, settings.id_legislatura)
    concluidos = pares_concluidos(db)
    pares = [(d, a) for a in anos for d in deputados]
    for deputado_id, ano in barra(pares, progresso, desc="Despesas (API)", unit="dep-ano"):
        if deve_pular((deputado_id, ano), concluidos, forcar):
            resumo.pares_pulados += 1
            continue
        try:
            registros: list[dict[str, Any]] = []
            for item in client.paginar(
                f"/deputados/{deputado_id}/despesas",
                {"idLegislatura": settings.id_legislatura, "ano": ano},
            ):
                try:
                    registros.append(despesa_da_api(item, deputado_id))
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning("Despesa ignorada (deputado %s/%s): %s", deputado_id, ano, exc)
            contagem, removidas = gravar_par(db, deputado_id, ano, registros, fonte="api")
            resumo.somar(contagem, removidas)
        except Exception as exc:  # noqa: BLE001 - uma falha não pode abortar a coleta
            db.rollback()
            resumo.registrar_falha(f"deputado {deputado_id} / {ano}", exc)
    registrar_execucao(db, "camara-api", resumo.despesas_inseridas + resumo.despesas_atualizadas)


def coletar_despesas_bulk(
    sessao: requests.Session,
    db: Session,
    anos: list[int],
    settings: Settings,
    resumo: Resumo,
    forcar: bool = False,
    progresso: bool = True,
) -> None:
    """Modo `--bulk`: baixa `Ano-{ano}.csv.zip`, filtra a legislatura e faz upsert.

    Aplica a mesma limpeza da API (o hash é idêntico nas duas fontes). Mantém só
    linhas da legislatura configurada e de deputados já sincronizados.
    """
    deputados = {str(d) for d in ids_deputados(db, settings.id_legislatura)}
    concluidos = pares_concluidos(db)
    ano_atual = date.today().year
    for ano in anos:
        pendentes = [d for d in deputados if not deve_pular((int(d), ano), concluidos, forcar)]
        if not pendentes:
            logger.info("CSV %d: todos os deputados já têm checkpoint; pulando o ano", ano)
            resumo.pares_pulados += len(deputados)
            continue
        try:
            arquivo = baixar_arquivo(
                sessao,
                settings.bulk_url_template.format(ano=ano),
                DOWNLOAD_DIR / f"Ano-{ano}.csv.zip",
                timeout=max(settings.timeout, 120),
                reaproveitar=not forcar and ano != ano_atual,
            )
            df = pd.read_csv(
                arquivo,
                sep=";",
                dtype=str,
                encoding="utf-8-sig",
                keep_default_na=False,
                usecols=COLUNAS_CSV_CAMARA,
            )
        except Exception as exc:  # noqa: BLE001
            resumo.registrar_falha(f"CSV {ano}", exc)
            continue

        df = df[(df["codLegislatura"] == str(settings.id_legislatura)) & df["ideCadastro"].isin(deputados)]
        logger.info("CSV %d: %d linhas da legislatura %d", ano, len(df), settings.id_legislatura)
        grupos = df.groupby("ideCadastro", sort=True)
        for deputado_str, grupo in barra(grupos, progresso, desc=f"Despesas {ano} (CSV)", total=grupos.ngroups, unit="dep"):
            deputado_id = int(deputado_str)
            if deve_pular((deputado_id, ano), concluidos, forcar):
                resumo.pares_pulados += 1
                continue
            try:
                registros: list[dict[str, Any]] = []
                for linha in grupo.to_dict("records"):
                    try:
                        registros.append(despesa_do_csv(linha))
                    except (KeyError, TypeError, ValueError) as exc:
                        logger.warning("Linha ignorada (deputado %s/%s): %s", deputado_id, ano, exc)
                contagem, removidas = gravar_par(db, deputado_id, ano, registros, fonte="bulk")
                resumo.somar(contagem, removidas)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                resumo.registrar_falha(f"deputado {deputado_id} / {ano} (CSV)", exc)

        # Quem não aparece no CSV de um ano fechado não teve despesa nele (ex.: suplente
        # fora de exercício). Sem checkpoint, o ano nunca seria pulado nas próximas rodadas.
        if ano != ano_atual:
            ausentes = deputados - set(grupos.groups)
            for deputado_str in ausentes:
                marcar_checkpoint(db, int(deputado_str), ano, fonte="bulk")
            db.commit()
    registrar_execucao(db, "camara-bulk", resumo.despesas_inseridas + resumo.despesas_atualizadas)


# --------------------------------------------------------------------------- emendas


def mapa_autores(db: Session, id_legislatura: int) -> dict[str, int]:
    """Nome normalizado -> id do deputado, só para nomes sem homônimos.

    O Portal da Transparência não usa o id da Câmara, então o vínculo é pelo nome
    parlamentar. Autores sem correspondência (senadores, bancadas, comissões,
    deputados de outras legislaturas) ficam com `deputado_id` nulo.
    """
    linhas = db.execute(
        select(Deputado.nome_normalizado, Deputado.id).where(Deputado.id_legislatura == id_legislatura)
    ).all()
    repeticoes = Counter(nome for nome, _ in linhas)
    return {nome: dep_id for nome, dep_id in linhas if nome and repeticoes[nome] == 1}


def _ler_blocos(zf: zipfile.ZipFile, sufixo: str) -> Iterator[pd.DataFrame]:
    membro = next((n for n in zf.namelist() if n.endswith(sufixo)), None)
    if membro is None:
        raise FileNotFoundError(f"{sufixo} não encontrado no zip de emendas")
    with zf.open(membro) as arquivo:
        yield from pd.read_csv(
            arquivo,
            sep=";",
            dtype=str,
            encoding="cp1252",
            encoding_errors="replace",
            keep_default_na=False,
            chunksize=LINHAS_POR_BLOCO_CSV,
        )


def _substituir(
    db: Session,
    modelo: type[Emenda] | type[EmendaPagamento] | type[EmendaConvenio],
    blocos: Iterator[pd.DataFrame],
    conversor: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    coluna_ano: str | None = None,
    anos: list[int] | None = None,
    vincular: Callable[[dict[str, Any]], int | None] | None = None,
) -> int:
    """Troca as linhas dos `anos` informados (ou todas, se `None`) pelas do arquivo.

    Os arquivos de emendas são um retrato completo e não têm chave estável por
    linha, então a carga é "apaga e insere" (idempotente). Roda dentro da
    transação do chamador, que faz o commit. `vincular` define o `deputado_id`.
    """
    prefixos = {str(a) for a in anos} if anos is not None else None
    if anos is None:
        db.execute(delete(modelo))
    else:
        db.execute(delete(modelo).where(modelo.ano.in_(anos)))  # type: ignore[union-attr]
    total = 0
    for bloco in blocos:
        if prefixos is not None and coluna_ano:
            bloco = bloco[bloco[coluna_ano].str[:4].isin(prefixos)]
        registros: list[dict[str, Any]] = []
        for linha in bloco.to_dict("records"):
            try:
                registro = conversor(linha)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Linha de %s ignorada: %s", modelo.__tablename__, exc)
                continue
            if vincular is not None:
                registro["deputado_id"] = vincular(registro)
            registros.append(registro)
        for lote in em_lotes(registros, 5_000):
            db.execute(insert(modelo), list(lote))
        total += len(registros)
    return total


SQL_PROPAGAR_VINCULO = """
WITH mapa AS (
    SELECT codigo_autor, MIN(deputado_id) AS deputado_id
    FROM (
        SELECT codigo_autor, deputado_id FROM emendas
        WHERE deputado_id IS NOT NULL AND codigo_autor IS NOT NULL
        UNION
        SELECT codigo_autor, deputado_id FROM emendas_pagamentos
        WHERE deputado_id IS NOT NULL AND codigo_autor IS NOT NULL
    )
    GROUP BY codigo_autor
    HAVING COUNT(DISTINCT deputado_id) = 1
)
UPDATE {tabela}
SET deputado_id = (SELECT mapa.deputado_id FROM mapa WHERE mapa.codigo_autor = {tabela}.codigo_autor)
WHERE deputado_id IS NULL AND codigo_autor IN (SELECT codigo_autor FROM mapa)
"""


def propagar_vinculo_por_codigo(db: Session) -> int:
    """Estende o vínculo autor -> deputado pelo código do autor do Portal.

    O nome do autor muda entre anos ("IZALCI" / "IZALCI LUCAS"), mas o código é
    estável. Só usa códigos que apontam para um único deputado.
    """
    alteradas = 0
    for tabela in ("emendas", "emendas_pagamentos"):
        db.execute(text(SQL_PROPAGAR_VINCULO.format(tabela=tabela)))
        # rowcount vem -1 em UPDATE com WITH no SQLite; changes() é confiável.
        alteradas += db.scalar(text("SELECT changes()")) or 0
    return alteradas


def _chaves_pagamentos(db: Session, municipios: list[tuple[str, str]]) -> set[tuple[Any, ...]]:
    """Identidade dos pagamentos já gravados nos municípios monitorados."""
    if not municipios:
        return set()
    filtro = or_(
        *(
            and_(EmendaPagamento.sigla_uf == uf, EmendaPagamento.municipio_normalizado == nome)
            for uf, nome in municipios
        )
    )
    return {
        tuple(linha)
        for linha in db.execute(
            select(
                EmendaPagamento.codigo_emenda,
                EmendaPagamento.ano,
                EmendaPagamento.mes,
                EmendaPagamento.codigo_favorecido,
                EmendaPagamento.valor_recebido_centavos,
            ).where(filtro)
        )
    }


def municipios_monitorados(settings: Settings) -> list[tuple[str, str]]:
    """'PE/CARPINA' -> ('PE', 'CARPINA'), já normalizado."""
    pares = []
    for item in settings.municipios_monitorados:
        uf, _, nome = item.partition("/")
        if uf and nome:
            pares.append((uf.strip().upper(), normalizar_nome(nome) or ""))
    return pares


def coletar_emendas(
    sessao: requests.Session,
    db: Session,
    anos: list[int],
    settings: Settings,
    resumo: Resumo,
    forcar: bool = False,
) -> list[EmendaPagamento]:
    """Carrega catálogo de emendas, convênios e pagamentos por favorecido (com município).

    `emendas` e `emendas_convenios` recebem todos os anos do arquivo (são
    pequenos e permitem saber a área e o objeto de restos a pagar antigos);
    `emendas_pagamentos` recebe só os pagamentos feitos nos `anos` pedidos.

    O vínculo com deputados é feito pelo nome só para emendas da legislatura
    atual (evita homônimos de mandatos antigos) e depois estendido pelo código
    do autor. Retorna os pagamentos novos nos municípios monitorados.
    """
    destino = DOWNLOAD_DIR / "EmendasParlamentares.zip"
    recente = destino.exists() and time.time() - destino.stat().st_mtime < VALIDADE_DOWNLOAD_EMENDAS_S
    inicio = settings.ano_inicial_legislatura
    monitorados = municipios_monitorados(settings)
    try:
        arquivo = baixar_arquivo(
            sessao,
            settings.emendas_bulk_url,
            destino,
            timeout=max(settings.timeout, 120),
            reaproveitar=recente and not forcar,
        )
        autores = mapa_autores(db, settings.id_legislatura)
        havia_pagamentos = bool(db.scalar(select(func.count(EmendaPagamento.id))))
        antes = _chaves_pagamentos(db, monitorados)

        def vincular_emenda(r: dict[str, Any]) -> int | None:
            return autores.get(r["nome_autor_normalizado"] or "") if r["ano"] >= inicio else None

        def vincular_pagamento(r: dict[str, Any]) -> int | None:
            ano_emenda = r["ano_emenda"] or r["ano"]
            return autores.get(r["nome_autor_normalizado"] or "") if ano_emenda >= inicio else None

        with zipfile.ZipFile(arquivo) as zf:
            resumo.emendas = _substituir(
                db, Emenda, _ler_blocos(zf, "EmendasParlamentares.csv"), emenda_do_csv,
                vincular=vincular_emenda,
            )
            resumo.pagamentos_emendas = _substituir(
                db, EmendaPagamento, _ler_blocos(zf, "_PorFavorecido.csv"), pagamento_emenda_do_csv,
                coluna_ano="Ano/Mês", anos=anos, vincular=vincular_pagamento,
            )
            convenios = _substituir(
                db, EmendaConvenio, _ler_blocos(zf, "_Convenios.csv"), convenio_do_csv,
            )
        propagados = propagar_vinculo_por_codigo(db)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        resumo.registrar_falha("emendas", exc)
        return []

    vinculados = db.scalar(
        select(func.count()).select_from(EmendaPagamento).where(
            EmendaPagamento.ano.in_(anos), EmendaPagamento.deputado_id.is_not(None)
        )
    ) or 0
    logger.info(
        "Emendas: %d linhas; convênios: %d; pagamentos: %d (%d vinculados a deputados; "
        "%d linhas ligadas pelo código do autor)",
        resumo.emendas, convenios, resumo.pagamentos_emendas, vinculados, propagados,
    )
    registrar_execucao(db, "emendas", resumo.emendas + resumo.pagamentos_emendas)

    if not havia_pagamentos or not monitorados:
        return []
    novos = [
        p
        for p in db.scalars(
            select(EmendaPagamento).where(
                or_(
                    *(
                        and_(EmendaPagamento.sigla_uf == uf, EmendaPagamento.municipio_normalizado == nome)
                        for uf, nome in monitorados
                    )
                )
            )
        )
        if (p.codigo_emenda, p.ano, p.mes, p.codigo_favorecido, p.valor_recebido_centavos) not in antes
    ]
    logger.info("%d pagamentos novos nos municípios monitorados", len(novos))
    return novos


def municipios_desatualizados(db: Session, dias: int = 30) -> bool:
    """A tabela de municípios do IBGE está vazia ou foi carregada há mais de `dias` dias?"""
    ultima = db.scalar(select(func.max(SyncExecucao.concluido_em)).where(SyncExecucao.fonte == "ibge"))
    vazia = not db.scalar(select(func.count()).select_from(Municipio))
    return vazia or ultima is None or (datetime.now() - ultima).days >= dias


# --------------------------------------------------------------------------- CLI


def _ano_valido(valor: str) -> int:
    ano = int(valor)
    if not ANO_INICIAL_CEAP <= ano <= date.today().year:
        raise argparse.ArgumentTypeError(
            f"ano deve estar entre {ANO_INICIAL_CEAP} e {date.today().year}"
        )
    return ano


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m civic.scraper",
        description="Coleta deputados, despesas da cota parlamentar e emendas.",
    )
    parser.add_argument("--ano", type=_ano_valido, nargs="+", help="anos a coletar (padrão: ANOS do .env)")
    parser.add_argument("--bulk", action="store_true", help="usa os CSVs anuais da Câmara em vez da API")
    parser.add_argument("--so-deputados", action="store_true", help="só sincroniza a lista de deputados")
    parser.add_argument("--forcar", action="store_true", help="ignora checkpoints e downloads em cache")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--sem-emendas", action="store_true", help="não carrega as emendas")
    grupo.add_argument("--so-emendas", action="store_true", help="só carrega as emendas")
    parser.add_argument("--sem-progresso", action="store_true", help="desliga a barra de progresso")
    parser.add_argument("--log-level", default=None, help="DEBUG, INFO, WARNING... (padrão: LOG_LEVEL)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Executa a coleta. Retorna 0 sem falhas, 1 se algum item falhou."""
    args = criar_parser().parse_args(argv)
    settings = get_settings()
    logging.basicConfig(
        level=(args.log_level or settings.log_level).upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    anos = sorted(set(args.ano or settings.anos))
    progresso = not args.sem_progresso and sys.stderr.isatty()

    init_db()
    resumo = Resumo()
    client = CamaraClient(settings)
    db = SessionLocal()
    contexto = logging_redirect_tqdm() if progresso else nullcontext()
    try:
        with contexto:
            logger.info("Anos: %s | modo: %s", anos, "bulk" if args.bulk else "API")
            precisa_deputados = not args.so_emendas or not ids_deputados(db, settings.id_legislatura)
            if precisa_deputados:
                try:
                    resumo.deputados = sincronizar_deputados(client, db, settings.id_legislatura)
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    resumo.registrar_falha("lista de deputados", exc)

            if not args.so_deputados and not args.so_emendas:
                if args.bulk:
                    coletar_despesas_bulk(client.sessao, db, anos, settings, resumo, args.forcar, progresso)
                else:
                    coletar_despesas_api(client, db, anos, settings, resumo, args.forcar, progresso)

            novos: list[EmendaPagamento] = []
            if not args.so_deputados and not args.sem_emendas:
                novos = coletar_emendas(client.sessao, db, anos, settings, resumo, args.forcar)

            if not args.so_deputados:
                if args.forcar or municipios_desatualizados(db):
                    try:
                        atualizar_municipios(client.sessao, db, settings)
                        registrar_execucao(db, "ibge", 1)
                    except Exception as exc:  # noqa: BLE001
                        db.rollback()
                        resumo.registrar_falha("municípios do IBGE", exc)
                try:
                    logger.info("Alertas recalculados: %s", recalcular_se_configurado(db, settings))
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    resumo.registrar_falha("alertas", exc)
                notificar_telegram(novos, settings, client.sessao)
    except KeyboardInterrupt:
        db.rollback()
        logger.warning("Interrompido. O que já tinha checkpoint está salvo; rode de novo para retomar.")
        resumo.log()
        return 130
    finally:
        db.close()

    resumo.log()
    return 1 if resumo.falhas else 0


if __name__ == "__main__":
    sys.exit(main())
