"""Funções puras de normalização dos dados da Câmara e do Portal da Transparência."""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from collections.abc import Mapping
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)

_NAO_DIGITO = re.compile(r"\D")
_NAO_ALFANUMERICO = re.compile(r"[^A-Z0-9 ]")
_FORMATOS_DATA = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y")
_SEM_INFORMACAO = {"sem informação", "sem informacao", "s/i", "-1"}

TIPOS_DOCUMENTO: dict[int, str] = {
    0: "Nota Fiscal",
    1: "Recibos/Outros",
    2: "Despesa no Exterior",
    3: "Despesa do PARLASUL",
    4: "Nota Fiscal Eletrônica",
}

UF_POR_CODIGO_IBGE: dict[str, str] = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}


# --------------------------------------------------------------------------- básicos


def limpar_texto(valor: str | None) -> str | None:
    """Remove espaços nas pontas e colapsa espaços internos. Vazio vira `None`."""
    if valor is None:
        return None
    texto = " ".join(str(valor).split())
    return texto or None


def limpar_informacao(valor: str | None) -> str | None:
    """Como `limpar_texto`, mas também trata marcadores como "Sem informação" e "S/I"."""
    texto = limpar_texto(valor)
    if texto is None or texto.lower() in _SEM_INFORMACAO:
        return None
    return texto


def limpar_documento(valor: str | None) -> str | None:
    """Mantém só os dígitos de um CPF/CNPJ.

    Retorna `None` se não sobrar nada ou se o total de dígitos não for 11 (CPF)
    nem 14 (CNPJ); neste último caso registra um warning.
    """
    if valor is None:
        return None
    digitos = _NAO_DIGITO.sub("", str(valor))
    if not digitos:
        return None
    if len(digitos) not in (11, 14):
        logger.warning("Documento com %d dígitos descartado: %r", len(digitos), valor)
        return None
    return digitos


def tipo_pessoa(doc: str | None) -> str | None:
    """'PF' para CPF (11 dígitos), 'PJ' para CNPJ (14 dígitos), senão `None`."""
    if doc is None:
        return None
    if len(doc) == 14:
        return "PJ"
    if len(doc) == 11:
        return "PF"
    return None


def parse_data(valor: str | None) -> date | None:
    """Converte 'AAAA-MM-DD', com ou sem hora (também aceita 'DD/MM/AAAA')."""
    texto = limpar_texto(valor)
    if texto is None:
        return None
    for formato in _FORMATOS_DATA:
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(texto).date()
    except ValueError:
        logger.warning("Data inválida ignorada: %r", valor)
        return None


def para_centavos(valor: float | int | str | Decimal | None) -> int:
    """Converte um valor monetário em reais para centavos inteiros.

    Usa `Decimal` com `ROUND_HALF_UP`. Aceita número, string com ponto decimal
    ("1234.56") ou no formato brasileiro ("1.234,56"). `None` e vazio valem 0.
    Floats passam por `str()` para não herdar o erro da representação binária.

    Raises:
        ValueError: se a string não representar um número.
    """
    if valor is None:
        return 0
    if isinstance(valor, bool):
        raise ValueError(f"Valor monetário inválido: {valor!r}")
    if isinstance(valor, Decimal):
        numero = valor
    elif isinstance(valor, (int, float)):
        numero = Decimal(str(valor))
    else:
        texto = str(valor).strip().replace("R$", "").replace(" ", "")
        if not texto:
            return 0
        if "," in texto:
            texto = texto.replace(".", "").replace(",", ".")
        try:
            numero = Decimal(texto)
        except InvalidOperation as exc:
            raise ValueError(f"Valor monetário inválido: {valor!r}") from exc
    if not numero.is_finite():
        raise ValueError(f"Valor monetário inválido: {valor!r}")
    return int((numero * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def para_inteiro(valor: Any) -> int | None:
    """Converte para `int` tolerando strings vazias, '0012' e '12.0'. Inválido vira `None`."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    texto = str(valor).strip()
    if not texto:
        return None
    try:
        return int(Decimal(texto))
    except (InvalidOperation, ValueError):
        return None


def normalizar_nome(valor: str | None) -> str | None:
    """Maiúsculas, sem acentos e sem pontuação: 'Dr. Frederico' -> 'DR FREDERICO'."""
    texto = limpar_texto(valor)
    if texto is None:
        return None
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return limpar_texto(_NAO_ALFANUMERICO.sub(" ", sem_acento.upper()))


def gerar_hash(
    deputado_id: int,
    ano: int,
    mes: int,
    cod_documento: int | None,
    num_documento: str | None,
    cnpj_cpf: str | None,
    valor_documento_centavos: int,
    parcela: int,
) -> str:
    """Chave de idempotência (SHA-256) de uma despesa.

    A API não tem ID estável (`codDocumento` pode vir 0 ou repetido), então a
    identidade é a combinação dos campos abaixo, já limpos, unidos por "|".
    `None` vira string vazia, o que torna o hash igual para a API e o CSV.
    """
    partes = (
        deputado_id,
        ano,
        mes,
        cod_documento,
        num_documento,
        cnpj_cpf,
        valor_documento_centavos,
        parcela,
    )
    chave = "|".join("" if p is None else str(p) for p in partes)
    return hashlib.sha256(chave.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- despesas


def montar_despesa(
    *,
    deputado_id: int,
    ano: int,
    mes: int,
    data_documento: str | None,
    tipo_despesa: str | None,
    tipo_documento: str | None,
    num_documento: str | None,
    cod_documento: Any,
    fornecedor: str | None,
    cnpj_cpf: str | None,
    valor_documento: Any,
    valor_glosa: Any,
    valor_liquido: Any,
    url_documento: str | None,
    parcela: Any,
) -> dict[str, Any]:
    """Aplica toda a limpeza e devolve o dicionário pronto para `Despesa`."""
    doc = limpar_documento(cnpj_cpf)
    num = limpar_texto(num_documento)
    cod = para_inteiro(cod_documento) or None
    num_parcela = para_inteiro(parcela) or 0
    valor_doc = para_centavos(valor_documento)
    return {
        "hash_unico": gerar_hash(deputado_id, ano, mes, cod, num, doc, valor_doc, num_parcela),
        "deputado_id": deputado_id,
        "ano": ano,
        "mes": mes,
        "data_documento": parse_data(data_documento),
        "tipo_despesa": limpar_texto(tipo_despesa) or "NÃO INFORMADO",
        "tipo_documento": limpar_texto(tipo_documento),
        "num_documento": num,
        "cod_documento": cod,
        "fornecedor": limpar_texto(fornecedor),
        "cnpj_cpf": doc,
        "tipo_pessoa": tipo_pessoa(doc),
        "valor_documento_centavos": valor_doc,
        "valor_glosa_centavos": para_centavos(valor_glosa),
        "valor_liquido_centavos": para_centavos(valor_liquido),
        "url_documento": limpar_texto(url_documento),
        "parcela": num_parcela,
    }


def despesa_da_api(item: Mapping[str, Any], deputado_id: int) -> dict[str, Any]:
    """Normaliza um item de `GET /deputados/{id}/despesas`."""
    return montar_despesa(
        deputado_id=deputado_id,
        ano=int(item["ano"]),
        mes=int(item["mes"]),
        data_documento=item.get("dataDocumento"),
        tipo_despesa=item.get("tipoDespesa"),
        tipo_documento=item.get("tipoDocumento"),
        num_documento=item.get("numDocumento"),
        cod_documento=item.get("codDocumento"),
        fornecedor=item.get("nomeFornecedor"),
        cnpj_cpf=item.get("cnpjCpfFornecedor"),
        valor_documento=item.get("valorDocumento"),
        valor_glosa=item.get("valorGlosa"),
        valor_liquido=item.get("valorLiquido"),
        url_documento=item.get("urlDocumento"),
        parcela=item.get("parcela"),
    )


def despesa_do_csv(linha: Mapping[str, Any]) -> dict[str, Any]:
    """Normaliza uma linha do CSV anual `Ano-{ano}.csv` (modo --bulk).

    Raises:
        ValueError: se a linha não tiver `ideCadastro` (ex.: lideranças partidárias).
    """
    deputado_id = para_inteiro(linha.get("ideCadastro"))
    if deputado_id is None:
        raise ValueError("Linha sem ideCadastro")
    cod_tipo = para_inteiro(linha.get("indTipoDocumento"))
    return montar_despesa(
        deputado_id=deputado_id,
        ano=int(linha["numAno"]),
        mes=int(linha["numMes"]),
        data_documento=linha.get("datEmissao"),
        tipo_despesa=linha.get("txtDescricao"),
        tipo_documento=TIPOS_DOCUMENTO.get(cod_tipo) if cod_tipo is not None else None,
        num_documento=linha.get("txtNumero"),
        cod_documento=linha.get("ideDocumento"),
        fornecedor=linha.get("txtFornecedor"),
        cnpj_cpf=linha.get("txtCNPJCPF"),
        valor_documento=linha.get("vlrDocumento"),
        valor_glosa=linha.get("vlrGlosa"),
        valor_liquido=linha.get("vlrLiquido"),
        url_documento=linha.get("urlDocumento"),
        parcela=linha.get("numParcela"),
    )


# --------------------------------------------------------------------------- emendas


def _codigo_ibge(valor: str | None) -> str | None:
    digitos = _NAO_DIGITO.sub("", valor or "")
    return digitos if len(digitos) == 7 else None


def ano_do_codigo_emenda(codigo: str | None) -> int | None:
    """O código da emenda começa pelo ano (ex.: '202440340007' -> 2024)."""
    if codigo and len(codigo) >= 4 and codigo[:4].isdigit():
        return int(codigo[:4])
    return None


def emenda_do_csv(linha: Mapping[str, Any]) -> dict[str, Any]:
    """Normaliza uma linha de `EmendasParlamentares.csv`."""
    ibge = _codigo_ibge(linha.get("Código Município IBGE"))
    nome_autor = limpar_informacao(linha.get("Nome do Autor da Emenda"))
    return {
        "codigo_emenda": limpar_informacao(linha.get("Código da Emenda")),
        "ano": int(linha["Ano da Emenda"]),
        "tipo_emenda": limpar_informacao(linha.get("Tipo de Emenda")),
        "codigo_autor": limpar_informacao(linha.get("Código do Autor da Emenda")),
        "nome_autor": nome_autor,
        "nome_autor_normalizado": normalizar_nome(nome_autor),
        "numero_emenda": limpar_informacao(linha.get("Número da emenda")),
        "localidade": limpar_informacao(linha.get("Localidade de aplicação do recurso")),
        "codigo_municipio_ibge": ibge,
        "municipio": limpar_informacao(linha.get("Município")) if ibge else None,
        "sigla_uf": UF_POR_CODIGO_IBGE.get(ibge[:2]) if ibge else None,
        "funcao": limpar_informacao(linha.get("Nome Função")),
        "subfuncao": limpar_informacao(linha.get("Nome Subfunção")),
        "acao": limpar_informacao(linha.get("Nome Ação")),
        "valor_empenhado_centavos": para_centavos(linha.get("Valor Empenhado")),
        "valor_liquidado_centavos": para_centavos(linha.get("Valor Liquidado")),
        "valor_pago_centavos": para_centavos(linha.get("Valor Pago")),
        "valor_rp_inscrito_centavos": para_centavos(linha.get("Valor Restos A Pagar Inscritos")),
        "valor_rp_cancelado_centavos": para_centavos(linha.get("Valor Restos A Pagar Cancelados")),
        "valor_rp_pago_centavos": para_centavos(linha.get("Valor Restos A Pagar Pagos")),
    }


def pagamento_emenda_do_csv(linha: Mapping[str, Any]) -> dict[str, Any]:
    """Normaliza uma linha de `EmendasParlamentares_PorFavorecido.csv`.

    O campo 'Ano/Mês' ('202609') é o mês do pagamento, não o ano da emenda.
    """
    ano_mes = _NAO_DIGITO.sub("", linha.get("Ano/Mês") or "")
    if len(ano_mes) != 6:
        raise ValueError(f"Ano/Mês inválido: {linha.get('Ano/Mês')!r}")
    codigo = limpar_informacao(linha.get("Código da Emenda"))
    nome_autor = limpar_informacao(linha.get("Nome do Autor da Emenda"))
    municipio = limpar_informacao(linha.get("Município Favorecido"))
    uf = limpar_informacao(linha.get("UF Favorecido"))
    return {
        "codigo_emenda": codigo,
        "ano_emenda": ano_do_codigo_emenda(codigo),
        "ano": int(ano_mes[:4]),
        "mes": int(ano_mes[4:]),
        "tipo_emenda": limpar_informacao(linha.get("Tipo de Emenda")),
        "codigo_autor": limpar_informacao(linha.get("Código do Autor da Emenda")),
        "nome_autor": nome_autor,
        "nome_autor_normalizado": normalizar_nome(nome_autor),
        "numero_emenda": limpar_informacao(linha.get("Número da emenda")),
        "codigo_favorecido": limpar_informacao(linha.get("Código do Favorecido")),
        "favorecido": limpar_informacao(linha.get("Favorecido")),
        "natureza_juridica": limpar_informacao(linha.get("Natureza Jurídica")),
        "tipo_favorecido": limpar_informacao(linha.get("Tipo Favorecido")),
        "sigla_uf": uf.upper() if uf and len(uf) == 2 else None,
        "municipio": municipio,
        "municipio_normalizado": normalizar_nome(municipio),
        "valor_recebido_centavos": para_centavos(linha.get("Valor Recebido")),
    }


def convenio_do_csv(linha: Mapping[str, Any]) -> dict[str, Any]:
    """Normaliza uma linha de `EmendasParlamentares_Convenios.csv`."""
    return {
        "codigo_emenda": limpar_informacao(linha.get("Código da Emenda")),
        "localidade": limpar_informacao(linha.get("Localidade do gasto")),
        "funcao": limpar_informacao(linha.get("Nome Função")),
        "tipo_emenda": limpar_informacao(linha.get("Tipo de Emenda")),
        "data_publicacao": parse_data(linha.get("Data Publicação Convênio")),
        "convenente": limpar_informacao(linha.get("Convenente")),
        "objeto": limpar_informacao(linha.get("Objeto Convênio")),
        "numero_convenio": limpar_informacao(linha.get("Número Convênio")),
        "valor_centavos": para_centavos(linha.get("Valor Convênio")),
    }


# --------------------------------------------------------------------------- Receita (CNPJ)


def parse_data_receita(valor: str | None) -> date | None:
    """'20050518' -> date(2005, 5, 18). Zeros e vazio viram `None`."""
    digitos = _NAO_DIGITO.sub("", valor or "")
    if len(digitos) != 8 or digitos == "00000000":
        return None
    try:
        return datetime.strptime(digitos, "%Y%m%d").date()
    except ValueError:
        return None


# --------------------------------------------------------------------------- Pernambuco


def verba_da_alepe(
    nota: Mapping[str, Any], docid: str, deputado_id: int, ano: int, mes: int, rubricas: Mapping[int, str]
) -> dict[str, Any]:
    """Normaliza uma nota de `verbaindenizatorianotas.php` (valores vêm em reais)."""
    doc = limpar_documento(nota.get("cnpj"))
    rubrica = para_inteiro(nota.get("rubrica"))
    return {
        "docid": str(docid),
        "deputado_estadual_id": deputado_id,
        "ano": ano,
        "mes": mes,
        "rubrica": rubrica,
        "rubrica_nome": rubricas.get(rubrica) if rubrica is not None else None,
        "sequencial": para_inteiro(nota.get("sequencial")),
        "data": parse_data(nota.get("data")),
        "cnpj_cpf": doc,
        "tipo_pessoa": tipo_pessoa(doc),
        "fornecedor": limpar_texto(nota.get("empresa")),
        "valor_centavos": para_centavos(nota.get("valor")),
    }


def _documento_tce(valor: str | None) -> tuple[str | None, str | None]:
    """CPF/CNPJ do TCE-PE: CNPJ vem completo; CPF vem mascarado ('***.***.404-92')."""
    texto = limpar_texto(valor)
    if texto is None:
        return None, None
    digitos = _NAO_DIGITO.sub("", texto)
    if len(digitos) == 14 and set(digitos) != {"0"}:
        return digitos, "PJ"
    if "*" in texto:
        return texto, "PF"
    if len(digitos) == 11:
        return f"***.{digitos[3:6]}.{digitos[6:9]}-**", "PF"
    return None, None


def despesa_municipal_do_tce(item: Mapping[str, Any]) -> dict[str, Any]:
    """Normaliza um empenho de `DespesasMunicipais` do TCE-PE."""
    ug = int(item["ID_UNIDADE_GESTORA"])
    ano = int(item["ANOREFERENCIA"])
    doc, pessoa = _documento_tce(item.get("CPF_CNPJ"))
    fornecedor = limpar_texto(item.get("FORNECEDOR"))
    historico = limpar_texto(item.get("HISTORICO"))
    chave = "|".join(
        str(limpar_texto(item.get(c)) or "") for c in ("ID_EMPENHO", "ANOREFERENCIA", "NUMEROEMPENHO", "ID_UNIDADE_GESTORA")
    )
    return {
        "chave": chave,
        "unidade_gestora_id": ug,
        "ano": ano,
        "mes": para_inteiro(item.get("MESREFERENCIA")),
        "data_empenho": parse_data((item.get("DATAEMPENHO") or "")[:10]),
        "numero_empenho": limpar_texto(item.get("NUMEROEMPENHO")),
        "fornecedor": fornecedor,
        "fornecedor_normalizado": normalizar_nome(fornecedor),
        "cpf_cnpj": doc,
        "tipo_pessoa": pessoa,
        "elemento_despesa": limpar_texto(item.get("ELEMENTODESPESA")),
        "funcao": limpar_texto(item.get("FUNCAO")),
        "acao": limpar_texto(item.get("ACAO")),
        "modalidade": limpar_texto(item.get("MODALIDADE")),
        "historico": historico,
        "historico_normalizado": normalizar_nome(historico),
        "id_empenho": limpar_texto(item.get("ID_EMPENHO")),
        "fonte_recurso": limpar_texto(item.get("FONTERECURSO")),
        "categoria_economica": limpar_texto(item.get("CATEGORIA")),
        "valor_empenhado_centavos": para_centavos(item.get("VALOREMPENHADO")),
        "valor_liquidado_centavos": para_centavos(item.get("VALORLIQUIDADO")),
        "valor_pago_centavos": para_centavos(item.get("VALORPAGO")),
    }


def contrato_do_tce(item: Mapping[str, Any], ug: int) -> dict[str, Any]:
    """Normaliza um contrato de `Contratos` do TCE-PE (LICON).

    Usa só `CPF_CNPJ` (CNPJ completo; CPF já mascarado pelo tribunal). Os campos
    `NumeroDocumento`/`NumeroDocumentoAjustado` trazem o CPF completo e são ignorados.
    """
    doc, pessoa = _documento_tce(item.get("CPF_CNPJ"))
    vigencia = [parse_data(p.strip()) for p in (limpar_texto(item.get("Vigencia")) or "").split(" a ")]
    objeto = limpar_texto(item.get("Objeto"))
    fornecedor = limpar_texto(item.get("RazaoSocial"))
    return {
        "codigo": str(limpar_texto(item.get("CodigoContrato")) or ""),
        "unidade_gestora_id": ug,
        "ano": int(item["AnoContrato"]),
        "numero": limpar_texto(item.get("NumeroContrato")),
        "tipo_processo": limpar_texto(item.get("TipoProcesso")),
        "numero_processo": limpar_texto(item.get("NumeroProcesso")),
        "ano_processo": para_inteiro(item.get("AnoProcesso")),
        "objeto": objeto,
        "objeto_normalizado": normalizar_nome(objeto),
        "fornecedor": fornecedor,
        "fornecedor_normalizado": normalizar_nome(fornecedor),
        "cpf_cnpj": doc,
        "tipo_pessoa": pessoa,
        "valor_centavos": para_centavos(item.get("Valor")),
        "vigencia_inicio": vigencia[0] if vigencia else None,
        "vigencia_fim": vigencia[1] if len(vigencia) > 1 else None,
        "situacao": limpar_texto(item.get("Situacao")),
        "estagio": limpar_texto(item.get("Estagio")),
        "url_documento": limpar_texto(item.get("LinkArquivo")),
    }


def pagamento_do_tce(item: Mapping[str, Any]) -> dict[str, Any]:
    """Normaliza um pagamento de `EmpenhoPagamento` do TCE-PE (sem os dados bancários)."""
    return {
        "unidade_gestora_id": int(item["ID_UNIDADE_GESTORA"]),
        "ano": int(item["ANOREFERENCIA"]),
        "id_empenho": str(limpar_texto(item.get("IDEMPENHO")) or ""),
        "data": parse_data((item.get("DATA") or "")[:10]),
        "tipo": limpar_texto(item.get("TIPO")),
        "valor_centavos": para_centavos(item.get("VALOR")),
    }


def cpf_meio(valor: str | None) -> str | None:
    """6 dígitos centrais de um CPF mascarado ('***.063.774-**' ou '***063774**') ou completo."""
    digitos = _NAO_DIGITO.sub("", valor or "")
    if len(digitos) == 11:
        return digitos[3:9]
    return digitos if len(digitos) == 6 else None


def servidor_do_tce(item: Mapping[str, Any]) -> dict[str, Any]:
    """Normaliza um vínculo de `ListaServidores` do TCE-PE."""
    nome = limpar_texto(item.get("NomeServidor")) or ""
    return {
        "unidade_gestora_id": int(item["UnidadeJurisdicionadaTCE"]),
        "nome": nome,
        "nome_normalizado": normalizar_nome(nome) or "",
        "cargo": limpar_texto(item.get("NomeCargo")),
        "vinculo": limpar_texto(item.get("NomeTipoVinculo")),
        "data_admissao": parse_data(item.get("DataAdmissao")),
        "matricula": limpar_texto(item.get("Matricula")),
        "hash_cpf": limpar_texto(item.get("HashCPFPessoa")),
        "cpf_meio": cpf_meio(item.get("CPFServidor")),
        "ano_remessa": para_inteiro(item.get("AnoRemessa")),
        "mes_remessa": para_inteiro(item.get("MesRemessa")),
    }



# --------------------------------------------------------------------------- PNCP


def contrato_do_pncp(item: Mapping[str, Any]) -> dict[str, Any]:
    """Normaliza um contrato de `/v1/contratos` do PNCP. CPF de pessoa física sai mascarado."""
    orgao = item.get("orgaoEntidade") or {}
    unidade = item.get("unidadeOrgao") or {}
    tipo = limpar_texto(item.get("tipoPessoa"))
    ni = _NAO_DIGITO.sub("", item.get("niFornecedor") or "")
    if tipo == "PF" and len(ni) == 11:
        ni = f"***.{ni[3:6]}.{ni[6:9]}-**"
    elif not ni:
        ni = None
    objeto = limpar_texto(item.get("objetoContrato"))
    assinatura = parse_data(item.get("dataAssinatura"))
    ibge = _NAO_DIGITO.sub("", str(unidade.get("codigoIbge") or ""))
    return {
        "numero_controle": item["numeroControlePNCP"],
        "orgao_cnpj": limpar_documento(orgao.get("cnpj")),
        "orgao_nome": limpar_texto(orgao.get("razaoSocial")),
        "esfera": limpar_texto(orgao.get("esferaId")),
        "poder": limpar_texto(orgao.get("poderId")),
        "sigla_uf": limpar_texto(unidade.get("ufSigla")),
        "municipio_ibge": ibge if len(ibge) == 7 else None,
        "municipio_nome": limpar_texto(unidade.get("municipioNome")),
        "unidade_nome": limpar_texto(unidade.get("nomeUnidade")),
        "fornecedor_ni": ni,
        "fornecedor_nome": limpar_texto(item.get("nomeRazaoSocialFornecedor")),
        "tipo_pessoa": tipo if tipo in ("PJ", "PF") else tipo,
        "objeto": objeto,
        "objeto_normalizado": normalizar_nome(objeto),
        "tipo_contrato": limpar_texto((item.get("tipoContrato") or {}).get("nome")),
        "categoria": limpar_texto((item.get("categoriaProcesso") or {}).get("nome")),
        "valor_inicial_centavos": para_centavos(item.get("valorInicial")),
        "valor_global_centavos": para_centavos(item.get("valorGlobal")),
        "data_assinatura": assinatura,
        "vigencia_inicio": parse_data(item.get("dataVigenciaInicio")),
        "vigencia_fim": parse_data(item.get("dataVigenciaFim")),
        "data_publicacao": parse_data((item.get("dataPublicacaoPncp") or "")[:10]),
        "ano": assinatura.year if assinatura else para_inteiro(item.get("anoContrato")),
    }



# --------------------------------------------------------------------------- Senado


def despesa_senado_do_csv(linha: Mapping[str, Any], senadores: Any) -> dict[str, Any]:
    """Normaliza uma linha do CSV anual da CEAPS. CPF de pessoa física sai mascarado."""
    nome = limpar_texto(linha.get("SENADOR")) or ""
    digitos = _NAO_DIGITO.sub("", linha.get("CNPJ_CPF") or "")
    if len(digitos) == 14:
        doc, pessoa = digitos, "PJ"
    elif len(digitos) == 11:
        doc, pessoa = f"***.{digitos[3:6]}.{digitos[6:9]}-**", "PF"
    else:
        doc, pessoa = None, None
    return {
        "senador_id": senadores.get(normalizar_nome(nome) or ""),
        "nome_senador": nome,
        "ano": int(linha["ANO"]),
        "mes": int(linha["MES"]),
        "tipo_despesa": limpar_texto(linha.get("TIPO_DESPESA")),
        "cnpj_cpf": doc,
        "tipo_pessoa": pessoa,
        "fornecedor": limpar_texto(linha.get("FORNECEDOR")),
        "documento": limpar_texto(linha.get("DOCUMENTO")),
        "data": parse_data(linha.get("DATA")),
        "detalhamento": limpar_texto(linha.get("DETALHAMENTO")),
        "cod_documento": limpar_texto(linha.get("COD_DOCUMENTO")),
        "valor_centavos": para_centavos(linha.get("VALOR_REEMBOLSADO")),
    }



# --------------------------------------------------------------------------- TSE


def _tse(valor: Any) -> str | None:
    """O TSE usa '#NULO', '#NE' e '-1'/'-3'/'-4' para "sem informação"."""
    texto = limpar_texto(valor)
    if texto is None or texto.startswith("#") or texto in ("-1", "-3", "-4"):
        return None
    return texto


def candidato_do_tse(linha: Mapping[str, Any], municipios: Any) -> dict[str, Any]:
    """Normaliza uma linha de `consulta_cand_{ano}_{UF}.csv`. `municipios`: (UF, nome normalizado) -> IBGE."""
    nome = _tse(linha.get("NM_CANDIDATO")) or ""
    uf = _tse(linha.get("SG_UF"))
    nome_ue = _tse(linha.get("NM_UE"))
    resultado = _tse(linha.get("DS_SIT_TOT_TURNO"))
    municipal = (linha.get("TP_ABRANGENCIA") or "").strip().upper() == "MUNICIPAL"
    return {
        "sq_candidato": str(linha["SQ_CANDIDATO"]).strip(),
        "ano": int(linha["ANO_ELEICAO"]),
        "cargo": (_tse(linha.get("DS_CARGO")) or "").upper(),
        "sigla_uf": uf,
        "codigo_ue": _tse(linha.get("SG_UE")),
        "nome_ue": nome_ue,
        "municipio_ibge": municipios.get((uf or "", normalizar_nome(nome_ue) or "")) if municipal else None,
        "nome": nome,
        "nome_normalizado": normalizar_nome(nome) or "",
        "nome_urna": _tse(linha.get("NM_URNA_CANDIDATO")),
        "numero": _tse(linha.get("NR_CANDIDATO")),
        "sigla_partido": _tse(linha.get("SG_PARTIDO")),
        "situacao_candidatura": _tse(linha.get("DS_SITUACAO_CANDIDATURA")),
        "resultado": resultado,
        "eleito": bool(resultado and resultado.upper().startswith("ELEITO")),
        "ocupacao": _tse(linha.get("DS_OCUPACAO")),
        "genero": _tse(linha.get("DS_GENERO")),
        "instrucao": _tse(linha.get("DS_GRAU_INSTRUCAO")),
        "bens_centavos": 0,
    }



def doacao_do_tse(linha: Mapping[str, Any], ano: int) -> dict[str, Any]:
    """Doação de pessoa física (receitas do candidato). Guarda só os 6 dígitos centrais do CPF."""
    nome = _tse(linha.get("NM_DOADOR_RFB")) or _tse(linha.get("NM_DOADOR")) or ""
    return {
        "ano": ano,
        "sq_candidato": str(linha["SQ_CANDIDATO"]).strip(),
        "doador_nome": nome,
        "doador_nome_normalizado": normalizar_nome(nome) or "",
        "doador_cpf_meio": cpf_meio(_tse(linha.get("NR_CPF_CNPJ_DOADOR"))),
        "valor_centavos": para_centavos(linha.get("VR_RECEITA")),
    }
