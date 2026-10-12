# Estou de Olho — auditoria cidadã do dinheiro público

[![CI](https://github.com/sposito88/estou-de-olho/actions/workflows/ci.yml/badge.svg)](https://github.com/sposito88/estou-de-olho/actions/workflows/ci.yml)
Licença: [AGPL-3.0](LICENSE) · [Como contribuir](CONTRIBUTING.md) · [Código de conduta](CODE_OF_CONDUCT.md) · [Segurança](SECURITY.md)

> **Rodar em 2 minutos, sem baixar nada:** `make instalar && make dev`, depois `make api` e `make web`
> (dados fictícios; detalhes em [CONTRIBUTING.md](CONTRIBUTING.md)).

Coleta, guarda e mostra **quanto cada deputado federal gastou da Cota Parlamentar (CEAP)**, com nota fiscal, e **quanto de emenda parlamentar chegou a cada município**, com Carpina–PE como cidade padrão. Por cima disso:

- **Sinais de alerta** automáticos: empresa aberta pouco antes de receber, fornecedor que vive de um só deputado, notas em sequência, CNPJ baixado emitindo nota, MEI acima do limite, divulgação em ano eleitoral e padrões atípicos.
- **Ficha de cada fornecedor**, com o cadastro da Receita (abertura, situação, MEI, cidade da sede).
- **Página da cidade** com valor por habitante, emenda Pix, comparação com a região (IBGE), o que foi financiado e quanto da cota foi gasto em empresas locais.
- **Compartilhamento**: cartão em imagem para redes sociais, link de WhatsApp, feed RSS por cidade e aviso no Telegram quando chega pagamento novo.
- **Pernambuco**: verba indenizatória de cada deputado estadual (ALEPE), nota por nota; contas da prefeitura e da câmara de vereadores (TCE-PE), com o que cada vereador recebeu em seu nome e o pessoal nomeado no mandato.
- **Emenda Pix** (transferência especial), em todo o Brasil: o que chegou a cada município, o plano de ação declarado no Transferegov (objeto, metas, custeio × investimento, relatório de gestão) e, onde o tribunal de contas publica a fonte de recurso (TCE-PE), o que a prefeitura informou como gasto com esse dinheiro.
- **Pessoal da prefeitura** (TCE-PE): lista de vínculos (nome, cargo, vínculo, admissão), custo da folha mês a mês pela data do pagamento, pessoas físicas pagas por serviço ou aluguel e nomeados no mandato que doaram para campanhas de 2024 no município.
- **Contas do ano corrente**: relatório bimestral (RREO) do Siconfi, com orçamento, empenhado e liquidado por área até o último bimestre.
- **Rio Grande do Sul**: despesas de prefeituras, câmaras e órgãos dos 497 municípios (TCE-RS), com histórico, função, elemento e fonte de recurso, somadas por órgão, credor e elemento em cada ano.
- **Paraíba**: quadro de pessoal dos 223 municípios com o **salário de cada servidor** (TCE-PB), folha mês a mês por tipo de vínculo e subsídio dos vereadores.
- **São Paulo**: despesas da prefeitura, da câmara e da administração indireta dos 644 municípios do TCE-SP (todos menos a capital), somadas por órgão e credor em cada ano.
- **Brasil (Fase 1)**: contratos de todas as prefeituras e câmaras (PNCP), contas anuais de todos os municípios (Siconfi), eleitos de 2022 e 2024 com bens declarados (TSE), cota dos senadores (CEAPS) e quadro de sócios dos fornecedores (Receita), com alertas de servidor ou eleito sócio de fornecedor.

- **Fontes:** API de Dados Abertos e CSVs anuais da Câmara (cota); download em lote do Portal da Transparência (emendas, pagamentos e convênios); base aberta de CNPJ da Receita Federal; APIs de municípios e população do IBGE; portal de transparência da ALEPE; API de Dados Abertos do TCE-PE; API de transparência do TCE-SP.
- **Escopo:** 57ª legislatura, de 2023 em diante (configurável).
- **Stack:** Python 3.10+, SQLite + SQLAlchemy 2.0, FastAPI + Pydantic v2 e front em React + Tailwind (pasta `web/`).

```text
gastos-camara/
├── civic/            # backend Python
│   ├── config.py     # Settings (.env)
│   ├── database.py   # engine, SessionLocal, get_db, init_db
│   ├── models.py     # Deputado, Despesa, Emenda*, Municipio, Fornecedor, Alerta, Sync*
│   ├── cleaning.py   # normalização pura (testada)
│   ├── scraper.py    # coleta diária (cota + emendas + IBGE + alertas + avisos) e CLI
│   ├── cnpj.py       # base de CNPJ da Receita (mensal) e CLI
│   ├── pernambuco.py # verba da ALEPE e contas municipais do TCE-PE, e CLI
│   ├── tce_sp.py     # despesas municipais do TCE-SP (órgão × credor × ano), e CLI
│   ├── tce_pb.py     # pessoal com salário dos municípios da Paraíba (TCE-PB), e CLI
│   ├── tce_rs.py     # despesas dos municípios gaúchos (TCE-RS), e CLI
│   ├── transferegov.py # Emendas Pix: planos, metas e repasses (Transferegov), e CLI
│   ├── pncp.py       # contratos públicos do PNCP (todos os municípios), e CLI
│   ├── siconfi.py    # contas anuais (DCA) de todos os municípios, e CLI
│   ├── tse.py        # candidatos, eleitos e bens (TSE), e CLI
│   ├── senado.py     # cota dos senadores (CEAPS), e CLI
│   ├── ibge.py       # municípios, região imediata e população
│   ├── alertas.py    # regras dos sinais de alerta
│   ├── avisos.py     # avisos no Telegram
│   ├── queries.py    # consultas agregadas
│   ├── schemas.py    # respostas Pydantic (centavos -> Decimal)
│   └── api.py        # rotas FastAPI
├── web/              # front React + Vite + Tailwind (consome só a API)
├── deploy/           # Caddyfile e rotina diária (cron)
├── design-system/    # identidade visual (gerada com ui-ux-pro-max)
├── tests/            # pytest
└── data/             # SQLite e downloads (fora do git)
```

## Setup

Requisitos: Python 3.10+ e Node 20+.

```bash
cd gastos-camara

# Backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # ajuste se quiser (anos, rate limit, caminho do banco)

# Front
cd web
npm install
cp .env.example .env          # VITE_API_URL e cidade padrão
cd ..
```

## Ordem de execução

```bash
# 1. Coleta (escolha um modo)
python -m civic.scraper --bulk          # recomendado: CSVs anuais, ~8 min
python -m civic.scraper                 # alternativa: API da Câmara, ~1 h

# 1b. Pernambuco: verba dos deputados estaduais e contas de TCE_MUNICIPIOS
python -m civic.pernambuco              # ~45 min na primeira vez; depois ~5 min
python -m civic.tce_sp                  # São Paulo: ~12 h na 1ª vez (3 anos); depois ~2 h por semana

# 1c. Fontes nacionais
python -m civic.senado                  # cota dos senadores (~1 min)
python -m civic.tse                     # candidatos e bens de 2022 e 2024 (~2 min)
python -m civic.siconfi                 # contas de todos os municípios (~2 h por ano na 1ª vez)
python -m civic.pncp                    # contratos municipais desde 2024 (~1 dia na 1ª vez; depois minutos)
python -m civic.siconfi --rreo          # ano corrente pelo RREO bimestral (~30 min na 1ª vez por bimestre)
python -m civic.transferegov            # Emendas Pix do Brasil todo (~8 min)
python -m civic.tce_pb                  # pessoal com salário da Paraíba (~3 min)
python -m civic.tce_rs                  # despesas do Rio Grande do Sul (~1,4 GB por ano; ~15 min por ano)

# 1d. Base de CNPJ e sócios da Receita (mensal; ~50 min e ~8 GB de download na primeira vez)
python -m civic.cnpj

# 2. API (http://localhost:8000/docs)
uvicorn civic.api:app --reload

# 3. Front (http://localhost:5173)
cd web && npm run dev

# Testes
pytest
cd web && npm run typecheck
```

As duas coletas gravam no mesmo banco e geram o mesmo hash por despesa. Dá para alternar entre elas sem duplicar nada.

### Opções da coleta

| Opção | Efeito |
|---|---|
| `--ano 2025 2026` | Coleta só esses anos (padrão: `ANOS` do `.env`). |
| `--bulk` | Usa `Ano-{ano}.csv.zip` da Câmara em vez da API. |
| `--so-deputados` | Só sincroniza a lista de deputados. |
| `--forcar` | Ignora checkpoints e downloads em cache. |
| `--sem-emendas` / `--so-emendas` | Pula ou faz só a carga das emendas. |
| `--sem-progresso` | Desliga a barra de progresso (por padrão ela só aparece em terminal). |

O processo sai com código `0` sem falhas e `1` se algum deputado/ano falhou. A falha de um item não interrompe a coleta; todas as falhas aparecem no resumo final.

Ao fim de cada coleta, o coletor também atualiza os municípios do IBGE (uma vez por mês), recalcula todos os alertas e, se `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` estiverem no `.env`, avisa no Telegram os pagamentos de emenda novos nos municípios de `MUNICIPIOS_MONITORADOS`.

`python -m civic.pernambuco` aceita `--ano`, `--so-alepe`, `--so-tce` e `--forcar`. Na ALEPE, consulta deputado por deputado a no máximo `ALEPE_REQ_PER_SEC` (padrão 2/s), pula meses já coletados e relê sempre os 3 meses mais recentes. No TCE-PE, baixa todos os empenhos de cada município de `TCE_MUNICIPIOS` (uma chamada por ano) e a lista de pessoal de cada órgão; o consórcio intermunicipal fica de fora.

`python -m civic.tce_sp` aceita `--municipio`, `--ano`, `--forcar` e `--sem-alertas`. Baixa mês a mês os eventos de cada empenho (empenhado, anulação, liquidado, pago) dos municípios de `TCE_SP_MUNICIPIOS` (padrão `todos`) a `TCE_SP_REQ_PER_SEC` (padrão 2/s) e guarda uma linha por órgão × credor × ano, com as somas e a quantidade de empenhos. Anos fechados ganham checkpoint; o ano corrente (e o anterior, até junho) é sempre relido. A rotina roda aos sábados. Os órgãos do TCE-SP ganham ids a partir de 10.000.000 em `unidades_gestoras` (com `fonte = 'TCE-SP'`).

`python -m civic.cnpj` aceita `--referencia 2026-09` (mês da base; padrão: o mais recente), `--forcar` e `--manter-arquivos`. Ele baixa com retomada, guarda só os CNPJs que aparecem nas despesas, apaga os zips e recalcula os alertas. Se a base do mês já foi carregada, sai sem fazer nada, então pode rodar todo dia.

### Tempo estimado de coleta

Medido em 07/10/2026, com 4 anos (2023–2026) e 648 deputados:

| Etapa | `--bulk` | API |
|---|---|---|
| Lista de deputados | ~1 min | ~1 min |
| Despesas (~770 mil) | ~6 min (4 downloads de 4–8 MB) | ~50–60 min (≈2.600 pares deputado/ano, ~1,2 s cada a 4 req/s) |
| Emendas (download de 32 MB) | ~1 min | ~1 min |
| **Total** | **~8 min** | **~1 h** |
| Base de CNPJ (mensal, ~7 GB) | ~50 min | ~50 min |

Nas execuções seguintes, os anos já coletados são pulados pelo checkpoint e só o ano corrente é recoletado: cerca de 2 min em `--bulk` e cerca de 15 min pela API. A coleta pela API pode ser interrompida (Ctrl+C) e retomada.

## Deploy com Docker (HML)

Uma imagem Python serve a API e roda o coletor. Um Caddy serve o site e repassa `/api`, `/health` e `/docs` para a API, então tudo fica na mesma origem e não depende de CORS. O banco SQLite fica em `./data`, montado como volume.

```bash
cp .env.example .env                 # TRANSPARENCIA_API_KEY pode ficar vazia
docker compose --profile coleta build
docker compose run --rm coleta       # coleta --bulk (~8 min na primeira vez)
docker compose up -d                 # site em http://<host>:8088 (mude com PORTA_WEB)
```

A API lê o banco em modo WAL e continua respondendo durante a coleta. Para publicar uma nova versão do código: `docker compose --profile coleta build && docker compose up -d`.

A rotina diária `deploy/rotina.sh` roda a coleta e a base de CNPJ e faz backup do banco em `data/backups/` (mantém 7 dias), com log em `data/logs/`. Para agendar às 3h30:

```bash
(crontab -l 2>/dev/null; echo "30 3 * * * $PWD/deploy/rotina.sh") | crontab -
```

Para reaproveitar zips da Receita que já existem no servidor (evita baixar ~8 GB), use `deploy/docker-compose.receita-local.yml`: no `.env`, `COMPOSE_FILE=docker-compose.yml:deploy/docker-compose.receita-local.yml` e `RECEITA_PASTA_LOCAL=/caminho/dos/zips`. Quando o zip local tem o mesmo tamanho do arquivo do mês na Receita, a base de CNPJ não é baixada de novo.

## API

Documentação interativa em `/docs`. Valores monetários saem como string decimal com 2 casas (`"1234.56"`) para não perder precisão. Listas paginadas usam o formato `{ "total": int, "itens": [...] }`.

| Rota | Parâmetros | Retorno |
|---|---|---|
| `GET /api/deputados` | `uf`, `partido` | lista de deputados |
| `GET /api/filtros` | — | UFs, partidos, anos com despesas e anos com emendas |
| `GET /api/gastos/resumo` | `ano`, `uf`, `partido` | total líquido, nº de deputados e nº de despesas |
| `GET /api/gastos/ranking` | `ano`, `uf`, `partido`, `limit` (1–100, padrão 10), `ordem` (`total` ou `relativo`) | deputado, total líquido, qtd. de despesas e índice em relação à média do estado |
| `GET /api/gastos/por-tipo` | `ano`, `uf`, `partido` | total por tipo de despesa |
| `GET /api/deputados/{id}/gastos` | `ano`, `limit`, `offset` | deputado, total, série mensal e despesas paginadas |
| `GET /api/despesas` | `ano`, `uf`, `partido`, `limit`, `offset` | últimas despesas (data desc, depois ano/mês desc) |
| `GET /api/deputados/{id}/emendas` | `ano` | empenhado, pago, áreas e municípios de destino |
| `GET /api/municipios` | `busca`, `uf`, `ano`, `limit` | municípios que receberam emendas (busca sem acento) |
| `GET /api/municipios/{uf}/{municipio}/emendas` | `ano` | total recebido, por habitante, emenda Pix, por autor, favorecido, área, ação e mês |
| `GET /api/municipios/{uf}/{municipio}/pagamentos` | `ano`, `limit`, `offset` | pagamentos paginados, com ação e objeto do convênio |
| `GET /api/municipios/{uf}/{municipio}/comparacao` | `ano` | emendas por habitante nas cidades da mesma região imediata |
| `GET /api/municipios/{uf}/{municipio}/cota` | `ano` | cota parlamentar gasta em empresas com sede na cidade |
| `GET /api/municipios/{uf}/{municipio}/feed.xml` | — | feed Atom dos últimos pagamentos |
| `GET /api/alertas` | `tipo`, `gravidade`, `esfera`, `ano`, `uf`, `partido`, `deputado_id`, `deputado_estadual_id`, `orgao_id`, `cnpj`, `limit`, `offset` | sinais de alerta paginados |
| `GET /api/alertas/resumo` | `ano`, `uf`, `partido`, `esfera` | contagem por tipo, gravidade e esfera |
| `GET /api/alertas/tipos` | — | nome de cada tipo de alerta |
| `GET /api/fornecedores/{cnpj}/documentos` | `limit`, `offset` | cada nota, empenho ou contrato com o fornecedor, de todas as fontes, com link quando a fonte publica |
| `GET /api/municipios/{uf}/{municipio}/contratos` | `ano` | contratos do PNCP: total, órgãos, categorias e maiores contratados |
| `GET /api/municipios/{uf}/{municipio}/contratos/lista` | `ano`, `busca`, `orgao_cnpj`, `limit`, `offset` | contratos paginados com link para o PNCP |
| `GET /api/municipios/{uf}/{municipio}/contas` | `ano` | despesa por área (Siconfi), por habitante, vs. mediana da UF e do Brasil |
| `GET /api/municipios/{uf}/{municipio}/eleitos` | `ano` (padrão 2024) | prefeito, vice e vereadores eleitos com bens declarados |
| `GET /api/senadores` | `ano`, `uf`, `busca` | senadores pelo total da cota |
| `GET /api/senadores/{id}` | `ano`, `limit`, `offset` | tipos de despesa, série mensal, fornecedores e despesas |
| `GET /api/fornecedores/{cnpj}` | — | cadastro na Receita e o que recebeu da cota federal, da verba estadual e de órgãos municipais |
| `GET /api/estaduais` | `ano`, `partido`, `busca` | deputados estaduais de PE pelo total de verba indenizatória |
| `GET /api/estaduais/resumo` | `ano` | total, notas e gasto por rubrica |
| `GET /api/estaduais/{id}` | `ano`, `limit`, `offset` | rubricas, série mensal, fornecedores e notas paginadas |
| `GET /api/municipios/{uf}/{municipio}/camara` | `ano` | gastos da câmara, pagamentos nominais a cada vereador e pessoal nomeado |
| `GET /api/municipios/{uf}/{municipio}/prefeitura` | `ano` | pago e empenhado, por área, por tipo, por órgão e maiores credores |
| `GET /api/municipios/{uf}/{municipio}/empenhos` | `ano`, `orgao_id`, `busca`, `limit`, `offset` | empenhos paginados, busca sem acento no credor e no histórico |
| `GET /health` | — | status e data da última coleta de cada fonte |

Retorna `404` para deputado ou município inexistente e `422` para parâmetros inválidos. O CORS fica liberado só para `localhost`/`127.0.0.1`.

## Decisões de projeto

- **Dinheiro em centavos (`int`)** no banco e nas somas. O valor só vira `Decimal` na resposta da API e `number` na formatação final do front.
- **Valor líquido sempre.** Todo gasto exibido ou somado usa `valor_liquido` (o que foi reembolsado), nunca `valor_documento`.
- **Idempotência por hash.** O hash é o SHA-256 de `deputado|ano|mês|codDocumento|numDocumento|cnpj|valor_documento|parcela`, com upsert `ON CONFLICT(hash_unico)`.
- **Ano corrente sem duplicatas.** Depois de coletar um deputado/ano, as despesas que não vieram mais da origem são apagadas. Sem isso, uma correção de valor geraria um hash novo e a despesa seria contada duas vezes.
- **Emendas por "apaga e insere".** O arquivo do Portal é um retrato completo e não tem chave estável por linha. O catálogo de emendas é carregado inteiro (2014 em diante, para saber a área de restos a pagar antigos); os pagamentos, só nos anos pedidos.
- **A cidade vem dos pagamentos por favorecido.** No arquivo principal, cerca de 45% das emendas estão como "Múltiplo", "Nacional" ou só o estado. O arquivo por favorecido diz onde o dinheiro chegou.
- **Vínculo autor → deputado em duas etapas.** Pelo nome, só nas emendas da legislatura atual (evita homônimos de mandatos antigos); depois pelo código do autor do Portal, que é estável mesmo quando o nome muda ("IZALCI" / "IZALCI LUCAS").
- **Ranking justo entre estados.** O teto da cota varia por UF; o modo `relativo` compara cada deputado à média dos colegas do mesmo estado (só quem tem 6+ meses com despesas entra na média).
- **Três esferas, as mesmas regras.** Cota federal, verba estadual e empenhos municipais viram a mesma forma (pagador, ano, CNPJ, data, valor) para as regras de empresa nova, CNPJ inativo e divulgação. O alerta de MEI soma as três fontes, porque o limite de faturamento é um só.
- **Alertas são recalculados por inteiro** depois de cada coleta e gravados numa tabela; a API só lê. Os limiares ficam no `.env` (`ALERTA_*`). O alerta de concentração só olha fornecedores que atendem até 5 deputados, para não marcar companhias aéreas e operadoras.
- **CPF de pessoa física sai mascarado na API** (`***.456.789-**`), por cuidado com a LGPD, embora o dado seja público na Câmara.
- **Front em React, não Streamlit**, para aplicar o design system acessível (Atkinson Hyperlegible, contraste AA, foco visível, layout para celular). Os rankings são barras em HTML com o valor escrito, legíveis no celular e por leitor de tela. Os gráficos mensais têm uma tabela equivalente.

## Limitações conhecidas

- **O partido exibido é o atual.** Gastos anteriores a uma troca de partido aparecem atribuídos ao partido novo.
- **Despesas sem documento fiscal** ficam com `cnpj_cpf` e `url_documento` nulos.
- **Os dados do ano corrente mudam retroativamente** (glosas e lançamentos tardios), por isso esse ano é sempre recoletado.
- **Autor da emenda ligado ao deputado pelo nome e pelo código do autor.** O Portal da Transparência não usa o id da Câmara. Nomes com homônimos na legislatura ficam sem vínculo. Senadores, bancadas, comissões e ex-deputados aparecem como "outros autores".
- **Alerta não é acusação.** As regras apontam padrões para verificação; muitos têm explicação legítima (por exemplo, um escritório pequeno que aluga a sala do gabinete). O limite do MEI usado é R$ 81 mil/ano (`ALERTA_MEI_LIMITE_ANUAL`); confira se a lei mudou.
- **A cidade do fornecedor é a da sede no cadastro atual da Receita.** Empresa que mudou de endereço aparece na cidade nova. A base é mensal.
- **Só a 57ª legislatura.** Despesas de janeiro de 2023 de deputados reeleitos pertencem à 56ª e ficam de fora, tanto pela API quanto pelo CSV.
- **A API da Câmara exige `idLegislatura` junto com `ano`.** Sem ele, `/deputados/{id}/despesas?ano=X` responde vazio (comportamento observado em 10/2026).
- **Ainda não implementado:** salário e verba de gabinete dos deputados federais (a API v2 da Câmara não tem esses dados).
- **Salário individual de vereador não está nos dados abertos.** O TCE-PE publica só o empenho global da folha, e o portal da Câmara de Carpina fica atrás de um bloqueio anti-robô (que não é contornado). O que aparece por vereador são os pagamentos em que ele é o credor (diárias, indenizações), casados pelo nome.
- **PNCP:** é contrato (compromisso), não pagamento. Municípios pequenos ainda publicam pouco, e a API limita consultas em excesso (a carga usa uma conexão só e espera quando recebe 429).
- **TSE sem CPF:** desde 2024 o TSE não publica o CPF dos candidatos. O alerta "eleito com nome de sócio" usa só o nome completo (3+ palavras) e avisa que pode ser homônimo. Já o alerta de servidor sócio (TCE-PE) usa nome + 6 dígitos do CPF.
- **Pessoal do TCE-PE não tem data de desligamento.** "Nomeados no mandato" conta vínculos com admissão a partir da posse, inclusive de quem já saiu.
- **Emenda Pix × gasto depende da fonte de recurso informada pela prefeitura.** O vínculo entre o dinheiro que chegou e o que foi gasto é a fonte "Transferência Especial da União" que a própria prefeitura lança em cada empenho no TCE-PE. Fonte lançada errada (gasto maior que o recebido, ou dinheiro "parado" que foi gasto com outra fonte) aparece como alerta, sem como saber pelos dados abertos onde o dinheiro foi de fato.
- **Folha sem salário individual.** O TCE-PE publica a lista de vínculos (sem data de saída) e a folha somada por secretaria e tipo de vínculo; o valor pago a cada servidor só está no portal da prefeitura.
- **TCE-SP sem histórico nem área.** A API de transparência do TCE-SP não traz o histórico, a função de governo nem o tipo de despesa de cada empenho, e identifica pessoa física só por um código interno (sem CPF). Por isso São Paulo aparece somado por órgão e credor no ano, e o gasto por área fica com a aba Contas (Siconfi). Folha e encargos aparecem com o próprio município como credor e ficam fora do ranking de fornecedores. A capital presta contas ao TCM-SP e não está nessa base.
- **A verba da ALEPE vem de endpoints JSON do portal de transparência**, não de uma API documentada; se o portal mudar, o coletor precisa ser ajustado.
- **`TRANSPARENCIA_API_KEY`** fica configurada no `.env`, mas não é usada: todos os dados do Portal vêm do download em lote, que é público.


## Licença

Código sob a [GNU AGPL-3.0](LICENSE): você pode usar, estudar, modificar e redistribuir, inclusive
para colocar no ar outra instância; quem disponibiliza uma versão modificada na internet precisa abrir o
código dessa versão também. Os dados vêm de fontes oficiais públicas e seguem as condições de cada fonte.
