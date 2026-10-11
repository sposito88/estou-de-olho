from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
import requests
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from civic import avisos, scraper
from civic.cleaning import parse_data_receita
from civic.cnpj import ReceitaWebDav, empresa_da_linha, estabelecimento_da_linha, simples_da_linha
from civic.config import Settings
from civic.models import Emenda, EmendaPagamento
from tests.conftest import deputado

# --------------------------------------------------------------------------- Receita


def test_parse_data_receita() -> None:
    assert parse_data_receita("20050518") == date(2005, 5, 18)
    assert parse_data_receita("00000000") is None
    assert parse_data_receita("0") is None
    assert parse_data_receita("") is None
    assert parse_data_receita("20051340") is None


def test_estabelecimento_da_linha() -> None:
    linha = {
        "basico": "07396865", "ordem": "0001", "dv": "68", "matriz_filial": "1", "nome_fantasia": "  ",
        "situacao": "08", "data_situacao": "20170210", "data_inicio": "20050518", "cnae": "1412602",
        "bairro": "DOS LAGOS", "cep": "89136000", "uf": "SC", "municipio": "8297",
    }
    r = estabelecimento_da_linha(linha, {"8297": "RODEIO"})
    assert r["cnpj"] == "07396865000168"
    assert r["nome_fantasia"] is None
    assert r["matriz"] is True
    assert r["situacao_cadastral"] == "BAIXADA"
    assert r["data_situacao_cadastral"] == date(2017, 2, 10)
    assert r["data_inicio_atividade"] == date(2005, 5, 18)
    assert r["municipio"] == "RODEIO"


def test_empresa_e_simples_da_linha() -> None:
    e = empresa_da_linha({"razao_social": "ACME LTDA ", "natureza": "2062", "capital": "1000,50", "porte": "01"})
    assert e == {
        "razao_social": "ACME LTDA",
        "natureza_juridica": "2062",
        "capital_social_centavos": 100050,
        "porte": "MICROEMPRESA",
    }
    s = simples_da_linha(
        {"opcao_simples": "S", "opcao_mei": "N", "data_opcao_mei": "20200101", "data_exclusao_mei": "20231231"}
    )
    assert s == {
        "opcao_simples": True,
        "opcao_mei": False,
        "data_opcao_mei": date(2020, 1, 1),
        "data_exclusao_mei": date(2023, 12, 31),
    }


class _Resposta:
    def __init__(self, status: int, corpo: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self._corpo = corpo
        self.headers = headers or {}
        self.text = corpo.decode("utf-8", "ignore")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size: int) -> Any:
        for i in range(0, len(self._corpo), chunk_size):
            yield self._corpo[i : i + chunk_size]

    def __enter__(self) -> _Resposta:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _SessaoFalsa:
    """Servidor WebDAV falso que respeita o cabeçalho Range."""

    def __init__(self, conteudo: bytes) -> None:
        self.conteudo = conteudo
        self.ranges: list[str | None] = []

    def head(self, url: str, **_: Any) -> _Resposta:
        return _Resposta(200, headers={"Content-Length": str(len(self.conteudo))})

    def get(self, url: str, headers: dict[str, str] | None = None, **_: Any) -> _Resposta:
        faixa = (headers or {}).get("Range")
        self.ranges.append(faixa)
        if faixa:
            inicio = int(faixa.removeprefix("bytes=").rstrip("-"))
            return _Resposta(206, self.conteudo[inicio:])
        return _Resposta(200, self.conteudo)

    def request(self, metodo: str, url: str, **_: Any) -> _Resposta:
        assert metodo == "PROPFIND"
        xml = (
            "<d:multistatus><d:response><d:href>/x/CNPJ/</d:href></d:response>"
            "<d:response><d:href>/x/CNPJ/2026-08/</d:href></d:response>"
            "<d:response><d:href>/x/CNPJ/2026-09/</d:href></d:response>"
            "<d:response><d:href>/x/CNPJ/cnpj.tar.gz</d:href></d:response></d:multistatus>"
        )
        return _Resposta(207, xml.encode())


def test_webdav_lista_referencias(settings: Settings) -> None:
    dav = ReceitaWebDav(settings, _SessaoFalsa(b""))  # type: ignore[arg-type]
    assert dav.referencias() == ["2026-08", "2026-09"]


def test_webdav_retoma_download_parcial(tmp_path: Path, settings: Settings) -> None:
    conteudo = bytes(range(256)) * 100
    sessao = _SessaoFalsa(conteudo)
    destino = tmp_path / "Simples.zip"
    destino.with_suffix(".zip.part").write_bytes(conteudo[:1000])  # download interrompido

    dav = ReceitaWebDav(settings, sessao)  # type: ignore[arg-type]
    assert dav.baixar("2026-09", "Simples.zip", destino) == destino
    assert destino.read_bytes() == conteudo
    assert sessao.ranges == ["bytes=1000-"]

    # Já completo: não baixa de novo.
    dav.baixar("2026-09", "Simples.zip", destino)
    assert sessao.ranges == ["bytes=1000-"]


# --------------------------------------------------------------------------- vínculo autor -> deputado


def test_propaga_vinculo_pelo_codigo_do_autor(db: Session) -> None:
    db.add(deputado(10, "Izalci Lucas", "PL", "DF"))
    db.flush()
    db.add_all(
        [
            # 2024: casou pelo nome
            Emenda(codigo_emenda="202400010001", ano=2024, codigo_autor="2363", nome_autor="IZALCI LUCAS",
                   nome_autor_normalizado="IZALCI LUCAS", deputado_id=10),
            # 2019: outro nome, mesmo código -> deve ser ligado
            Emenda(codigo_emenda="201900010001", ano=2019, codigo_autor="2363", nome_autor="IZALCI",
                   nome_autor_normalizado="IZALCI", deputado_id=None),
            # código de outro autor: continua sem vínculo
            Emenda(codigo_emenda="201900020001", ano=2019, codigo_autor="9999", nome_autor="FULANO",
                   nome_autor_normalizado="FULANO", deputado_id=None),
            EmendaPagamento(codigo_emenda="201900010001", ano=2024, mes=3, codigo_autor="2363",
                            nome_autor="IZALCI", nome_autor_normalizado="IZALCI", deputado_id=None,
                            valor_recebido_centavos=100),
        ]
    )
    db.commit()
    assert scraper.propagar_vinculo_por_codigo(db) == 2
    db.commit()
    vinculos = dict(db.execute(select(Emenda.codigo_emenda, Emenda.deputado_id)).all())
    assert vinculos == {"202400010001": 10, "201900010001": 10, "201900020001": None}
    assert db.scalar(select(EmendaPagamento.deputado_id)) == 10


def test_municipios_monitorados() -> None:
    s = Settings(_env_file=None, municipios_monitorados="PE/Carpina, pe/Poço Redondo")  # type: ignore[call-arg]
    assert scraper.municipios_monitorados(s) == [("PE", "CARPINA"), ("PE", "POCO REDONDO")]


# --------------------------------------------------------------------------- avisos (Telegram)


def _pagamento(valor: int, autor: str = "CLARISSA TERCIO") -> EmendaPagamento:
    return EmendaPagamento(
        codigo_emenda="202400010001", ano=2026, mes=9, nome_autor=autor, favorecido="FUNDO MUNICIPAL DE SAUDE",
        sigla_uf="PE", municipio="CARPINA", municipio_normalizado="CARPINA", valor_recebido_centavos=valor,
    )


def test_montar_mensagens() -> None:
    [msg] = avisos.montar_mensagens([_pagamento(100_00), _pagamento(500_00, "TULIO <GADELHA>")], "https://site")
    assert "Carpina – PE" in msg
    assert "2 pagamento(s) novo(s), total de <b>R$ 600,00</b>" in msg
    assert msg.index("R$ 500,00") < msg.index("R$ 100,00")  # maior primeiro
    assert "&lt;Gadelha&gt;" in msg  # escapa HTML
    assert 'href="https://site/cidade/PE/CARPINA"' in msg
    assert "set/2026" in msg


class _Correio:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.enviados: list[dict[str, Any]] = []

    def post(self, url: str, json: dict[str, Any], **_: Any) -> _Resposta:
        self.enviados.append({"url": url, **json})
        return _Resposta(self.status)


def test_notificar_sem_configuracao_nao_envia(settings: Settings) -> None:
    correio = _Correio()
    assert avisos.notificar_telegram([_pagamento(100)], settings, correio) == 0  # type: ignore[arg-type]
    assert correio.enviados == []


def test_notificar_envia_para_o_chat(settings: Settings) -> None:
    s = settings.model_copy(update={"telegram_bot_token": SecretStr("123:abc"), "telegram_chat_id": "-100"})
    correio = _Correio()
    assert avisos.notificar_telegram([_pagamento(100)], s, correio) == 1  # type: ignore[arg-type]
    assert correio.enviados[0]["url"].endswith("/bot123:abc/sendMessage")
    assert correio.enviados[0]["chat_id"] == "-100"
    assert correio.enviados[0]["parse_mode"] == "HTML"


def test_notificar_falha_nao_quebra_e_nao_vaza_token(settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    s = settings.model_copy(update={"telegram_bot_token": SecretStr("123:segredo"), "telegram_chat_id": "-100"})
    assert avisos.notificar_telegram([_pagamento(100)], s, _Correio(status=500)) == 0  # type: ignore[arg-type]
    assert "Falha ao enviar" in caplog.text
    assert "segredo" not in caplog.text


def test_webdav_usa_copia_local_de_mesmo_tamanho(tmp_path: Path, settings: Settings) -> None:
    conteudo = b"x" * 5000
    local = tmp_path / "somabase"
    local.mkdir()
    (local / "Simples.zip").write_bytes(conteudo)
    (local / "Empresas0.zip").write_bytes(b"versao antiga")  # tamanho diferente: não serve
    sessao = _SessaoFalsa(conteudo)
    dav = ReceitaWebDav(settings.model_copy(update={"cnpj_pasta_local": local}), sessao)  # type: ignore[arg-type]

    assert dav.baixar("2026-09", "Simples.zip", tmp_path / "downloads" / "Simples.zip") == local / "Simples.zip"
    assert sessao.ranges == []  # nada baixado

    destino = tmp_path / "downloads" / "Empresas0.zip"
    assert dav.baixar("2026-09", "Empresas0.zip", destino) == destino
    assert destino.read_bytes() == conteudo
