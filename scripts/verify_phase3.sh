#!/usr/bin/env bash
# Verificação da Fase 3 contra a imagem/serviço reais (NÃO foi executada pelo autor: a sessão de desenvolvimento não tem Docker).
# Uso (Git Bash/Linux/macOS, na raiz do repo, com o serviço do Compose rodando):  bash scripts/verify_phase3.sh [a|b|c|d|all]
# Nunca imprime valores de variáveis de ambiente. Nunca usa down -v, volume rm ou prune. O passo c faz backup do volume ANTES.
set -u
IMG="${IMG:-kiroo:local}"; SVC="${SVC:-kiroo}"; VOL="${VOL:-kiroo_kiroo-data}"; URL="${URL:-http://127.0.0.1:8765}"
BK="${BACKUP_DIR:-$HOME/kiroo-backups}"; PY="${PYTHON:-python3}"; command -v "$PY" >/dev/null || PY=python
step="${1:-all}"; fail=0
say(){ printf '\n== %s\n' "$*"; }
ok(){ printf '[OK] %s\n' "$*"; }; bad(){ printf '[FALHOU] %s\n' "$*"; fail=1; }

a(){ say "2a. Sem credenciais nem ZIP na imagem"
  docker history --no-trunc "$IMG" >/tmp/kiroo-history.txt
  if grep -i -E 'R2_|secret|\.zip|kiroo-licensed-assets' /tmp/kiroo-history.txt >/dev/null; then bad "docker history contém R2_/secret/.zip/nome do pacote (ver /tmp/kiroo-history.txt)"; else ok "docker history sem R2_, secret, .zip ou nome do pacote"; fi
  # Config.Env filtrado: só testa a presença de nomes R2_*, não imprime o ambiente
  if docker image inspect "$IMG" --format '{{range .Config.Env}}{{println .}}{{end}}' | cut -d= -f1 | grep -E '^R2_' >/dev/null; then bad "Config.Env tem variável R2_*"; else ok "Config.Env sem R2_*"; fi
  tar_f="$(mktemp -d)/kiroo.tar"; docker save "$IMG" -o "$tar_f" && "$PY" scripts/verify_image_layers.py "$tar_f" && ok "varredura de todas as camadas limpa" || bad "varredura de camadas encontrou algo (ver saída acima)"
  rm -f "$tar_f"
  echo "zips e assets no sistema de arquivos da imagem:"
  docker run --rm --entrypoint sh "$IMG" -c 'find / -xdev -name "*.zip" 2>/dev/null | head; echo "--- licenses:"; ls /app/licenses; echo "--- bia:"; ls /app/assets /reference 2>&1 | head'
  if git grep -n -i -E 'write.?token|r2_write|upload.?token|put_object|upload_file' -- . ':!tests/*' ':!docs/*' ':!scripts/verify_*' >/dev/null; then bad "referência a token/escrita no repo"; else ok "repo sem referência a token de escrita/upload"; fi; }

b(){ say "2b. Usuário não-root"
  docker compose exec -T "$SVC" id
  docker compose exec -T "$SVC" sh -c 'for p in /proc/[0-9]*; do n=$(sed -n "s/^Name:\t//p" $p/status); u=$(sed -n "s/^Uid:\t\([0-9]*\).*/\1/p" $p/status); echo "pid=${p#/proc/} uid=$u $n"; done'
  docker compose exec -T "$SVC" sh -c 'touch /data/.w && rm /data/.w && echo "/data gravável: sim"; for d in /app /usr /etc /app/frontend/dist; do touch $d/.w 2>/dev/null && { echo "$d gravável: SIM (ruim)"; rm -f $d/.w; } || echo "$d gravável: não"; done'; }

snap(){ docker compose exec -T "$SVC" python - <<'PYSNAP'
import hashlib, json, os, sqlite3
db = sqlite3.connect("file:/data/studio.sqlite3?mode=ro", uri=True)
tables = [r[0] for r in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by 1")]
counts = {t: db.execute(f'select count(*) from "{t}"').fetchone()[0] for t in tables}
ic = db.execute("pragma integrity_check").fetchone()[0]
media = {}
for root, _, files in os.walk("/data/productions"):
    for f in sorted(files):
        p = os.path.join(root, f); h = hashlib.sha256()
        with open(p, "rb") as fh:
            for c in iter(lambda: fh.read(1 << 20), b""): h.update(c)
        media[os.path.relpath(p, "/data")] = h.hexdigest()
print(json.dumps({"counts": counts, "integrity_check": ic, "media": media}, sort_keys=True))
PYSNAP
}

c(){ say "2c. Persistência após recriar (com backup antes)"
  mkdir -p "$BK"; ts=$(date +%Y%m%d-%H%M%S)
  docker run --rm -v "$VOL":/data:ro -v "$BK":/bk alpine tar czf "/bk/data-$ts.tgz" -C /data . || { bad "backup falhou; abortando"; return; }
  if docker run --rm -v "$BK":/bk alpine tar tzf "/bk/data-$ts.tgz" >/dev/null; then ok "backup abre: $BK/data-$ts.tgz"; else bad "backup não abre; abortando"; return; fi
  snap > "$BK/snap-before-$ts.json" || { bad "snapshot antes falhou"; return; }
  docker compose down                                   # SEM -v
  docker compose up -d --force-recreate
  for i in $(seq 1 30); do curl -fs "$URL/healthz" >/dev/null && break; sleep 2; done
  snap > "$BK/snap-after-$ts.json" || { bad "snapshot depois falhou"; return; }
  if cmp -s "$BK/snap-before-$ts.json" "$BK/snap-after-$ts.json"; then ok "contagens, integrity_check e checksums da mídia idênticos"; else bad "snapshots diferem: diff $BK/snap-before-$ts.json $BK/snap-after-$ts.json"; fi
  "$PY" - "$BK/snap-after-$ts.json" <<'PYCHK'
import json, sys
s = json.load(open(sys.argv[1])); c = s["counts"]
print("integrity_check:", s["integrity_check"], "| usuários:", c.get("users"), "| produções:", c.get("productions"), "| lançamentos de crédito:", c.get("credit_entries"), "| arquivos de mídia:", len(s["media"]), "| mp4:", sum(1 for k in s["media"] if k.endswith(".mp4")))
PYCHK
}

d(){ say "2d. SIGTERM e SIGKILL com produção em andamento (e2e em contêiner descartável, dados próprios; não toca no volume)"
  docker run --rm --entrypoint python -v "$PWD/scripts:/app/scripts:ro" -e E2E_PORT=8793 "$IMG" /app/scripts/e2e_shutdown.py; [ $? -eq 0 ] && ok "e2e de shutdown/retomada (SIGTERM e queda abrupta) passou no Linux do contêiner" || bad "e2e falhou"
  echo "Tempo e código de saída do serviço real:"; s=$(date +%s); docker compose kill -s SIGTERM "$SVC" >/dev/null; code=$(docker wait "$(docker compose ps -a -q "$SVC")"); echo "saiu em $(( $(date +%s)-s ))s com código $code"
  docker compose logs --no-log-prefix --tail 40 "$SVC" | grep -i -E 'shutdown|desligamento|interrupted|sigterm' | head
  docker compose up -d "$SVC"; }

case "$step" in a) a;; b) b;; c) c;; d) d;; all) a; b; c; d;; esac
echo; [ $fail -eq 0 ] && echo "RESULTADO: tudo OK" || echo "RESULTADO: há falhas"; exit $fail
