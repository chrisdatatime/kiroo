#!/bin/sh
# Entrypoint do contêiner Kiroo: roda o servidor sob o Litestream (replicação contínua do SQLite para o R2).
#
#   litestream replicate -exec "<comando do servidor>"
#
# O Litestream sobe o servidor como processo filho, repassa SIGTERM/SIGINT a ele e, depois que ele sai, faz a
# última sincronização. Sem as variáveis de backup:
#   * dev            -> sobe o servidor direto, sem replicação (aviso informativo);
#   * staging/prod   -> sobe mesmo assim, mas com aviso ALTO aqui e no log/`/readyz` do servidor (os dados ficam sem cópia).
# Credenciais: só variáveis de ambiente do processo; este script nunca as imprime.
#
# Opcional STUDIO_RESTORE_ON_EMPTY=1: se NÃO existir banco no volume e houver réplica, restaura antes de subir
# (recuperação de volume perdido). Nunca sobrescreve banco existente.
set -eu

DATA="${STUDIO_DATA_DIR:-/data}"
ENVN="${STUDIO_ENV:-dev}"
case "$ENVN" in dev|staging|production) ;; *) echo "entrypoint: STUDIO_ENV inválido: $ENVN" >&2; exit 2;; esac

missing=""
for v in BACKUP_R2_ENDPOINT BACKUP_R2_ACCESS_KEY_ID BACKUP_R2_SECRET_ACCESS_KEY; do
  eval "val=\${$v:-}"
  [ -n "$val" ] || missing="$missing $v"
done

if [ -n "$missing" ]; then
  case "$ENVN" in
    staging|production)
      echo "entrypoint: *** ATENÇÃO: BACKUP DO BANCO NÃO CONFIGURADO em $ENVN (faltam:$missing). O servidor vai subir SEM replicação. ***" >&2;;
    *) echo "entrypoint: backup desligado (dev; faltam:$missing)" >&2;;
  esac
  exec "$@"
fi

export LITESTREAM_ACCESS_KEY_ID="$BACKUP_R2_ACCESS_KEY_ID"
export LITESTREAM_SECRET_ACCESS_KEY="$BACKUP_R2_SECRET_ACCESS_KEY"
export BACKUP_BUCKET="${BACKUP_BUCKET:-kiroo-backups}"
export STUDIO_DATA_DIR="$DATA" STUDIO_ENV="$ENVN"
CFG="${LITESTREAM_CONFIG:-/etc/litestream.yml}"

if [ "${STUDIO_RESTORE_ON_EMPTY:-0}" = "1" ]; then
  litestream restore -config "$CFG" -if-db-not-exists -if-replica-exists "$DATA/studio.sqlite3" \
    || { echo "entrypoint: restauração automática falhou; abortando para não subir com banco vazio" >&2; exit 4; }
fi

# "$*": o Litestream recebe o comando como UMA string e o executa como filho.
exec litestream replicate -config "$CFG" -exec "$*"
