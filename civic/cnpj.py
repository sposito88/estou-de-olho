"""Enriquece os fornecedores da cota com a base aberta de CNPJ da Receita Federal.

Uso:
    python -m civic.cnpj [--referencia 2026-09] [--forcar] [--manter-arquivos]

Baixa (≈7 GB, com retomada) os arquivos Estabelecimentos, Empresas e Simples
do mês, lê em blocos e guarda só os CNPJs que aparecem nas despesas. Depois
recalcula os sinais de alerta. A base é mensal; rodar uma vez por mês basta.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
import zipfile
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pandas as pd
import requests
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from civic.alertas import recalcular_se_configurado
from civic.cleaning import normalizar_nome, para_centavos, parse_data_receita
from civic.config import Settings, get_settings
from civic.database import SessionLocal, init_db
from civic.ibge import atualizar_municipios
from civic.models import (
    ContratoMunicipal,
    ContratoPncp,
    Despesa,
    DespesaMunicipal,
    DespesaSenado,
    Fornecedor,
    Municipio,
    Socio,
    VerbaIndenizatoria,
)
from civic.scraper import DOWNLOAD_DIR, criar_sessao, registrar_execucao

logger = logging.getLogger("civic.cnpj")

LINHAS_POR_BLOCO = 500_000
PARTES = [str(i) for i in range(10)]

SITUACOES = {"01": "NULA", "02": "ATIVA", "03": "SUSPENSA", "04": "INAPTA", "08": "BAIXADA"}
PORTES = {"00": "NÃO INFORMADO", "01": "MICROEMPRESA", "03": "EMPRESA DE PEQUENO PORTE", "05": "DEMAIS"}

# Layout dos CSVs (sem cabeçalho), conforme o dicionário de dados da Receita.
COLUNAS_ESTABELECIMENTOS = {
    0: "basico", 1: "ordem", 2: "dv", 3: "matriz_filial", 4: "nome_fantasia", 5: "situacao",
    6: "data_situacao", 10: "data_inicio", 11: "cnae", 17: "bairro", 18: "cep", 19: "uf", 20: "municipio",
}
COLUNAS_EMPRESAS = {0: "basico", 1: "razao_social", 2: "natureza", 4: "capital", 5: "porte"}
COLUNAS_SOCIOS = {0: "basico", 1: "tipo", 2: "nome", 3: "documento", 4: "qualificacao", 5: "data_entrada"}
TIPOS_SOCIO = {"1": "PJ", "2": "PF", "3": "EX"}
COLUNAS_SIMPLES = {
    0: "basico", 1: "opcao_simples", 4: "opcao_mei", 5: "data_opcao_mei", 6: "data_exclusao_mei",
}


# --------------------------------------------------------------------------- conversões (puras)


def estabelecimento_da_linha(linha: dict[str, str], municipios_receita: dict[str, str]) -> dict[str, Any]:
    """Linha de Estabelecimentos (já com nomes de coluna) -> campos de `Fornecedor`."""
    return {
        "cnpj": f"{linha['basico']}{linha['ordem']}{linha['dv']}",
        "nome_fantasia": linha["nome_fantasia"].strip() or None,
        "matriz": linha["matriz_filial"] == "1",
        "situacao_cadastral": SITUACOES.get(linha["situacao"], linha["situacao"] or None),
        "data_situacao_cadastral": parse_data_receita(linha["data_situacao"]),
        "data_inicio_atividade": parse_data_receita(linha["data_inicio"]),
        "cnae_principal": linha["cnae"] or None,
        "bairro": linha["bairro"].strip() or None,
        "cep": linha["cep"] or None,
        "sigla_uf": linha["uf"] or None,
        "municipio": municipios_receita.get(linha["municipio"]),
    }


def empresa_da_linha(linha: dict[str, str]) -> dict[str, Any]:
    capital = linha["capital"]
    return {
        "razao_social": linha["razao_social"].strip() or None,
        "natureza_juridica": linha["natureza"] or None,
        "capital_social_centavos": para_centavos(capital) if capital else None,
        "porte": PORTES.get(linha["porte"]),
    }


def socio_da_linha(linha: dict[str, str], qualificacoes: dict[str, str]) -> dict[str, Any]:
    """Linha de Socios -> `Socio`. PF guarda só os 6 dígitos centrais do CPF (é o que a Receita publica)."""
    tipo = TIPOS_SOCIO.get(linha["tipo"], "EX")
    documento = re.sub(r"\D", "", linha["documento"] or "")
    if tipo == "PF":
        documento = documento[-6:] if len(documento) >= 6 else None
    nome = (linha["nome"] or "").strip()
    return {
        "cnpj_basico": linha["basico"],
        "tipo": tipo,
        "nome": nome,
        "nome_normalizado": normalizar_nome(nome) or "",
        "documento": documento or None,
        "qualificacao": qualificacoes.get(linha["qualificacao"], linha["qualificacao"] or None),
        "data_entrada": parse_data_receita(linha["data_entrada"]),
    }


def simples_da_linha(linha: dict[str, str]) -> dict[str, Any]:
    return {
        "opcao_simples": linha["opcao_simples"] == "S",
        "opcao_mei": linha["opcao_mei"] == "S",
        "data_opcao_mei": parse_data_receita(linha["data_opcao_mei"]),
        "data_exclusao_mei": parse_data_receita(linha["data_exclusao_mei"]),
    }


# --------------------------------------------------------------------------- WebDAV


class ReceitaWebDav:
    """Acesso ao compartilhamento público da Receita (Nextcloud) via WebDAV."""

    def __init__(self, settings: Settings, sessao: requests.Session | None = None) -> None:
        self.sessao = sessao or criar_sessao()
        self.auth = (settings.cnpj_webdav_token, "")
        self.base = f"{settings.cnpj_webdav_url}/{settings.cnpj_webdav_token}/{settings.cnpj_pasta}"
        self.timeout = max(settings.timeout, 120)
        self.pasta_local = settings.cnpj_pasta_local

    def referencias(self) -> list[str]:
        """Meses disponíveis ('2026-09', ...), do mais antigo ao mais recente."""
        resposta = self.sessao.request(
            "PROPFIND", f"{self.base}/", auth=self.auth, headers={"Depth": "1"}, timeout=self.timeout
        )
        resposta.raise_for_status()
        hrefs = re.findall(r"<d:href>([^<]+)</d:href>", resposta.text)
        return sorted({m.group(1) for h in hrefs if (m := re.search(r"/(\d{4}-\d{2})/?$", unquote(h)))})

    def baixar(self, referencia: str, arquivo: str, destino: Path) -> Path:
        """Baixa com retomada: um `.part` incompleto continua de onde parou (HTTP Range).

        Antes, procura o arquivo em `CNPJ_PASTA_LOCAL`; se lá houver um zip com
        o mesmo tamanho do arquivo do mês na Receita, devolve esse caminho.
        """
        url = f"{self.base}/{referencia}/{arquivo}"
        cabecalho = self.sessao.head(url, auth=self.auth, timeout=self.timeout)
        cabecalho.raise_for_status()
        tamanho = int(cabecalho.headers.get("Content-Length", 0))
        if destino.exists() and destino.stat().st_size == tamanho:
            return destino
        if self.pasta_local is not None:
            local = self.pasta_local / arquivo
            if tamanho and local.is_file() and local.stat().st_size == tamanho:
                logger.info("%s: usando cópia local em %s (mesmo tamanho da Receita)", arquivo, self.pasta_local)
                return local
        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial = destino.with_suffix(destino.suffix + ".part")
        inicio = parcial.stat().st_size if parcial.exists() else 0
        if tamanho and inicio >= tamanho:
            parcial.unlink()
            inicio = 0
        headers = {"Range": f"bytes={inicio}-"} if inicio else {}
        logger.info("Baixando %s (%.0f MB%s)", arquivo, tamanho / 1e6, f", retomando em {inicio / 1e6:.0f} MB" if inicio else "")
        t0 = time.monotonic()
        with self.sessao.get(url, auth=self.auth, headers=headers, stream=True, timeout=self.timeout) as resposta:
            resposta.raise_for_status()
            modo = "ab" if inicio and resposta.status_code == 206 else "wb"
            with parcial.open(modo) as saida:
                for bloco in resposta.iter_content(chunk_size=1 << 20):
                    saida.write(bloco)
        if tamanho and parcial.stat().st_size != tamanho:
            raise OSError(f"{arquivo}: download incompleto ({parcial.stat().st_size} de {tamanho} bytes)")
        parcial.replace(destino)
        logger.info("%s baixado em %.0f s", arquivo, time.monotonic() - t0)
        return destino


def ler_blocos(caminho: Path, colunas: dict[int, str]) -> Iterator[pd.DataFrame]:
    """Lê o CSV (único) de dentro do zip em blocos, só com as colunas pedidas, já nomeadas."""
    with zipfile.ZipFile(caminho) as zf, zf.open(zf.namelist()[0]) as arquivo:
        for bloco in pd.read_csv(
            arquivo,
            sep=";",
            header=None,
            dtype=str,
            encoding="latin1",
            usecols=list(colunas),
            keep_default_na=False,
            chunksize=LINHAS_POR_BLOCO,
            on_bad_lines="skip",
        ):
            yield bloco.rename(columns=colunas)


# --------------------------------------------------------------------------- carga


def cnpjs_alvo(db: Session) -> set[str]:
    """CNPJs de quem recebeu cota (deputados e senadores), verba estadual, empenho ou contrato público."""
    alvo: set[str] = set()
    for coluna, tipo in (
        (Despesa.cnpj_cpf, Despesa.tipo_pessoa),
        (VerbaIndenizatoria.cnpj_cpf, VerbaIndenizatoria.tipo_pessoa),
        (DespesaMunicipal.cpf_cnpj, DespesaMunicipal.tipo_pessoa),
        (DespesaSenado.cnpj_cpf, DespesaSenado.tipo_pessoa),
        (ContratoPncp.fornecedor_ni, ContratoPncp.tipo_pessoa),
        (ContratoMunicipal.cpf_cnpj, ContratoMunicipal.tipo_pessoa),
    ):
        alvo.update(c for c in db.scalars(select(coluna).where(tipo == "PJ").distinct()) if c and len(c) == 14)
    return alvo


def mapa_ibge(db: Session) -> dict[tuple[str, str], str]:
    return {
        (uf, nome): codigo
        for codigo, uf, nome in db.execute(
            select(Municipio.codigo_ibge, Municipio.sigla_uf, Municipio.nome_normalizado)
        )
    }


def carregar_fornecedores(
    dav: ReceitaWebDav,
    db: Session,
    referencia: str,
    partes: list[str],
    manter_arquivos: bool,
) -> int:
    """Baixa e processa a base do mês e substitui a tabela `fornecedores`.

    Para cada arquivo: baixa, filtra pelos CNPJs das despesas, apaga o zip
    (salvo `manter_arquivos`) e segue. Uma falha interrompe a carga sem tocar
    na tabela atual.
    """
    pasta = DOWNLOAD_DIR / "cnpj" / referencia
    alvo = cnpjs_alvo(db)
    basicos = {c[:8] for c in alvo}
    logger.info("%d CNPJs de fornecedores para procurar na base %s", len(alvo), referencia)

    def obter(nome: str) -> Path:
        return dav.baixar(referencia, nome, pasta / nome)

    def descartar(caminho: Path) -> None:
        # Só apaga o que este sistema baixou; cópias locais de outros sistemas ficam.
        if not manter_arquivos and caminho.resolve().is_relative_to(pasta.resolve()):
            caminho.unlink(missing_ok=True)

    municipios_zip = obter("Municipios.zip")
    with zipfile.ZipFile(municipios_zip) as zf, zf.open(zf.namelist()[0]) as arq:
        tabela = pd.read_csv(arq, sep=";", header=None, dtype=str, encoding="latin1", keep_default_na=False)
    municipios_receita = dict(zip(tabela[0], tabela[1]))

    fornecedores: dict[str, dict[str, Any]] = {}
    for parte in partes:
        caminho = obter(f"Estabelecimentos{parte}.zip")
        for bloco in ler_blocos(caminho, COLUNAS_ESTABELECIMENTOS):
            bloco = bloco[bloco["basico"].isin(basicos)]
            for linha in bloco.to_dict("records"):
                registro = estabelecimento_da_linha(linha, municipios_receita)
                if registro["cnpj"] in alvo:
                    fornecedores[registro["cnpj"]] = registro
        logger.info("Estabelecimentos%s: %d fornecedores encontrados até agora", parte, len(fornecedores))
        descartar(caminho)

    por_basico: dict[str, list[dict[str, Any]]] = {}
    for registro in fornecedores.values():
        por_basico.setdefault(registro["cnpj"][:8], []).append(registro)

    for parte in partes:
        caminho = obter(f"Empresas{parte}.zip")
        for bloco in ler_blocos(caminho, COLUNAS_EMPRESAS):
            for linha in bloco[bloco["basico"].isin(por_basico.keys())].to_dict("records"):
                dados = empresa_da_linha(linha)
                for registro in por_basico[linha["basico"]]:
                    registro.update(dados)
        descartar(caminho)

    caminho = obter("Simples.zip")
    for bloco in ler_blocos(caminho, COLUNAS_SIMPLES):
        for linha in bloco[bloco["basico"].isin(por_basico.keys())].to_dict("records"):
            dados = simples_da_linha(linha)
            for registro in por_basico[linha["basico"]]:
                registro.update(dados)
    descartar(caminho)

    with zipfile.ZipFile(obter("Qualificacoes.zip")) as zf, zf.open(zf.namelist()[0]) as arq:
        tabela_q = pd.read_csv(arq, sep=";", header=None, dtype=str, encoding="latin1", keep_default_na=False)
    qualificacoes = dict(zip(tabela_q[0], tabela_q[1]))
    socios: list[dict[str, Any]] = []
    for parte in partes:
        caminho = obter(f"Socios{parte}.zip")
        for bloco in ler_blocos(caminho, COLUNAS_SOCIOS):
            for linha in bloco[bloco["basico"].isin(por_basico.keys())].to_dict("records"):
                socios.append(socio_da_linha(linha, qualificacoes))
        descartar(caminho)
    db.execute(delete(Socio))
    for i in range(0, len(socios), 5_000):
        db.execute(insert(Socio), socios[i : i + 5_000])
    logger.info("%d sócios dos fornecedores", len(socios))

    ibge = mapa_ibge(db)
    agora = datetime.now()
    linhas = []
    for registro in fornecedores.values():
        chave = (registro.get("sigla_uf") or "", normalizar_nome(registro.get("municipio")) or "")
        linhas.append(
            {
                "razao_social": None, "natureza_juridica": None, "capital_social_centavos": None, "porte": None,
                "opcao_simples": None, "opcao_mei": None, "data_opcao_mei": None, "data_exclusao_mei": None,
                **registro,
                "codigo_municipio_ibge": ibge.get(chave),
                "referencia": referencia,
                "atualizado_em": agora,
            }
        )
    db.execute(delete(Fornecedor))
    for i in range(0, len(linhas), 5_000):
        db.execute(insert(Fornecedor), linhas[i : i + 5_000])
    db.commit()
    sem_municipio = sum(1 for l in linhas if not l["codigo_municipio_ibge"])
    logger.info(
        "%d de %d fornecedores encontrados na base (%d sem município do IBGE)",
        len(linhas), len(alvo), sem_municipio,
    )
    return len(linhas)


# --------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m civic.cnpj", description=__doc__.splitlines()[0])
    parser.add_argument("--referencia", help="mês da base (ex.: 2026-09); padrão: o mais recente")
    parser.add_argument("--partes", default="".join(PARTES), help="partes 0-9 a processar (para testes)")
    parser.add_argument("--forcar", action="store_true", help="processa mesmo se a referência já foi carregada")
    parser.add_argument("--manter-arquivos", action="store_true", help="não apaga os zips depois de ler")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(
        level=(args.log_level or settings.log_level).upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    init_db()
    db = SessionLocal()
    dav = ReceitaWebDav(settings)
    inicio = time.monotonic()
    try:
        referencia = args.referencia or dav.referencias()[-1]
        atual = db.scalar(select(Fornecedor.referencia).limit(1))
        cobertos = set(db.scalars(select(Fornecedor.cnpj)))
        novos = len(cnpjs_alvo(db) - cobertos)
        # Sem base nova e sem muitos CNPJs novos (fornecedores que apareceram no mês), não há o que fazer.
        if atual == referencia and not args.forcar and novos < 500:
            logger.info("Base %s já carregada (%d CNPJs novos fora dela); nada a fazer", referencia, novos)
            return 0
        if not db.scalar(select(Municipio.codigo_ibge).limit(1)):
            atualizar_municipios(dav.sessao, db, settings)
        total = carregar_fornecedores(dav, db, referencia, list(args.partes), args.manter_arquivos)
        registrar_execucao(db, "cnpj", total, detalhes=referencia)
        contagem = recalcular_se_configurado(db, settings)
        logger.info("Alertas recalculados: %s", contagem)
    except Exception:
        db.rollback()
        logger.exception("Falha ao carregar a base de CNPJ")
        return 1
    finally:
        db.close()
    logger.info("Concluído em %.0f min", (time.monotonic() - inicio) / 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
