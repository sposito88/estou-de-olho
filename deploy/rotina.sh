#!/usr/bin/env bash
# Rotina diária (cron) do Estou de Olho:
#   1. coleta da cota e das emendas (envia avisos do Telegram);
#   1b. verba dos deputados estaduais (ALEPE) e contas municipais (TCE-PE; TCE-SP aos sábados);
#   2. base de CNPJ da Receita (só trabalha quando sai um mês novo);
#   3. alertas (uma vez só, no fim) e índice da busca por nome;
#   4. backup do banco (guarda os últimos 7 dias).
# Uso: deploy/rotina.sh            (o cron chama assim)
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/backups data/logs
exec >>"data/logs/rotina-$(date +%Y-%m).log" 2>&1
# Uma rotina por vez, e nunca junto com uma tarefa pedida pelo Telegram (deploy/bot_admin.py):
# espera até 2 h pela outra terminar.
exec 9>/tmp/estoudeolho-rotina.lock
if ! flock -w 7200 9; then
  echo "== $(date -Is) rotina não rodou: outra execução ocupou a trava por mais de 2 h"
  exit 1
fi

echo "== $(date -Is) início"
# Cada coleta deixa de recalcular os alertas; o recálculo roda uma vez só, no fim.
coleta="docker compose run --rm -e ALERTAS_AO_FINAL=false"
python_coleta="docker compose run --rm --no-deps --entrypoint python coleta"
$coleta coleta || echo "!! coleta terminou com falhas (ver acima)"
$coleta pernambuco || echo "!! coleta de Pernambuco terminou com falhas (ver acima)"
$coleta senado || echo "!! coleta do Senado terminou com falhas (ver acima)"
$coleta pncp || echo "!! contratos do PNCP terminaram com falhas (ver acima)"
$coleta siconfi || echo "!! contas do Siconfi terminaram com falhas (ver acima)"
# Ano corrente pelo relatório bimestral (RREO): só consulta quem ainda não tem o bimestre esperado.
$coleta siconfi python -m civic.siconfi --rreo --sem-progresso || echo "!! RREO do Siconfi terminou com falhas (ver acima)"
$coleta transferegov || echo "!! Emendas Pix (Transferegov) terminaram com falhas (ver acima)"
# TCE-SP (644 municípios, ~2 h) e TCE-RS (497 municípios, arquivo anual de ~1,4 GB): só aos sábados.
if [ "$(date +%u)" = "6" ]; then
  $coleta tce_sp || echo "!! contas municipais do TCE-SP terminaram com falhas (ver acima)"
  $coleta tce_rs || echo "!! contas municipais do TCE-RS terminaram com falhas (ver acima)"
fi
# TCE-PB: quadro de pessoal com salário de todos os municípios da Paraíba (arquivo do ano, ~70 MB).
$coleta tce_pb || echo "!! pessoal do TCE-PB terminou com falhas (ver acima)"
# TSE quase não muda depois da eleição: só aos domingos.
if [ "$(date +%u)" = "7" ]; then
  $coleta tse || echo "!! TSE terminou com falhas (ver acima)"
fi
$coleta cnpj || echo "!! base de CNPJ falhou (ver acima)"


echo "== $(date -Is) alertas e busca"
# Incorpora o log de transações (WAL) ao banco antes das consultas pesadas: depois de coletas longas ele
# pode passar de 10 GB e deixar toda leitura lenta.
$python_coleta -c "
import sqlite3
c = sqlite3.connect('/app/data/gastos.db', timeout=600)
print('checkpoint:', c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone())
c.close()
" || echo "!! checkpoint do WAL falhou"
$python_coleta -m civic.alertas || echo "!! recálculo dos alertas falhou (ver acima)"
$python_coleta -m civic.busca || echo "!! índice de busca falhou (ver acima)"
# Canal público do Telegram: resumo dos alertas fortes surgidos desde o último resumo.
$python_coleta -m civic.canal || echo "!! resumo do canal do Telegram falhou (ver acima)"
# Sem ANALYZE/PRAGMA optimize: as consultas foram afinadas sem estatísticas, e com elas o SQLite chegou a
# escolher planos milhares de vezes mais lentos (alertas que levavam segundos passaram de horas).

# Dados abertos (CSV em data/publico, servidos em /dados/): uma vez por semana, aos domingos.
if [ "$(date +%u)" = "7" ]; then
  $python_coleta -m civic.exportar || echo "!! exportação dos dados abertos falhou (ver acima)"
fi

echo "== $(date -Is) backup"
destino="data/backups/gastos-$(date +%F).db"
docker compose run --rm --no-deps --entrypoint python coleta -c "
import sqlite3
origem = sqlite3.connect('/app/data/gastos.db')
copia = sqlite3.connect('/app/$destino')
origem.backup(copia)
copia.close(); origem.close()
" && gzip -f "$destino" && echo "backup: $destino.gz"
find data/backups -name 'gastos-*.db.gz' -mtime +7 -delete

# Cópia fora do servidor (opcional): BACKUP_REMOTO=remoto:pasta no .env, com o rclone já configurado
# em ~/.config/rclone (docker run --rm -it -v ~/.config/rclone:/config/rclone rclone/rclone config).
# Mantém 30 dias no destino.
backup_remoto=$(grep -E '^BACKUP_REMOTO=' .env 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
if [ -n "$backup_remoto" ] && [ -f "$destino.gz" ]; then
  rclone_docker="docker run --rm -v $HOME/.config/rclone:/config/rclone -v $PWD/data/backups:/backups:ro rclone/rclone"
  $rclone_docker copy "/backups/$(basename "$destino").gz" "$backup_remoto" \
    && $rclone_docker delete --min-age 30d "$backup_remoto" \
    && echo "backup remoto: $backup_remoto" || echo "!! cópia do backup para $backup_remoto falhou"
fi
echo "== $(date -Is) fim"
# Avisa no Telegram se algum passo falhou (com TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env).
$python_coleta -m civic.monitor "/app/data/logs/rotina-$(date +%Y-%m).log" >/dev/null 2>&1 || true
