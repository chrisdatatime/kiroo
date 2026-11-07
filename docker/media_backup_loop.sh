#!/bin/sh
# Backup diário da mídia (produções, uploads, workspaces, music, training) de dentro do contêiner.
#
# Sem cron e sem supercronic: um laço de `sleep` + o roteiro que já existe, scripts/backup_media.sh. O
# contêiner do Railway roda um processo só e não tem agendador; uma dependência a mais na imagem não se
# justifica para uma tarefa por dia.
#
# Começa desligado por padrão em dev e ligado em staging/production, e só roda quando as credenciais do R2
# estão no ambiente (quem decide isso é o entrypoint, que só chama este laço nesse caso).
#   STUDIO_MEDIA_BACKUP=0|1            desliga/liga explicitamente (vence o padrão do ambiente)
#   STUDIO_MEDIA_BACKUP_INTERVAL_S     intervalo entre execuções (padrão 86400 = 24 h)
#   STUDIO_MEDIA_BACKUP_DELAY_S        espera antes da primeira (padrão 300 s: deixa o servidor subir)
#   STUDIO_MEDIA_BACKUP_ARGS           argumentos extras para backup_media.sh (ex.: --allow-empty)
#   STUDIO_MEDIA_BACKUP_MAX_RUNS       para depois de N execuções (padrão 0 = sem limite; 1 = só uma)
#
# Credenciais: só variáveis de ambiente, herdadas do entrypoint. Este script nunca as imprime; o
# backup_media.sh também não (ele passa as chaves ao rclone por RCLONE_CONFIG_*).
#
# Encerramento: recebe o PID que vai virar o Litestream e sai sozinho quando ele morre, para não ficar um
# processo órfão depois do desligamento. O sleep é picado em fatias curtas só para notar isso rápido.
set -u

WATCH_PID="${1:-0}"
INTERVAL="${STUDIO_MEDIA_BACKUP_INTERVAL_S:-86400}"
DELAY="${STUDIO_MEDIA_BACKUP_DELAY_S:-300}"
MAX_RUNS="${STUDIO_MEDIA_BACKUP_MAX_RUNS:-0}"
SLICE=5                      # granularidade da checagem de que o processo vigiado ainda existe
SCRIPT="${STUDIO_MEDIA_BACKUP_SCRIPT:-/app/scripts/backup_media.sh}"

case "$INTERVAL" in ''|*[!0-9]*) echo "media_backup: STUDIO_MEDIA_BACKUP_INTERVAL_S inválido" >&2; exit 2;; esac
case "$DELAY" in ''|*[!0-9]*) echo "media_backup: STUDIO_MEDIA_BACKUP_DELAY_S inválido" >&2; exit 2;; esac
case "$MAX_RUNS" in ''|*[!0-9]*) echo "media_backup: STUDIO_MEDIA_BACKUP_MAX_RUNS inválido" >&2; exit 2;; esac
[ "$INTERVAL" -ge "$SLICE" ] || { echo "media_backup: intervalo mínimo é ${SLICE}s" >&2; exit 2; }
[ -f "$SCRIPT" ] || { echo "media_backup: roteiro não encontrado: $SCRIPT" >&2; exit 2; }
command -v bash >/dev/null 2>&1 || { echo "media_backup: bash ausente (backup_media.sh exige bash)" >&2; exit 2; }

# Dorme `$1` segundos em fatias, parando se o processo vigiado sair. Devolve 1 quando é hora de encerrar.
nap() {
  left="$1"
  while [ "$left" -gt 0 ]; do
    if [ "$WATCH_PID" != "0" ] && ! kill -0 "$WATCH_PID" 2>/dev/null; then
      return 1
    fi
    step="$SLICE"
    [ "$left" -lt "$step" ] && step="$left"
    sleep "$step"
    left=$((left - step))
  done
  [ "$WATCH_PID" = "0" ] || kill -0 "$WATCH_PID" 2>/dev/null
}

echo "media_backup: laço ligado (primeira execução em ${DELAY}s, depois a cada ${INTERVAL}s)"
nap "$DELAY" || { echo "media_backup: servidor saiu antes da primeira execução; encerrando"; exit 0; }

runs=0
while :; do
  inicio="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "media_backup: início $inicio"
  # backup_media.sh é bash (arrays e ${!var}); não roda com sh.
  # shellcheck disable=SC2086 - STUDIO_MEDIA_BACKUP_ARGS é lista de argumentos de propósito
  if bash "$SCRIPT" ${STUDIO_MEDIA_BACKUP_ARGS:-}; then
    echo "media_backup: ok (início $inicio, fim $(date -u +%Y-%m-%dT%H:%M:%SZ))"
  else
    rc=$?
    # 1 falha do rclone | 2 uso/config | 3 recusado (origem vazia) | 4 outra execução em andamento
    echo "media_backup: FALHOU código=$rc (início $inicio, fim $(date -u +%Y-%m-%dT%H:%M:%SZ)); o laço continua" >&2
  fi
  runs=$((runs + 1))
  if [ "$MAX_RUNS" != "0" ] && [ "$runs" -ge "$MAX_RUNS" ]; then
    echo "media_backup: limite de $MAX_RUNS execução(ões) atingido; encerrando"
    exit 0
  fi
  nap "$INTERVAL" || { echo "media_backup: servidor saiu; encerrando"; exit 0; }
done
