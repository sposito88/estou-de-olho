#!/usr/bin/env bash
# Rotina diária (cron) do Estou de Olho:
#   1. coleta da cota e das emendas (envia avisos do Telegram);
#   1b. verba dos deputados estaduais (ALEPE) e contas municipais (TCE-PE; TCE-SP aos sábados);
#   2. base de CNPJ da Receita (só trabalha quando sai um mês novo);
#   3. alertas (uma vez só, no fim), índice da busca por nome e estatísticas do banco;
#   4. backup do banco (guarda os últimos 7 dias).
# Uso: deploy/rotina.sh            (o cron chama assim)
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/backups data/logs
exec >>"data/logs/rotina-$(date +%Y-%m).log" 2>&1

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
# TCE-SP: 644 municípios, relê o ano corrente inteiro (~2 h): só aos sábados.
if [ "$(date +%u)" = "6" ]; then
  $coleta tce_sp || echo "!! contas municipais do TCE-SP terminaram com falhas (ver acima)"
fi
# TSE quase não muda depois da eleição: só aos domingos.
if [ "$(date +%u)" = "7" ]; then
  $coleta tse || echo "!! TSE terminou com falhas (ver acima)"
fi
$coleta cnpj || echo "!! base de CNPJ falhou (ver acima)"


echo "== $(date -Is) alertas e busca"
$python_coleta -m civic.alertas || echo "!! recálculo dos alertas falhou (ver acima)"
$python_coleta -m civic.busca || echo "!! índice de busca falhou (ver acima)"
$python_coleta -c "
import sqlite3
c = sqlite3.connect('/app/data/gastos.db', timeout=600)
c.execute('PRAGMA optimize')
c.close()
" || echo "!! PRAGMA optimize falhou"

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
echo "== $(date -Is) fim"
