"""Cota dos senadores (CEAPS) e cadastro de senadores.

Uso:
    python -m civic.senado [--ano 2025 ...]

O Senado publica um CSV por ano com todas as despesas reembolsadas. A carga
substitui o ano inteiro (o arquivo é um retrato completo e não tem chave estável).
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import sys
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from civic.alertas import recalcular_se_configurado
from civic.cleaning import despesa_senado_do_csv, normalizar_nome
from civic.config import Settings, get_settings
from civic.database import SessionLocal, init_db
from civic.models import DespesaSenado, Senador
from civic.pernambuco import ClienteJson
from civic.scraper import Resumo, em_lotes, registrar_execucao

logger = logging.getLogger("civic.senado")


class MapaSenadores:
    """Liga o nome usado na CEAPS ao senador: nome parlamentar, nome completo ou,
    em último caso, todas as palavras do nome contidas no nome completo de um único senador."""

    def __init__(self, cadastro: list[tuple[int, str, str]]) -> None:
        self.exatos: dict[str, int] = {}
        self.completos: list[tuple[int, set[str]]] = []
        for codigo, nome, completo in cadastro:
            for chave in (normalizar_nome(nome), normalizar_nome(completo)):
                if chave:
                    self.exatos.setdefault(chave, codigo)
            self.completos.append((codigo, set((normalizar_nome(completo) or "").split())))

    def get(self, nome: str, padrao: int | None = None) -> int | None:
        if nome in self.exatos:
            return self.exatos[nome]
        palavras = set(nome.split())
        candidatos = {codigo for codigo, completo in self.completos if palavras and palavras <= completo}
        return candidatos.pop() if len(candidatos) == 1 else padrao


def sincronizar_senadores(cliente: ClienteJson, db: Session, s: Settings) -> MapaSenadores:
    """Cadastro da legislatura atual e da anterior + quem está em exercício."""
    base = s.senado_dados_abertos_url
    parlamentares = []
    for legislatura in (s.senado_legislatura - 1, s.senado_legislatura):  # a atual sobrescreve a anterior
        corpo = cliente.get(f"{base}/senador/lista/legislatura/{legislatura}")
        parlamentares += corpo["ListaParlamentarLegislatura"]["Parlamentares"]["Parlamentar"]
    atuais = {
        p["IdentificacaoParlamentar"]["CodigoParlamentar"]: p["IdentificacaoParlamentar"]
        for p in cliente.get(f"{base}/senador/lista/atual")["ListaParlamentarEmExercicio"]["Parlamentares"]["Parlamentar"]
    }
    agora = datetime.now()
    linhas: dict[int, dict[str, Any]] = {}
    for p in parlamentares:
        ident = p["IdentificacaoParlamentar"]
        codigo = ident["CodigoParlamentar"]
        mandatos = (p.get("Mandatos") or {}).get("Mandato") or []
        mandatos = mandatos if isinstance(mandatos, list) else [mandatos]
        atual = atuais.get(codigo, {})
        linhas[int(codigo)] = {
            "id": int(codigo),
            "nome": ident["NomeParlamentar"],
            "nome_normalizado": normalizar_nome(ident["NomeParlamentar"]) or "",
            "sigla_partido": atual.get("SiglaPartidoParlamentar"),
            "sigla_uf": atual.get("UfParlamentar") or (mandatos[0].get("UfParlamentar") if mandatos else None),
            "url_foto": (atual.get("UrlFotoParlamentar")
                         or f"https://www.senado.leg.br/senadores/img/fotos-oficiais/senador{codigo}.jpg").replace("http://", "https://"),
            "em_exercicio": codigo in atuais,
            "atualizado_em": agora,
            "_completo": ident.get("NomeCompletoParlamentar") or ident["NomeParlamentar"],
        }
    valores = [{k: v for k, v in l.items() if k != "_completo"} for l in linhas.values()]
    stmt = sqlite_insert(Senador).values(valores)
    stmt = stmt.on_conflict_do_update(index_elements=[Senador.id], set_={c: stmt.excluded[c] for c in valores[0] if c != "id"})
    db.execute(stmt)
    db.commit()
    logger.info("%d senadores (%d em exercício)", len(valores), sum(1 for v in valores if v["em_exercicio"]))
    # Em exercício primeiro: em homônimos, vale quem está no mandato.
    ordem = sorted(linhas.values(), key=lambda l: not l["em_exercicio"])
    return MapaSenadores([(l["id"], l["nome"], l["_completo"]) for l in ordem])


def carregar_ceaps(cliente: ClienteJson, db: Session, ano: int, s: Settings, senadores: MapaSenadores) -> int:
    """Substitui as despesas do ano pelas do CSV do Senado."""
    resposta = cliente.sessao.get(
        s.senado_ceaps_url_template.format(ano=ano), timeout=cliente.timeout, headers={"Accept": "*/*"}
    )
    resposta.raise_for_status()
    texto = resposta.content.decode("latin1")
    # A 1ª linha é "ULTIMA ATUALIZACAO"; o cabeçalho vem na 2ª.
    corpo = texto.split("\n", 1)[1] if texto.startswith('"ULTIMA') else texto
    linhas, sem_vinculo = [], set()
    for linha in csv.DictReader(io.StringIO(corpo), delimiter=";"):
        try:
            registro = despesa_senado_do_csv(linha, senadores)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Linha da CEAPS %d ignorada: %s", ano, exc)
            continue
        if registro["senador_id"] is None:
            sem_vinculo.add(registro["nome_senador"])
        linhas.append(registro)
    db.execute(delete(DespesaSenado).where(DespesaSenado.ano == ano))
    for lote in em_lotes(linhas, 5_000):
        db.execute(insert(DespesaSenado), list(lote))
    db.commit()
    if sem_vinculo:
        logger.warning("CEAPS %d: senadores sem cadastro na legislatura: %s", ano, sorted(sem_vinculo))
    logger.info("CEAPS %d: %d despesas", ano, len(linhas))
    return len(linhas)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m civic.senado", description=__doc__.splitlines()[0])
    parser.add_argument("--ano", type=int, nargs="+", help="anos (padrão: ANOS do .env)")
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
    cliente = ClienteJson(s.req_per_sec, max(s.timeout, 120))
    total = 0
    try:
        senadores = sincronizar_senadores(cliente, db, s)
        for ano in sorted(a for a in (args.ano or s.anos) if a <= date.today().year):
            try:
                total += carregar_ceaps(cliente, db, ano, s, senadores)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                resumo.registrar_falha(f"CEAPS {ano}", exc)
        registrar_execucao(db, "senado", total)
        logger.info("Alertas recalculados: %s", recalcular_se_configurado(db, s))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        resumo.registrar_falha("Senado", exc)
    finally:
        db.close()
    for falha in resumo.falhas:
        logger.info("  - %s", falha)
    return 1 if resumo.falhas else 0


if __name__ == "__main__":
    sys.exit(main())
