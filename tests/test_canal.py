from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from civic import canal
from civic.config import get_settings
from civic.models import Alerta, Municipio, SyncExecucao

ONTEM = datetime(2026, 10, 11, 4, 0)


def _alerta(tipo: str, prioridade: int, titulo: str, cnpj: str | None = "99000001000101") -> Alerta:
    return Alerta(tipo=tipo, gravidade="alta", esfera="municipal", municipio_ibge="2604007", cnpj=cnpj, ano=2026,
                  valor_centavos=1_000_000_00, titulo=titulo, descricao="...", prioridade=prioridade,
                  chave=titulo, primeira_vez=ONTEM + timedelta(hours=20), calculado_em=ONTEM)


def test_resumo_so_com_alertas_fortes_e_sem_pessoa_fisica(fabrica: sessionmaker[Session],
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "site_url", "https://estoudeolho.com.br")
    with fabrica() as db:
        db.add(Municipio(codigo_ibge="2604007", nome="Carpina", nome_normalizado="CARPINA", sigla_uf="PE"))
        db.add_all([
            _alerta("pix_parado", 90, "R$ 1,98 mi de Emenda Pix parados"),
            _alerta("servidor_socio", 95, "Fulano (secretário) é sócio da empresa X"),
            _alerta("empresa_nova", 30, "Empresa aberta ontem"),  # fraco: fica de fora
        ])
        db.commit()
        texto = canal.montar_resumo(db, s, ONTEM)
    assert texto is not None
    assert "2 novo(s)" in texto and "Emenda Pix parados" in texto and "Carpina-PE" in texto
    assert "Fulano" not in texto and "1 que envolvem pessoas físicas (só no site)" in texto
    assert "Empresa aberta ontem" not in texto
    assert "https://estoudeolho.com.br/fornecedores/99000001000101" in texto


def test_primeira_execucao_so_marca_ponto_de_partida(fabrica: sessionmaker[Session],
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    enviados: list[str] = []
    monkeypatch.setattr(canal, "enviar_telegram", lambda texto, s: enviados.append(texto) or True)
    monkeypatch.setattr(canal, "SessionLocal", fabrica)
    monkeypatch.setattr(canal, "init_db", lambda: None)
    with fabrica() as db:
        db.add(_alerta("pix_parado", 90, "Antigo"))
        db.commit()
    assert canal.main([]) == 0 and enviados == []  # ponto de partida, nada publicado
    with fabrica() as db:
        assert db.query(SyncExecucao).filter_by(fonte=canal.FONTE).count() == 1
        novo = _alerta("pix_parado", 90, "Novo depois do ponto de partida")
        novo.primeira_vez = datetime.now() + timedelta(minutes=1)
        db.add(novo)
        db.commit()
    assert canal.main([]) == 0
    assert len(enviados) == 1 and "Novo depois" in enviados[0] and "Antigo" not in enviados[0]
    assert canal.main(["--apresentacao", "--simular"]) == 0
