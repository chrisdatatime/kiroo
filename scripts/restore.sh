#!/usr/bin/env bash
# Restaura banco (Litestream) e mídia (rclone) do R2 em uma pasta de DESTINO NOVA e valida o resultado.
#
#   STUDIO_ENV=staging bash scripts/restore.sh --dest /caminho/novo [--timestamp 2026-11-06T12:00:00Z] [--db-only|--media-only] [--hash]
#
# Segurança (sem exceções, não há --force):
#   * O destino NÃO pode existir com conteúdo. Nada é sobrescrito: nem banco, nem pasta de mídia.
#   * Recusa destino igual a STUDIO_DATA_DIR, dentro dele, ou que o contenha (proteção do volume real).
#   * Só LÊ do bucket; usa credenciais de backup apenas por variáveis de ambiente (nunca impressas).
# Depois de restaurar roda scripts/verify_restore.py (integridade do SQLite, registros, arquivos de mídia).
#
# Alinhamento banco x mídia: o banco é replicado continuamente (--timestamp escolhe o ponto), a mídia é um espelho diário.
# Banco mais novo que a mídia => alguns arquivos ausentes (relatados por produção). Veja docs/BACKUP.md.
#
# Modo local (testes e ensaio sem R2): --local-db ARQUIVO.sqlite3 e/ou --local-media PASTA substituem o bucket.
# Saída: 0 ok | 1 validação falhou | 2 uso/config | 3 destino recusado | 4 falha ao restaurar | 5 mídia incompleta (banco ok).
set -euo pipefail
umask 077

DEST=""; TS=""; DO_DB=1; DO_MEDIA=1; HASH=""; LDB=""; LMEDIA=""
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
while [ $# -gt 0 ]; do case "$1" in
  --dest) DEST="${2:-}"; shift 2;;
  --timestamp) TS="${2:-}"; shift 2;;
  --db-only) DO_MEDIA=0; shift;;
  --media-only) DO_DB=0; shift;;
  --hash) HASH="--hash"; shift;;
  --local-db) LDB="${2:-}"; shift 2;;
  --local-media) LMEDIA="${2:-}"; shift 2;;
  -h|--help) sed -n '2,19p' "$0"; exit 0;;
  *) echo "argumento desconhecido: $1" >&2; exit 2;; esac; done

die() { echo "restore: $1" >&2; exit "${2:-2}"; }
PYBIN="${PYTHON:-}"; [ -n "$PYBIN" ] || PYBIN="$(command -v python3 || command -v python || true)"
[ -n "$PYBIN" ] || die "python não encontrado (defina PYTHON)"

[ -n "$DEST" ] || die "informe --dest (pasta nova)"
if [ -e "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null || true)" ]; then
  die "destino já existe e não está vazio: $DEST (nada será sobrescrito)" 3
fi
mkdir -p "$DEST"; DEST="$(cd "$DEST" && pwd)"
if [ -n "${STUDIO_DATA_DIR:-}" ] && [ -d "${STUDIO_DATA_DIR}" ]; then
  REAL="$(cd "$STUDIO_DATA_DIR" && pwd)"
  case "$DEST/" in "$REAL/"*) die "destino dentro de STUDIO_DATA_DIR (volume real): recusado" 3;; esac
  case "$REAL/" in "$DEST/"*) die "destino contém STUDIO_DATA_DIR (volume real): recusado" 3;; esac
fi

BUCKET="${BACKUP_BUCKET:-kiroo-backups}"
PREFIX="${BACKUP_R2_PREFIX:-${STUDIO_ENV:-}}"   # prefixo no bucket; padrao = STUDIO_ENV

# Configuracao do Litestream: LITESTREAM_CONFIG (padrao /etc/litestream.yml, o caminho da imagem); se o padrao nao
# existir e nada foi pedido, cai para o litestream.yml do repositorio (./ ou ao lado de scripts/).
CFG=""
if [ "$DO_DB" -eq 1 ] && [ -z "$LDB" ]; then
  if [ -n "${LITESTREAM_CONFIG:-}" ]; then
    [ -f "$LITESTREAM_CONFIG" ] || die "LITESTREAM_CONFIG aponta para arquivo inexistente: $LITESTREAM_CONFIG"
    CFG="$LITESTREAM_CONFIG"
  else
    for c in /etc/litestream.yml ./litestream.yml "$HERE/../litestream.yml"; do
      [ -f "$c" ] && { CFG="$c"; break; }
    done
    [ -n "$CFG" ] || die "configuracao do Litestream nao encontrada (procurei /etc/litestream.yml, ./litestream.yml e $HERE/../litestream.yml); defina LITESTREAM_CONFIG"
  fi
fi

if [ -z "$LDB" ] && [ -z "$LMEDIA" ]; then
  case "${STUDIO_ENV:-}" in dev|staging|production) ;; *) die "defina STUDIO_ENV=dev|staging|production (ou use --local-db/--local-media)";; esac
  missing=""
  for v in BACKUP_R2_ENDPOINT BACKUP_R2_ACCESS_KEY_ID BACKUP_R2_SECRET_ACCESS_KEY; do [ -n "${!v:-}" ] || missing="$missing $v"; done
  [ -z "$missing" ] || die "variáveis ausentes (só os nomes):$missing"
  case "$PREFIX" in ""|*[!a-z0-9_-]*) die "BACKUP_R2_PREFIX invalido (use a-z 0-9 _ -)";; esac
fi

if [ "$DO_DB" -eq 1 ]; then
  echo "restore: banco -> $DEST/studio.sqlite3"
  if [ -n "$LDB" ]; then
    [ -f "$LDB" ] || die "--local-db inexistente: $LDB"
    "$PYBIN" - "$LDB" "$DEST/studio.sqlite3" <<'PYEOF' || die "cópia local do banco falhou" 4
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)          # cópia consistente (inclui o que ainda está no WAL)
dst.close(); src.close()
PYEOF
  else
    command -v "${LITESTREAM:-litestream}" >/dev/null 2>&1 || die "litestream não encontrado no PATH"
    export LITESTREAM_ACCESS_KEY_ID="$BACKUP_R2_ACCESS_KEY_ID" LITESTREAM_SECRET_ACCESS_KEY="$BACKUP_R2_SECRET_ACCESS_KEY"
    export BACKUP_BUCKET="$BUCKET" BACKUP_R2_PREFIX="$PREFIX"
    # O caminho do banco só identifica a entrada no litestream.yml (mesma expansão usada na replicação).
    export STUDIO_DATA_DIR_SOURCE="${STUDIO_DATA_DIR_SOURCE:-/data}"
    ARGS=(restore -config "$CFG" -o "$DEST/studio.sqlite3")
    [ -z "$TS" ] || ARGS+=(-timestamp "$TS")
    STUDIO_DATA_DIR="$STUDIO_DATA_DIR_SOURCE" "${LITESTREAM:-litestream}" "${ARGS[@]}" "$STUDIO_DATA_DIR_SOURCE/studio.sqlite3" \
      || die "litestream restore falhou (há réplica em ${PREFIX}/db? timestamp válido?)" 4
  fi
fi

if [ "$DO_MEDIA" -eq 1 ]; then
  echo "restore: mídia -> $DEST"
  if [ -n "$LMEDIA" ]; then
    [ -d "$LMEDIA" ] || die "--local-media inexistente: $LMEDIA"
    cp -R "$LMEDIA"/. "$DEST"/ || die "cópia local da mídia falhou" 4
  else
    command -v "${RCLONE:-rclone}" >/dev/null 2>&1 || die "rclone não encontrado no PATH"
    export RCLONE_CONFIG_KBK_TYPE=s3 RCLONE_CONFIG_KBK_PROVIDER=Cloudflare RCLONE_CONFIG_KBK_NO_CHECK_BUCKET=true
    export RCLONE_CONFIG_KBK_ENDPOINT="$BACKUP_R2_ENDPOINT" RCLONE_CONFIG_KBK_ACCESS_KEY_ID="$BACKUP_R2_ACCESS_KEY_ID"
    export RCLONE_CONFIG_KBK_SECRET_ACCESS_KEY="$BACKUP_R2_SECRET_ACCESS_KEY"
    # `copy` (nunca sync/delete) e só o espelho "current"; versões antigas ficam em archive/ para recuperação manual.
    "${RCLONE:-rclone}" copy "KBK:${BUCKET}/${PREFIX}/media/current" "$DEST" --fast-list --transfers 4 --checkers 8 --retries 3 \
      || die "rclone copy falhou" 4
  fi
fi

echo "restore: validando"
VCODE=0
if [ "$DO_DB" -eq 1 ]; then
  "$PYBIN" "$HERE/verify_restore.py" --data-dir "$DEST" $HASH || VCODE=$?
else
  echo "restore: --media-only, validação do banco ignorada"
fi
case "$VCODE" in
  0) echo "restore: OK em $DEST";;
  2) echo "restore: banco íntegro, mídia incompleta (esperado se o banco é mais novo que o último backup de mídia)" >&2; exit 5;;
  *) echo "restore: VALIDAÇÃO FALHOU (código $VCODE)" >&2; exit 1;;
esac
cat <<MSG

Para abrir o restaurado SEM tocar no real (porta e dados descartáveis):
  STUDIO_DATA_DIR="$DEST" STUDIO_PORT=8799 STUDIO_MODE=simulated python -m studio ui --no-browser
MSG
