"""Configuração central do projeto, lida de variáveis de ambiente e do arquivo `.env`.

Todas as URLs e parâmetros ajustáveis vivem aqui; nenhum outro módulo deve
conter valores hardcoded.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BASE_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = BASE_DIR / "data"

ANO_INICIAL_CEAP: int = 2008


def _anos_padrao() -> list[int]:
    """Anos da 57ª legislatura até o ano corrente."""
    return list(range(2023, date.today().year + 1))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = f"sqlite:///{DATA_DIR / 'gastos.db'}"

    api_base_url: str = "https://dadosabertos.camara.leg.br/api/v2"
    bulk_url_template: str = "https://www.camara.leg.br/cotas/Ano-{ano}.csv.zip"
    id_legislatura: int = 57

    # Portal da Transparência (emendas parlamentares). A chave é pessoal: só no `.env`.
    transparencia_api_url: str = "https://api.portaldatransparencia.gov.br/api-de-dados"
    transparencia_api_key: SecretStr | None = None
    emendas_bulk_url: str = (
        "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO"
    )

    # Base de CNPJ da Receita (compartilhamento público do Nextcloud, acessado via WebDAV).
    cnpj_webdav_url: str = "https://arquivos.receitafederal.gov.br/public.php/dav/files"
    cnpj_webdav_token: str = "gn672Ad4CF8N6TK"
    cnpj_pasta: str = "Dados/Cadastros/CNPJ"
    # Pasta com zips da Receita já baixados por outro sistema no mesmo servidor.
    # Um zip local só é usado se tiver o mesmo tamanho do arquivo do mês na Receita; nunca é apagado.
    cnpj_pasta_local: Path | None = None

    # IBGE: municípios (com região imediata) e estimativa de população.
    ibge_municipios_url: str = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
    ibge_populacao_url: str = (
        "https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/-1/variaveis/9324"
        "?localidades=N6[all]"
    )

    # Pernambuco: verba indenizatória dos deputados estaduais (ALEPE) e contas
    # municipais (TCE-PE) dos municípios listados em TCE_MUNICIPIOS.
    alepe_url: str = "https://www.alepe.pe.gov.br/servicos/transparencia"
    alepe_site_url: str = "https://www.alepe.pe.gov.br"
    alepe_dados_abertos_url: str = "https://dadosabertos.alepe.pe.gov.br/api/v1"
    alepe_req_per_sec: float = Field(default=2.0, gt=0)
    tce_url: str = "https://sistemas.tce.pe.gov.br/DadosAbertos"
    tce_municipios: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["Carpina"])

    # TCE-SP: despesas de todos os municípios paulistas, exceto a capital (que presta contas ao TCM-SP).
    # TCE_SP_MUNICIPIOS: "todos" ou lista de nomes ("Adamantina, Campinas").
    tce_sp_url: str = "https://transparencia.tce.sp.gov.br/api/json"
    tce_sp_municipios: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["todos"])
    tce_sp_req_per_sec: float = Field(default=2.0, gt=0)

    # Transferegov: planos e repasses das Emendas Pix (transferências especiais).
    transferegov_url: str = "https://api.transferegov.gestao.gov.br/transferenciasespeciais"
    transferegov_req_per_sec: float = Field(default=2.0, gt=0)
    # Fontes de recurso do TCE-PE que identificam Emenda Pix (federal e estadual).
    fonte_pix_federal: str = "Transferência Especial da União"
    fonte_pix_estadual: str = "Transferência Especial dos Estados"
    alerta_pix_parado_meses: int = Field(default=6, ge=1)
    alerta_pix_minimo: float = Field(default=100_000.0, ge=0)

    # Senado: cota dos senadores (CEAPS) e cadastro.
    senado_dados_abertos_url: str = "https://legis.senado.leg.br/dadosabertos"
    senado_ceaps_url_template: str = "https://www.senado.gov.br/transparencia/LAI/verba/despesa_ceaps_{ano}.csv"
    senado_legislatura: int = 57

    # Siconfi (Tesouro Nacional): contas anuais (DCA) de todos os municípios.
    siconfi_url: str = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"
    siconfi_req_per_sec: float = Field(default=4.0, gt=0)

    # TSE: candidatos, eleitos e bens declarados.
    tse_cdn_url: str = "https://cdn.tse.jus.br/estatistica/sead/odsele"
    tse_eleicoes: Annotated[list[int], NoDecode] = Field(default_factory=lambda: [2022, 2024])

    # PNCP: contratos de órgãos públicos (Lei 14.133). Esferas: M municipal, E estadual, U/F federal.
    pncp_url: str = "https://pncp.gov.br/api/consulta/v1"
    pncp_data_inicial: date = date(2024, 1, 1)
    pncp_esferas: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["M"])
    pncp_req_per_sec: float = Field(default=1.0, gt=0)

    # Cada coleta recalcula os alertas ao terminar. A rotina diária desliga (ALERTAS_AO_FINAL=false)
    # e recalcula uma vez só no fim, com `python -m civic.alertas`.
    alertas_ao_final: bool = True

    # Sinais de alerta (limiares ajustáveis).
    alerta_empresa_nova_dias: int = Field(default=180, ge=1)
    alerta_mei_limite_anual: float = Field(default=81_000.0, gt=0)
    alerta_concentracao_pct: float = Field(default=0.30, gt=0, le=1)
    alerta_concentracao_minimo: float = Field(default=20_000.0, ge=0)
    alerta_sequencia_min_notas: int = Field(default=6, ge=3)
    alerta_divulgacao_fator: float = Field(default=2.0, gt=1)
    alerta_divulgacao_minimo: float = Field(default=30_000.0, ge=0)
    alerta_padrao_min_notas: int = Field(default=30, ge=5)

    # Avisos no Telegram quando chegar pagamento de emenda nos municípios monitorados.
    telegram_api_url: str = "https://api.telegram.org"
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    municipios_monitorados: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["PE/CARPINA"])
    site_url: str = "http://localhost:5173"

    # Limite de consultas à API por IP e por minuto (0 desliga). A busca, mais pesada, tem limite próprio.
    api_limite_por_minuto: int = Field(default=240, ge=0)
    api_limite_busca_por_minuto: int = Field(default=40, ge=1)

    # Contestações: token para a área administrativa (sem token, a área fica desligada).
    admin_token: SecretStr | None = None
    contestacoes_por_dia: int = Field(default=5, ge=1)

    anos: Annotated[list[int], NoDecode] = Field(default_factory=_anos_padrao)

    req_per_sec: float = Field(default=4.0, gt=0)
    timeout: float = Field(default=30.0, gt=0)
    itens_por_pagina: int = Field(default=100, ge=1, le=100)

    api_url: str = "http://localhost:8000"
    cors_origin_regex: str = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"

    log_level: str = "INFO"

    @field_validator("anos", mode="before")
    @classmethod
    def _parse_anos(cls, valor: Any) -> Any:
        """Aceita `2023,2024`, `[2023, 2024]` ou uma lista Python."""
        if isinstance(valor, str):
            texto = valor.strip().strip("[]")
            return [int(parte) for parte in texto.split(",") if parte.strip()]
        return valor

    @field_validator("tse_eleicoes", mode="before")
    @classmethod
    def _parse_eleicoes(cls, valor: Any) -> Any:
        if isinstance(valor, str):
            return [int(parte) for parte in valor.split(",") if parte.strip()]
        return valor

    @field_validator("pncp_esferas", mode="before")
    @classmethod
    def _parse_esferas(cls, valor: Any) -> Any:
        if isinstance(valor, str):
            return [parte.strip().upper() for parte in valor.split(",") if parte.strip()]
        return valor

    @field_validator("tce_municipios", "tce_sp_municipios", mode="before")
    @classmethod
    def _parse_tce_municipios(cls, valor: Any) -> Any:
        """'Carpina, Paudalho' -> ['Carpina', 'Paudalho']."""
        if isinstance(valor, str):
            return [parte.strip() for parte in valor.split(",") if parte.strip()]
        return valor

    @field_validator("municipios_monitorados", mode="before")
    @classmethod
    def _parse_municipios(cls, valor: Any) -> Any:
        """'PE/Carpina, PE/Paudalho' -> ['PE/CARPINA', 'PE/PAUDALHO']."""
        if isinstance(valor, str):
            valor = [parte for parte in valor.split(",") if parte.strip()]
        return [str(v).strip().upper() for v in valor]

    @field_validator("anos")
    @classmethod
    def _validar_anos(cls, anos: list[int]) -> list[int]:
        ano_atual = date.today().year
        invalidos = [a for a in anos if not ANO_INICIAL_CEAP <= a <= ano_atual]
        if invalidos:
            raise ValueError(
                f"Anos fora do intervalo {ANO_INICIAL_CEAP}-{ano_atual}: {invalidos}"
            )
        if not anos:
            raise ValueError("ANOS não pode ser vazio")
        return sorted(set(anos))

    @field_validator("bulk_url_template")
    @classmethod
    def _validar_template(cls, template: str) -> str:
        if "{ano}" not in template:
            raise ValueError("BULK_URL_TEMPLATE deve conter o marcador {ano}")
        return template

    @field_validator(
        "api_base_url", "api_url", "transparencia_api_url", "cnpj_webdav_url", "site_url",
        "alepe_url", "alepe_site_url", "alepe_dados_abertos_url", "tce_url", "tce_sp_url", "pncp_url",
        "senado_dados_abertos_url", "siconfi_url", "tse_cdn_url", "transferegov_url",
    )
    @classmethod
    def _sem_barra_final(cls, url: str) -> str:
        return url.rstrip("/")

    @property
    def ano_inicial_legislatura(self) -> int:
        """Primeiro ano da legislatura configurada (57ª -> 2023; cada uma dura 4 anos)."""
        return 2023 + 4 * (self.id_legislatura - 57)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    """Instância única de `Settings` (cacheada). Use `get_settings.cache_clear()` em testes."""
    return Settings()
