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
#
# Volume montado como root (Railway): se este script começar como root, ele conserta o dono de $DATA e
# BAIXA para o usuário do app antes de iniciar o Litestream e o servidor. Ver "privilégio" abaixo.
set -eu

DATA="${STUDIO_DATA_DIR:-/data}"
ENVN="${STUDIO_ENV:-dev}"
case "$ENVN" in dev|staging|production) ;; *) echo "entrypoint: STUDIO_ENV inválido: $ENVN" >&2; exit 2;; esac

# ------------------------------------------------------------------ privilégio: conserta $DATA e desce para o app
# A imagem declara `USER kiroo` (uid 10001), mas o Railway monta o volume pertencendo ao root; sem isto o
# servidor não consegue escrever em /data. Com RAILWAY_RUN_UID=0 a plataforma inicia o contêiner como root e
# este bloco faz, nesta ordem: (1) cria $DATA se faltar, (2) passa o dono para o app, (3) troca de usuário com
# `setpriv` e se re-executa. Depois disso NADA do app roda com privilégio: nem o Litestream, nem o servidor,
# nem o laço de backup. `setpriv` substitui o processo (exec), então tini continua PID 1 e o SIGTERM segue
# chegando direto ao Litestream.
# Plano B (pior, documentado em docs/RAILWAY.md): KIROO_SKIP_PRIV_DROP=1 mantém tudo como root.
APP_UID="${KIROO_APP_UID:-10001}"
APP_GID="${KIROO_APP_GID:-10001}"
if [ "$(id -u)" = "0" ] && [ "${KIROO_PRIV_DROPPED:-0}" != "1" ]; then
  mkdir -p "$DATA"
  chown "$APP_UID:$APP_GID" "$DATA"
  chmod 0700 "$DATA"
  # Conteúdo antigo com dono errado (volume que já rodou como root). O -quit para na primeira ocorrência:
  # num volume já correto isto não percorre os 5 GB.
  if [ -n "$(find "$DATA" ! -uid "$APP_UID" -print -quit 2>/dev/null)" ]; then
    echo "entrypoint: ajustando o dono de $DATA para $APP_UID:$APP_GID (volume montado como root)" >&2
    chown -R "$APP_UID:$APP_GID" "$DATA"
  fi
  if [ "${KIROO_SKIP_PRIV_DROP:-0}" = "1" ]; then
    echo "entrypoint: *** ATENÇÃO: KIROO_SKIP_PRIV_DROP=1 — o app vai rodar como ROOT (plano B). ***" >&2
  elif command -v setpriv >/dev/null 2>&1; then
    # HOME igual ao do usuário kiroo no /etc/passwd, para o processo ficar idêntico ao caminho `USER kiroo`.
    KIROO_PRIV_DROPPED=1
    export KIROO_PRIV_DROPPED HOME=/nonexistent
    exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups --no-new-privs --inh-caps=-all -- "$0" "$@"
  else
    echo "entrypoint: *** ATENÇÃO: setpriv ausente; o app vai rodar como ROOT. ***" >&2
  fi
fi

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
# Prefixo no bucket (padrao: o proprio STUDIO_ENV). Ensaios usam outro (ex.: ensaio) para nunca misturar com staging real.
export BACKUP_R2_PREFIX="${BACKUP_R2_PREFIX:-$ENVN}"
case "$BACKUP_R2_PREFIX" in ""|*[!a-z0-9_-]*) echo "entrypoint: BACKUP_R2_PREFIX invalido (use a-z 0-9 _ -)" >&2; exit 2;; esac
export STUDIO_DATA_DIR="$DATA" STUDIO_ENV="$ENVN"
CFG="${LITESTREAM_CONFIG:-/etc/litestream.yml}"

if [ "${STUDIO_RESTORE_ON_EMPTY:-0}" = "1" ]; then
  litestream restore -config "$CFG" -if-db-not-exists -if-replica-exists "$DATA/studio.sqlite3" \
    || { echo "entrypoint: restauração automática falhou; abortando para não subir com banco vazio" >&2; exit 4; }
fi

# "$*": o Litestream recebe o comando como UMA string e o executa como filho.
exec litestream replicate -config "$CFG" -exec "$*"
