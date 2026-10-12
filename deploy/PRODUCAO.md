# Colocar em produção

Guia para rodar uma instância pública do Estou de Olho num servidor só dela (não compartilhado).

## 1. Servidor

- **Tamanho:** 4 vCPU, 8 GB de RAM e 150 GB de SSD dão conta do Brasil inteiro com folga
  (o banco SQLite passa de 5 GB; as coletas da Receita e do TSE baixam dezenas de GB temporários).
- **Sistema:** Ubuntu LTS com Docker e o plugin `docker compose`.
- **Acesso só por chave SSH.** Em `/etc/ssh/sshd_config`: `PasswordAuthentication no` e
  `PermitRootLogin no`; reinicie o `ssh`. Antes, confirme que entra com a chave
  (`ssh-copy-id usuario@servidor`).
- **Firewall:** só 22 (SSH), 80 e 443 abertas (`ufw allow OpenSSH && ufw allow 80,443/tcp && ufw enable`).
- **Atualizações automáticas de segurança:** `apt install unattended-upgrades`.

## 2. Instalação

```bash
git clone https://github.com/sposito88/estou-de-olho.git && cd estou-de-olho
cp .env.example .env   # e preencha (veja abaixo)
docker compose build
docker compose up -d   # api + web
```

No `.env`, além do que já está no exemplo:

| Variável | Para quê |
|---|---|
| `SITE_URL=https://seu.dominio` | links nos avisos e no feed |
| `ADMIN_TOKEN=` (texto longo e aleatório: `openssl rand -hex 32`) | liga a área de contestações |
| `TELEGRAM_BOT_TOKEN=` e `TELEGRAM_CHAT_ID=` | avisos de emenda, contestação nova e falha da rotina |
| `BACKUP_REMOTO=remoto:pasta` | cópia diária do banco fora do servidor (ver item 4) |
| `PORTA_WEB=8088` | porta do site, se houver outro proxy na frente |

**HTTPS:** se o servidor for só do Estou de Olho, troque a primeira linha do `deploy/Caddyfile`
de `:80 {` para `seu.dominio {` e publique as portas 80 e 443 no serviço `web`; o Caddy emite e renova
o certificado sozinho. Atrás de outro proxy (Traefik, Cloudflare), deixe `:80` e aponte o proxy para `PORTA_WEB`.

## 3. Primeira carga e rotina

Siga a "Ordem de execução" do README (a primeira carga completa leva de 1 a 2 dias, quase tudo
esperando as fontes). Depois, a rotina diária:

```cron
30 3 * * * PATH=/usr/local/bin:/usr/bin:/bin /caminho/estou-de-olho/deploy/rotina.sh
```

Ela coleta tudo, recalcula os alertas uma vez, refaz o índice da busca, exporta os dados abertos
aos domingos, faz backup e avisa no Telegram se algum passo falhar (`python -m civic.monitor`).

## 4. Backup fora do servidor

Os backups diários ficam em `data/backups` (7 dias). Para mandar uma cópia para fora (Google Drive,
Backblaze B2, S3, outro servidor via SFTP…), configure o rclone uma vez, sem instalar nada:

```bash
docker run --rm -it -v ~/.config/rclone:/config/rclone rclone/rclone config   # crie o "remoto"
echo 'BACKUP_REMOTO=meuremoto:estou-de-olho/backups' >> .env
```

A rotina copia o backup do dia e apaga no destino o que tiver mais de 30 dias.
**Teste a restauração** de vez em quando: `gunzip -k gastos-AAAA-MM-DD.db.gz` e abra com `sqlite3`.

## 5. Monitoramento

- **Site no ar:** cadastre `https://seu.dominio/health` num monitor gratuito (UptimeRobot, Better Stack,
  Healthchecks.io). Ele devolve 200 e a data da última atualização de cada fonte.
- **Rotina:** o `civic.monitor` avisa no Telegram quando algum passo termina com falha.
- **Disco:** acompanhe `df -h`; o banco cresce com as coletas nacionais.

## 6. Comandos pelo Telegram

Com `TELEGRAM_BOT_TOKEN` e `TELEGRAM_ADMIN_CHAT_ID` no `.env` (mande `/start` ao bot e pegue o id da
conversa em `getUpdates`), ligue o bot de administração no cron:

```cron
*/5 * * * * cd $HOME/estou-de-olho && flock -n /tmp/estoudeolho-bot.lock python3 deploy/bot_admin.py >> data/logs/bot.log 2>&1
```

Na conversa privada com o bot: `/status`, `/rotina`, `/atualizar <fonte>`, `/log` e `/ajuda`. Ele só aceita
essa conversa e só executa comandos de uma lista fixa; tarefas manuais e a rotina diária não rodam juntas.

## 7. Contestações e direito de resposta

Os pedidos chegam pelo site (`/contestar`) e avisam no Telegram. Para analisar:

```bash
H="X-Admin-Token: $ADMIN_TOKEN"
curl -s -H "$H" https://seu.dominio/api/admin/contestacoes?status=recebida | jq
curl -s -X PATCH -H "$H" -H 'Content-Type: application/json' \
  -d '{"status": "resposta_publicada", "resposta_publica": "Texto que aparece no site."}' \
  https://seu.dominio/api/admin/contestacoes/ID
```

Status: `recebida`, `em_analise`, `corrigida`, `mantida` (com explicação) e `resposta_publicada`.
Os três últimos aparecem em público em `/correcoes` e na própria página contestada. Combine um prazo
de resposta (ex.: 10 dias úteis) e cumpra.

## 8. Quando mudar para PostgreSQL

O SQLite em modo WAL aguenta bem muitas leituras e uma escrita por vez, o que basta para o site com
coleta noturna. Mude quando aparecer um destes sinais:

- erros "database is locked" no log da API durante a rotina;
- mais de um servidor de API (balanceamento de carga);
- coletas que precisem rodar em paralelo com escrita intensa.

O código usa SQLAlchemy, mas há trechos específicos do SQLite (upserts com `sqlite_insert`,
`strftime`, FTS5 da busca). A migração envolve trocar esses trechos pelos equivalentes do PostgreSQL
(`postgresql.insert ... on_conflict_do_update`, `to_char`/`extract`, `tsvector` ou `pg_trgm` para a busca)
e copiar os dados com `pgloader`. Vale abrir uma issue para planejar junto.
