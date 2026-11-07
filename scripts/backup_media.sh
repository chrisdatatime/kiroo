#!/usr/bin/env bash
# Backup diário da mídia do Kiroo para o R2 (bucket privado kiroo-backups), com rclone.
#
#   STUDIO_ENV=production bash scripts/backup_media.sh [--dry-run] [--allow-empty] [--data-dir DIR]
#
# Layout no bucket:
#   <bucket>/<ambiente>/media/current/<pasta>/...                 espelho do estado mais recente
#   <bucket>/<ambiente>/media/archive/<AAAA-MM-DDTHHMMSSZ>/<pasta>/...   versões SUBSTITUÍDAS ou REMOVIDAS na origem
#   <bucket>/<ambiente>/media/manifests/<AAAA-MM-DDTHHMMSSZ>.json   tamanhos/contagens desta execução
#
# Nunca apaga nada no destino sem guardar a versão: usa `rclone sync --backup-dir`, que MOVE o que seria
# sobrescrito/apagado para archive/<data>. A retirada definitiva de versões antigas é uma decisão separada
# (regra de ciclo de vida do bucket; ver docs/BACKUP.md), nunca deste script.
#
# Credenciais (SÓ por variáveis de ambiente; nada é lido de arquivo nem impresso):
#   BACKUP_R2_ENDPOINT  BACKUP_R2_ACCESS_KEY_ID  BACKUP_R2_SECRET_ACCESS_KEY   (BACKUP_BUCKET, padrão kiroo-backups)
# Entradas:  STUDIO_ENV (dev|staging|production, OBRIGATÓRIA: define o prefixo)  e  STUDIO_DATA_DIR (ou --data-dir).
# Saída: 0 ok | 2 uso/config inválida | 3 recusado por segurança (origem vazia) | outro = erro do rclone.
set -euo pipefail
umask 077

DRY=""; ALLOW_EMPTY=0; DATA_DIR="${STUDIO_DATA_DIR:-}"
while [ $# -gt 0 ]; do case "$1" in
  --dry-run) DRY="--dry-run"; shift;;
  --allow-empty) ALLOW_EMPTY=1; shift;;
  --data-dir) DATA_DIR="${2:-}"; shift 2;;
  -h|--help) sed -n '2,20p' "$0"; exit 0;;
  *) echo "argumento desconhecido: $1" >&2; exit 2;; esac; done

die() { echo "backup_media: $1" >&2; exit "${2:-2}"; }

case "${STUDIO_ENV:-}" in dev|staging|production) ;; *) die "defina STUDIO_ENV=dev|staging|production";; esac
[ -n "$DATA_DIR" ] && [ -d "$DATA_DIR" ] || die "STUDIO_DATA_DIR/--data-dir inexistente: ${DATA_DIR:-<vazio>}"
missing=""
for v in BACKUP_R2_ENDPOINT BACKUP_R2_ACCESS_KEY_ID BACKUP_R2_SECRET_ACCESS_KEY; do
  [ -n "${!v:-}" ] || missing="$missing $v"; done
[ -z "$missing" ] || die "variáveis ausentes (só os nomes):$missing"
command -v "${RCLONE:-rclone}" >/dev/null 2>&1 || die "rclone não encontrado no PATH"
RC="${RCLONE:-rclone}"

# Remoto do rclone definido por variáveis de ambiente (as chaves não vão para a linha de comando nem para arquivo).
export RCLONE_CONFIG_KBK_TYPE=s3 RCLONE_CONFIG_KBK_PROVIDER=Cloudflare
export RCLONE_CONFIG_KBK_ENDPOINT="$BACKUP_R2_ENDPOINT"
export RCLONE_CONFIG_KBK_ACCESS_KEY_ID="$BACKUP_R2_ACCESS_KEY_ID"
export RCLONE_CONFIG_KBK_SECRET_ACCESS_KEY="$BACKUP_R2_SECRET_ACCESS_KEY"
export RCLONE_CONFIG_KBK_NO_CHECK_BUCKET=true      # o token só lê/escreve objetos; não cria bucket

BUCKET="${BACKUP_BUCKET:-kiroo-backups}"
ROOT="KBK:${BUCKET}/${STUDIO_ENV}/media"
TS="$(date -u +%Y-%m-%dT%H%M%SZ)"

# Impede duas execuções ao mesmo tempo (tarefa agendada que demorou mais que o intervalo).
LOCK_DIR="${TMPDIR:-/tmp}"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_DIR/kiroo-backup-media-${STUDIO_ENV}.lock"
  flock -n 9 || die "outra execução do backup está em andamento" 4
fi

# Pastas com dado do usuário (persistente e não regenerável). sound_cache, sim_ops, demo_inputs e logs ficam de fora.
DIRS="productions uploads workspaces music training"
flags=(--fast-list --transfers 4 --checkers 8 --retries 3 --low-level-retries 5 --stats-one-line --exclude ".readyz-*" --exclude "*.tmp")
summary=""
for d in $DIRS; do
  src="$DATA_DIR/$d"
  [ -d "$src" ] || { echo "backup_media: $d ausente na origem (ignorado)"; continue; }
  if [ -z "$(ls -A "$src" 2>/dev/null)" ] && [ "$ALLOW_EMPTY" -ne 1 ]; then
    # origem vazia + sync = arquivar o espelho inteiro. Quase sempre é volume errado/desmontado.
    die "$d está vazia na origem; recusado (use --allow-empty se for esperado)" 3
  fi
  echo "backup_media: $d -> $ROOT/current/$d"
  "$RC" sync "$src" "$ROOT/current/$d" --backup-dir "$ROOT/archive/$TS/$d" "${flags[@]}" $DRY
  sz="$("$RC" size --json "$src" 2>/dev/null || echo '{}')"
  summary="${summary}\"$d\":${sz},"
done
if [ -f "$DATA_DIR/agents.json" ]; then       # configuração da interface (pequena)
  "$RC" copyto "$DATA_DIR/agents.json" "$ROOT/current/agents.json" --backup-dir "$ROOT/archive/$TS" $DRY
fi

if [ -z "$DRY" ]; then
  printf '{"finished_at":"%s","env":"%s","dirs":{%s}}\n' "$TS" "$STUDIO_ENV" "${summary%,}" \
    | "$RC" rcat "$ROOT/manifests/$TS.json"
fi
echo "backup_media: concluído ($TS)${DRY:+ [dry-run]}"
