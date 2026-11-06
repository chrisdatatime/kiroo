#!/usr/bin/env bash
# Verificação da Fase 3 (imagem Docker do Kiroo). Cada verificação termina em PASS, FAIL ou NAO_VERIFICADO.
#
#   bash scripts/verify_phase3.sh [--only ID[,ID...]] [--list] [--backup ARQUIVO.tgz] [--image kiroo:local]
#
# - NUNCA toca no serviço real nem no volume real: tudo que interrompe (SIGTERM/SIGKILL/recriar) roda num projeto Compose
#   descartável (nome kiroo-verify-<id>, volume próprio rotulado, porta efêmera). Só recursos com o rótulo desta execução são removidos.
# - Nunca imprime valores de credenciais; só nomes e booleanos.
# - NAO_VERIFICADO = a checagem não pôde rodar (comando ausente, erro do docker/python, saída vazia, timeout, controle falhou).
#   FAIL = rodou e encontrou problema (inclui qualquer "Traceback"). Saída != 0 se houver FAIL ou NAO_VERIFICADO.
# - Windows/Git Bash: caminhos de CONTÊINER passam por dk()/dc() (MSYS_NO_PATHCONV só nesses comandos); caminhos do HOST para
#   programas nativos passam por cygpath. Onde dá, usa streaming (docker save | python) em vez de arquivo.
set -u -o pipefail

IMG="${IMG:-kiroo:local}"; BACKUP=""; ONLY=""; LIST=0; TO="${TIMEOUT:-300}"
while [ $# -gt 0 ]; do case "$1" in
  --only) ONLY="${2:-}"; shift 2;; --list) LIST=1; shift;; --backup) BACKUP="${2:-}"; shift 2;; --image) IMG="${2:-}"; shift 2;;
  -h|--help) sed -n '2,14p' "$0"; exit 0;; *) echo "argumento desconhecido: $1" >&2; exit 2;; esac; done

IDS="2a-history 2a-env 2a-selftest 2a-layers-control 2a-layers-names 2a-layers-values 2a-fs 2a-token 2b-user 2b-write 2c-persist 2d-sigterm 2d-readyz 2d-sigkill kill9-e2e 2e-git backup-intact"
desc(){ case "$1" in
 2a-history) echo "docker history sem R2_/secret/.zip/nome do pacote";; 2a-env) echo "Config.Env da imagem sem R2_*";;
 2a-selftest) echo "autoteste do scanner de camadas (controles em imagem sintética)";;
 2a-layers-control) echo "controle positivo/negativo do scanner via docker commit + docker save (imagem descartável)";;
 2a-layers-names) echo "camadas: nome do ZIP, *.zip, assets fora do esperado, R2_* no Env";;
 2a-layers-values) echo "camadas: valores reais das 3 variáveis R2 (exige as variáveis no shell)";;
 2a-fs) echo "sistema de arquivos da imagem: sem *.zip; licenças presentes";; 2a-token) echo "repo sem referência a token de escrita/upload";;
 2b-user) echo "todos os processos do contêiner rodam como usuário não-root";; 2b-write) echo "/data gravável; /app /usr /etc não";;
 2c-persist) echo "persistência após down (sem -v) + up --force-recreate (descartável)";;
 2d-sigterm) echo "SIGTERM: tempo/código de saída, interrupted/resumed, retomada até o fim (descartável)";;
 2d-readyz) echo "/readyz vira 503 durante o desligamento (se mensurável)";; 2d-sigkill) echo "SIGKILL: retomada até o fim (descartável)";;
 kill9-e2e) echo "e2e de desligamento/kill-9 em Linux (SO do contêiner)";; 2e-git) echo "nenhum arquivo licenciado/.env/data/reference rastreado ou staged";;
 backup-intact) echo "checksum do backup do volume real igual no início e no fim";; esac; }

if [ "$LIST" = 1 ]; then for i in $IDS; do printf '%-18s %s\n' "$i" "$(desc "$i")"; done; echo; echo "grupos: 2a 2b 2c 2d 2e kill9 backup"; exit 0; fi

RUN="$(date +%s)-$$"; PROJ="kiroo-verify-$RUN"; LABEL="kiroo.verify=$RUN"; REAL_PROJECT="kiroo"; REAL_VOL="kiroo_kiroo-data"
TMP="$(mktemp -d)"; MSYS=0; case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) MSYS=1;; esac
PY="${PYTHON:-python3}"; command -v "$PY" >/dev/null 2>&1 || PY=python
hostp(){ if [ "$MSYS" = 1 ]; then cygpath -w "$1"; else printf '%s' "$1"; fi; }      # caminho nativo Windows (programas nativos)
hostm(){ if [ "$MSYS" = 1 ]; then cygpath -m "$1"; else printf '%s' "$1"; fi; }      # C:/... (YAML do Compose)
TOCMD=(); [ -z "${NO_TIMEOUT:-}" ] && command -v timeout >/dev/null 2>&1 && TOCMD=(timeout "$TO")                  # limite de tempo por comando docker
dk(){ MSYS_NO_PATHCONV=1 "${TOCMD[@]}" docker "$@"; }                                 # docker com caminhos de contêiner
COMPOSE_FILE_NATIVE=""
dc(){ MSYS_NO_PATHCONV=1 "${TOCMD[@]}" docker compose -p "$PROJ" -f "$COMPOSE_FILE_NATIVE" "$@"; }

selected(){ [ -z "$ONLY" ] && return 0; local g="${1%%-*}"; case ",$ONLY," in *",$1,"*|*",$g,"*|*",all,"*) return 0;; esac; return 1; }
RES_ID=(); RES_ST=(); RES_WHY=()
rec(){ RES_ID+=("$1"); RES_ST+=("$2"); RES_WHY+=("$3"); printf '[%s] %s — %s\n' "$2" "$1" "$3"; }
has_tb(){ grep -q 'Traceback' "$1" 2>/dev/null; }
jget(){ printf '%s' "$1" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1]))' "$2" 2>/dev/null; }

# ------------------------------------------------------------ ambiente descartável
ENV_STATE=""   # "" = não criado | ok | fail:<motivo>
assert_disposable(){
  case "$PROJ" in kiroo-verify-*) ;; *) echo "RECUSADO: projeto '$PROJ' não é descartável" >&2; return 1;; esac
  [ "$PROJ" != "$REAL_PROJECT" ] && [ "${PROJ}_data" != "$REAL_VOL" ] || { echo "RECUSADO: alvo é o real" >&2; return 1; }; }
cleanup(){
  [ -n "$COMPOSE_FILE_NATIVE" ] && assert_disposable 2>/dev/null && { dc down --remove-orphans >/dev/null 2>&1; }
  local c i v
  for c in $(dk ps -aq --filter "label=$LABEL" 2>/dev/null); do dk rm -f "$c" >/dev/null 2>&1; done
  for v in $(dk volume ls -q --filter "label=$LABEL" 2>/dev/null); do dk volume rm "$v" >/dev/null 2>&1; done
  for i in $(dk image ls -q --filter "label=$LABEL" 2>/dev/null); do dk image rm -f "$i" >/dev/null 2>&1; done
  rm -rf "$TMP"; }
trap cleanup EXIT

ensure_env(){
  [ -n "$ENV_STATE" ] && { [ "$ENV_STATE" = ok ]; return; }
  command -v docker >/dev/null 2>&1 || { ENV_STATE="fail:docker ausente no PATH"; return 1; }
  dk image inspect "$IMG" >/dev/null 2>&1 || { ENV_STATE="fail:imagem $IMG não encontrada"; return 1; }
  assert_disposable || { ENV_STATE="fail:guarda de descartável recusou"; return 1; }
  local f="$TMP/compose.yml" probe_src; probe_src="$(hostm "$(cd "$(dirname "$0")" && pwd)")"
  cat > "$f" <<YML
services:
  app:
    image: "$IMG"
    pull_policy: never
    init: true
    labels: { kiroo.verify: "$RUN" }
    ports: ["127.0.0.1::8765"]
    environment: ["STUDIO_MODE=simulated", "STUDIO_SHUTDOWN_GRACE_S=20", "STUDIO_POLL_INTERVAL_S=1"]
    volumes: ["data:/data", "${probe_src}:/probe:ro"]
    stop_grace_period: 40s
volumes:
  data:
    labels: { kiroo.verify: "$RUN" }
YML
  COMPOSE_FILE_NATIVE="$(hostp "$f")"
  dc up -d >"$TMP/up.out" 2>&1 || { ENV_STATE="fail:compose up falhou ($(tail -n1 "$TMP/up.out" | cut -c1-120))"; return 1; }
  wait_healthy 90 || { ENV_STATE="fail:serviço descartável não ficou saudável"; return 1; }
  ENV_STATE=ok; }
wait_healthy(){ local i; for i in $(seq 1 "${1:-60}"); do
  dc exec -T app python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8765/healthz', timeout=2)" >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
probe(){ dc exec -T app python /probe/container_probe.py "$@"; }
need_env(){ ensure_env || { rec "$1" NAO_VERIFICADO "${ENV_STATE#fail:}"; return 1; }; }

# ------------------------------------------------------------ verificações
c_2a_history(){ local out rc; out=$(dk history --no-trunc "$IMG" 2>&1); rc=$?
  [ $rc -ne 0 ] && { rec 2a-history NAO_VERIFICADO "docker history falhou (rc=$rc)"; return; }
  [ -z "$out" ] && { rec 2a-history NAO_VERIFICADO "docker history sem saída"; return; }
  local n; n=$(printf '%s\n' "$out" | grep -c -i -E 'R2_|secret|\.zip|kiroo-licensed-assets')
  [ "$n" -gt 0 ] && rec 2a-history FAIL "$n linha(s) do history casam R2_/secret/.zip/nome do pacote" || rec 2a-history PASS "history sem R2_, secret, .zip ou nome do pacote ($(printf '%s\n' "$out" | wc -l) camadas)"; }

c_2a_env(){ local raw rc; raw=$(dk image inspect "$IMG" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null); rc=$?
  [ $rc -ne 0 ] || [ -z "$raw" ] && { rec 2a-env NAO_VERIFICADO "inspect falhou ou Env vazio (rc=$rc)"; return; }
  if printf '%s\n' "$raw" | cut -d= -f1 | grep -q '^R2_'; then rec 2a-env FAIL "Config.Env tem variável R2_*"; else
    rec 2a-env PASS "Config.Env sem R2_* ($(printf '%s\n' "$raw" | wc -l) variáveis, só nomes comparados)"; fi; }

SELFTEST_OK=""; CTRL_OK=""
c_2a_selftest(){ local out rc; out=$("$PY" scripts/verify_image_layers.py --selftest 2>&1); rc=$?
  if [ $rc -eq 0 ] && ! printf '%s' "$out" | grep -q Traceback; then SELFTEST_OK=1; rec 2a-selftest PASS "scanner achou o marcador sintético e não achou o inexistente"
  else SELFTEST_OK=0; rec 2a-selftest FAIL "autoteste do scanner falhou (rc=$rc)"; fi; }

c_2a_layers_control(){
  [ -z "$SELFTEST_OK" ] && c_2a_selftest_quiet
  command -v docker >/dev/null 2>&1 && dk image inspect "$IMG" >/dev/null 2>&1 || { CTRL_OK=0; rec 2a-layers-control NAO_VERIFICADO "docker/imagem indisponível"; return; }
  local pos neg cid out rc ok
  pos="CTRL-POS-$(date +%s)-$RANDOM$RANDOM"; neg="CTRL-NEG-$RANDOM$RANDOM$RANDOM"
  cid=$(dk run -d --label "$LABEL" --entrypoint sh "$IMG" -c "echo $pos > /tmp/ctrl.txt; sleep 1" 2>/dev/null) || { CTRL_OK=0; rec 2a-layers-control NAO_VERIFICADO "não consegui criar o contêiner de controle"; return; }
  dk wait "$cid" >/dev/null 2>&1
  dk commit --change "LABEL kiroo.verify=$RUN" "$cid" "kiroo-verify-ctrl:$RUN" >/dev/null 2>&1 || { CTRL_OK=0; rec 2a-layers-control NAO_VERIFICADO "docker commit falhou"; return; }
  out=$(dk save "kiroo-verify-ctrl:$RUN" 2>"$TMP/ctrl.err" | KIROO_CTRL_POS="$pos" KIROO_CTRL_NEG="$neg" "$PY" scripts/verify_image_layers.py - --needle-env KIROO_CTRL_POS --needle-env KIROO_CTRL_NEG 2>&1); rc=$?
  if [ -z "$out" ] || printf '%s' "$out" | grep -q -e Traceback -e erro_execucao; then CTRL_OK=0; rec 2a-layers-control NAO_VERIFICADO "pipeline docker save|scanner não executou (rc=$rc)"; return; fi
  ok=$(jget "$out" "d['secret_in_content']['KIROO_CTRL_POS'] and not d['secret_in_content']['KIROO_CTRL_NEG']")
  if [ "$ok" = True ]; then CTRL_OK=1; rec 2a-layers-control PASS "controle positivo achado e negativo não achado, pelo mesmo pipeline docker save | scanner"
  else CTRL_OK=0; rec 2a-layers-control FAIL "o scanner NÃO achou o marcador plantado: varreduras de camadas ficam NAO_VERIFICADO"; fi; }
c_2a_selftest_quiet(){ if "$PY" scripts/verify_image_layers.py --selftest >/dev/null 2>&1; then SELFTEST_OK=1; else SELFTEST_OK=0; fi; }

LAYERS_JSON=""; LAYERS_RC=""
run_layers(){ [ -n "$LAYERS_RC" ] && return
  [ -z "$CTRL_OK" ] && c_2a_layers_control >/dev/null
  LAYERS_JSON=$(dk save "$IMG" 2>"$TMP/save.err" | "$PY" scripts/verify_image_layers.py - 2>&1); LAYERS_RC=$?; }
layers_guard(){ # $1=id ; retorna 1 (e registra NAO_VERIFICADO) se a varredura não é confiável
  run_layers
  [ "$SELFTEST_OK" = 1 ] && [ "$CTRL_OK" = 1 ] || { rec "$1" NAO_VERIFICADO "controles de sanidade do scanner não passaram"; return 1; }
  if [ -z "$LAYERS_JSON" ] || printf '%s' "$LAYERS_JSON" | grep -q -e Traceback -e erro_execucao || [ "$LAYERS_RC" -eq 3 ]; then
    rec "$1" NAO_VERIFICADO "varredura não rodou: $(printf '%s' "$LAYERS_JSON" | cut -c1-120)"; return 1; fi
  return 0; }
c_2a_layers_names(){ layers_guard 2a-layers-names || return
  local bad layers; bad=$(jget "$LAYERS_JSON" "d['zip_name_in_paths'] or d['zip_name_in_content'] or d['zip_files']>0 or d['unexpected_asset_paths']>0 or d['env_has_r2']"); layers=$(jget "$LAYERS_JSON" "d['layers']")
  if [ "$bad" = False ]; then rec 2a-layers-names PASS "$layers camadas varridas: sem nome do ZIP, *.zip, assets fora do esperado ou R2_* no Env"
  elif [ "$bad" = True ]; then rec 2a-layers-names FAIL "achado: $(jget "$LAYERS_JSON" "{k:v for k,v in d.items() if k in ('zip_name_in_paths','zip_name_in_content','zip_files','unexpected_asset_paths','env_has_r2')}")"
  else rec 2a-layers-names NAO_VERIFICADO "não consegui interpretar a saída do scanner"; fi; }
c_2a_layers_values(){ layers_guard 2a-layers-values || return
  local present; present=$(jget "$LAYERS_JSON" "all(d['secrets_present_in_env'][k] for k in ('R2_ACCOUNT_ID','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY'))")
  if [ "$present" != True ]; then rec 2a-layers-values NAO_VERIFICADO "R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY não estão todas definidas neste shell (presença: $(jget "$LAYERS_JSON" "d['secrets_present_in_env']"))"; return; fi
  if [ "$(jget "$LAYERS_JSON" "any(d['secret_in_content'].values())")" = True ]; then rec 2a-layers-values FAIL "valor de credencial R2 encontrado em camada: $(jget "$LAYERS_JSON" "d['secret_in_content']")"
  else rec 2a-layers-values PASS "os 3 valores reais não aparecem em nenhum dos $(jget "$LAYERS_JSON" "d['files_scanned']") arquivos varridos"; fi; }

c_2a_fs(){ local out rc; out=$(dk run --rm --entrypoint sh "$IMG" -c 'find / -xdev \( -name "*.zip" -o -name "*kiroo-licensed*" \) 2>/dev/null | head -20; echo "---LIC"; ls /app/licenses 2>/dev/null; echo "---ASSETS"; ls /app/assets 2>/dev/null; ls -d /app/assets/bia /reference/bia 2>/dev/null' 2>&1); rc=$?
  { [ $rc -ne 0 ] || ! printf '%s' "$out" | grep -q -- '---LIC'; } && { rec 2a-fs NAO_VERIFICADO "docker run falhou ou saída incompleta (rc=$rc)"; return; }
  has_tb <(printf '%s' "$out") && { rec 2a-fs FAIL "Traceback na saída"; return; }
  local zips lic bia; zips=$(printf '%s
' "$out" | awk '/^---LIC/{exit} NF' | wc -l); lic=$(printf '%s
' "$out" | awk '/^---LIC/{f=1;next} /^---ASSETS/{f=0} f' | grep -c -i limezu); bia=$(printf '%s
' "$out" | awk '/^---ASSETS/{f=1;next} f' | grep -c bia)
  if [ "$zips" -gt 0 ] || [ "$bia" -gt 0 ]; then rec 2a-fs FAIL "$zips arquivo(s) .zip/pacote e $bia caminho(s) bia na imagem"
  elif [ "$lic" -lt 1 ]; then rec 2a-fs FAIL "licenças LimeZu não encontradas em /app/licenses"
  else rec 2a-fs PASS "nenhum *.zip; $lic licença(s) LimeZu em /app/licenses; sem /app/assets/bia nem /reference/bia na imagem"; fi; }

c_2a_token(){ command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1 || { rec 2a-token NAO_VERIFICADO "git/repositório indisponível"; return; }
  local hits; hits=$(git grep -n -i -E 'write.?token|r2_write|upload.?token|put_object|upload_file' -- . ':!tests/*' ':!docs/*' ':!scripts/verify_*' ':!scripts/container_probe.py' 2>/dev/null | wc -l)
  [ "$hits" -eq 0 ] && rec 2a-token PASS "nenhuma referência a token de escrita/upload nos arquivos rastreados (só nomes; valores não são verificáveis)" || rec 2a-token FAIL "$hits referência(s): rode git grep -n -i -E 'write.?token|put_object|upload_file'"; }

c_2b_user(){ need_env 2b-user || return
  local out; out=$(dc exec -T app sh -c 'echo "id=$(id -u):$(id -un)"; for p in /proc/[0-9]*; do u=$(sed -n "s/^Uid:[[:space:]]*\([0-9]*\).*/\1/p" $p/status 2>/dev/null); [ -n "$u" ] && echo "uid=$u"; done' 2>&1)
  [ -z "$out" ] && { rec 2b-user NAO_VERIFICADO "sem saída do exec"; return; }
  has_tb <(printf '%s' "$out") && { rec 2b-user FAIL "Traceback"; return; }
  local idl uids nonuser; idl=$(printf '%s\n' "$out" | grep '^id='); uids=$(printf '%s\n' "$out" | grep -c '^uid='); nonuser=$(printf '%s\n' "$out" | grep '^uid=' | grep -v -c '^uid=10001$')
  [ "$uids" -eq 0 ] && { rec 2b-user NAO_VERIFICADO "não consegui listar processos"; return; }
  if [ "$nonuser" -eq 0 ] && [ "$idl" = "id=10001:kiroo" ]; then rec 2b-user PASS "$uids processo(s), todos uid 10001 (kiroo); exec como $idl"; else rec 2b-user FAIL "processos fora do uid 10001: $nonuser; $idl"; fi; }
c_2b_write(){ need_env 2b-write || return
  local out; out=$(dc exec -T app sh -c 'touch /data/.w 2>/dev/null && rm -f /data/.w && echo DATA_W=1 || echo DATA_W=0; for d in /app /usr /etc; do touch $d/.w 2>/dev/null && { rm -f $d/.w; echo "W$d=1"; } || echo "W$d=0"; done' 2>&1)
  printf '%s' "$out" | grep -q '^DATA_W=' || { rec 2b-write NAO_VERIFICADO "saída inesperada do exec"; return; }
  if printf '%s\n' "$out" | grep -q '^DATA_W=1$' && ! printf '%s\n' "$out" | grep -q -E '^W/(app|usr|etc)=1$'; then rec 2b-write PASS "/data gravável; /app, /usr e /etc não"
  else rec 2b-write FAIL "$(printf '%s' "$out" | tr '\n' ' ')"; fi; }

c_2c_persist(){ need_env 2c-persist || return
  local seed pid s1 s2 st
  seed=$(probe seed 2>&1); pid=$(jget "$seed" "d['pid']"); [ -z "$pid" ] && { rec 2c-persist NAO_VERIFICADO "seed falhou: $(printf '%s' "$seed" | tail -n1 | cut -c1-120)"; return; }
  st=$(probe wait "$pid" 2>&1); [ "$(jget "$st" "d.get('timeout',False)")" = False ] || { rec 2c-persist NAO_VERIFICADO "produção simulada não terminou a tempo"; return; }
  s1=$(probe snapshot 2>&1); has_tb <(printf '%s' "$s1") && { rec 2c-persist FAIL "Traceback no snapshot"; return; }
  printf '%s' "$s1" > "$TMP/s1.json"
  dc down >/dev/null 2>&1 || { rec 2c-persist NAO_VERIFICADO "compose down falhou"; return; }                # SEM -v
  dc up -d --force-recreate >/dev/null 2>&1 || { rec 2c-persist NAO_VERIFICADO "compose up --force-recreate falhou"; return; }
  wait_healthy 90 || { rec 2c-persist NAO_VERIFICADO "serviço não voltou saudável"; return; }
  s2=$(probe snapshot 2>&1); has_tb <(printf '%s' "$s2") && { rec 2c-persist FAIL "Traceback no snapshot pós-recriar"; return; }
  printf '%s' "$s2" > "$TMP/s2.json"
  local users prods credits mp4 ic
  users=$(jget "$s2" "d['counts'].get('users')"); prods=$(jget "$s2" "d['counts'].get('productions')"); credits=$(jget "$s2" "d['counts'].get('credit_entries')")
  mp4=$(jget "$s2" "sum(1 for k in d['media'] if k.endswith('.mp4'))"); ic=$(jget "$s2" "d['integrity_check']")
  if [ -z "$users" ] || [ -z "$ic" ]; then rec 2c-persist NAO_VERIFICADO "snapshot ilegível"; return; fi
  if ! cmp -s "$TMP/s1.json" "$TMP/s2.json"; then rec 2c-persist FAIL "snapshots diferem após recriar (contagens/mídia)"; return; fi
  if [ "$ic" != ok ] || [ "${users:-0}" -lt 1 ] || [ "${prods:-0}" -lt 1 ]; then rec 2c-persist FAIL "integrity_check=$ic users=$users productions=$prods"; return; fi
  [ "${mp4:-0}" -ge 1 ] && rec 2c-persist PASS "idênticos após recriar: users=$users productions=$prods credit_entries=$credits mp4=$mp4 integrity_check=ok" \
    || rec 2c-persist PASS "idênticos após recriar: users=$users productions=$prods credit_entries=$credits integrity_check=ok (ATENÇÃO: nenhum .mp4 nesta produção simulada)"; }

new_prod(){ local seed; seed=$(probe seed 2>&1); NP_PID=$(jget "$seed" "d['pid']"); [ -n "$NP_PID" ] && [ "$(jget "$(probe wait-attempts "$NP_PID" 1 2>&1)" "d['ok']")" = True ]; }
final_ok(){ # $1=pid $2=id $3=esperaEventos(regex) ; avalia estado final após retomada
  local st; st=$(probe wait "$1" 2>&1); has_tb <(printf '%s' "$st") && { rec "$2" FAIL "Traceback na sonda"; return 1; }
  [ "$(jget "$st" "d.get('timeout',False)")" = False ] || { rec "$2" NAO_VERIFICADO "a produção não terminou após a retomada (timeout)"; return 1; }
  local fin dup ev; fin=$(jget "$st" "d['status']"); ev=$(jget "$st" "d['events']"); dup=$(jget "$st" "len(d['attempts'])-len({(a[1],a[2],a[3]) for a in d['attempts']})")
  case "$fin" in awaiting_final_review|completed) ;; *) rec "$2" FAIL "status final=$fin events=$ev"; return 1;; esac
  [ "$dup" = 0 ] || { rec "$2" FAIL "$dup tentativa(s) duplicada(s) (cena, tipo, nº) após a retomada"; return 1; }
  printf '%s' "$ev" | grep -q -E "$3" || { rec "$2" FAIL "eventos esperados ($3) ausentes: $ev"; return 1; }
  FIN_DESC="status=$fin events=$ev tentativas=$(jget "$st" "d['n_attempts']") sem duplicatas"; return 0; }

READYZ_RES=""
c_2d_sigterm(){ need_env 2d-sigterm || return
  new_prod || { rec 2d-sigterm NAO_VERIFICADO "não consegui iniciar produção simulada em andamento"; return; }
  local pid="$NP_PID" port cid t0 t1 code
  port=$(dc port app 8765 2>/dev/null | tail -n1 | sed 's/.*://'); cid=$(dc ps -q app)
  ( "$PY" - "$port" > "$TMP/readyz.out" 2>&1 <<'PYR'
import sys, time, http.client
port = int(sys.argv[1]); end = time.time() + 60; seen = None; last = None
while time.time() < end:
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=1); c.request("GET", "/readyz"); last = c.getresponse().status
        if last == 503 and seen is None: seen = time.time()
    except OSError:
        if last is not None: break
    time.sleep(0.05)
print("seen503=%s last=%s" % (seen is not None, last))
PYR
  ) &
  local poller=$!; sleep 1
  t0=$(date +%s); dc kill -s SIGTERM app >/dev/null 2>&1; code=$(dk wait "$cid" 2>/dev/null); t1=$(date +%s); wait "$poller" 2>/dev/null
  READYZ_RES=$(cat "$TMP/readyz.out" 2>/dev/null)
  [ -z "$code" ] && { rec 2d-sigterm NAO_VERIFICADO "docker wait sem código de saída"; return; }
  local took=$((t1-t0)); local logs; logs=$(dc logs --no-log-prefix app 2>&1 | tail -n 60)
  dc start app >/dev/null 2>&1; wait_healthy 90 || { rec 2d-sigterm NAO_VERIFICADO "não voltou saudável após o SIGTERM"; return; }
  if [ "$code" != 0 ] || [ "$took" -gt 30 ]; then rec 2d-sigterm FAIL "saída em ${took}s com código $code (esperado 0 em até ~30s)"; return; fi
  final_ok "$pid" 2d-sigterm 'interrupted.*resumed' || return
  rec 2d-sigterm PASS "saiu em ${took}s com código 0; $FIN_DESC"; }
c_2d_readyz(){ need_env 2d-readyz || return
  if [ -z "$READYZ_RES" ]; then rec 2d-readyz NAO_VERIFICADO "2d-sigterm não rodou nesta execução (rode --only 2d-sigterm,2d-readyz)"; return; fi
  case "$READYZ_RES" in *Traceback*) rec 2d-readyz FAIL "Traceback no poller";; *"seen503=True"*) rec 2d-readyz PASS "/readyz respondeu 503 durante o desligamento ($READYZ_RES)";;
    *) rec 2d-readyz NAO_VERIFICADO "503 não observado ($READYZ_RES): janela curta ou porta não observável; não é prova de falha";; esac; }
c_2d_sigkill(){ need_env 2d-sigkill || return
  new_prod || { rec 2d-sigkill NAO_VERIFICADO "não consegui iniciar produção simulada em andamento"; return; }
  local pid="$NP_PID" cid code; cid=$(dc ps -q app)
  dc kill -s SIGKILL app >/dev/null 2>&1; code=$(dk wait "$cid" 2>/dev/null)
  [ -z "$code" ] && { rec 2d-sigkill NAO_VERIFICADO "docker wait sem código"; return; }
  dc start app >/dev/null 2>&1; wait_healthy 90 || { rec 2d-sigkill NAO_VERIFICADO "não voltou saudável após o SIGKILL"; return; }
  [ "$code" = 137 ] || { rec 2d-sigkill NAO_VERIFICADO "código de saída $code (esperado 137): o SIGKILL pode não ter sido o motivo da parada"; return; }
  final_ok "$pid" 2d-sigkill 'resumed' || return
  rec 2d-sigkill PASS "código 137; retomou até o fim: $FIN_DESC"; }

c_kill9_e2e(){ need_env kill9-e2e || return
  local out rc; out=$(dc exec -T -e E2E_PORT=8793 app python /probe/e2e_shutdown.py 2>&1); rc=$?
  printf '%s' "$out" > "$TMP/e2e.out"; local ok bad; ok=$(grep -c '^\[OK\]' "$TMP/e2e.out"); bad=$(grep -c '^\[FALHOU\]' "$TMP/e2e.out")
  if has_tb "$TMP/e2e.out"; then rec kill9-e2e FAIL "Traceback no e2e (rc=$rc)"
  elif [ $((ok+bad)) -eq 0 ]; then rec kill9-e2e NAO_VERIFICADO "e2e sem nenhuma verificação na saída (rc=$rc): $(printf '%s' "$out" | tail -n1 | cut -c1-100)"
  elif [ "$bad" -gt 0 ] || [ $rc -ne 0 ]; then rec kill9-e2e FAIL "$bad falha(s), $ok ok: $(grep '^\[FALHOU\]' "$TMP/e2e.out" | head -3 | cut -c1-110 | tr '\n' '|')"
  else rec kill9-e2e PASS "$ok verificações ok (graceful e kill-9, no Linux do contêiner)"; fi; }

c_2e_git(){ command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1 || { rec 2e-git NAO_VERIFICADO "git/repositório indisponível"; return; }
  local out rc; out=$("$PY" scripts/check_licensed_files.py 2>&1); rc=$?
  has_tb <(printf '%s' "$out") && { rec 2e-git FAIL "Traceback no check"; return; }
  [ -z "$out" ] && { rec 2e-git NAO_VERIFICADO "check sem saída (rc=$rc)"; return; }
  [ $rc -ne 0 ] && { rec 2e-git FAIL "$(printf '%s' "$out" | head -n3 | tr '\n' ' ')"; return; }
  local bad; bad=$( { git ls-files; git diff --cached --name-only; } | grep -E '^(\.env$|\.env\.[^d]|data/|reference/)|\.sqlite3' | grep -v -E '^\.env\.example$' | wc -l)
  [ "$bad" -eq 0 ] && rec 2e-git PASS "check_licensed_files ok; nada de .env/data/reference rastreado ou staged" || rec 2e-git FAIL "$bad arquivo(s) sensíveis rastreados/staged"; }

sha_of(){ if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else "$PY" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$(hostp "$1")"; fi; }
BK_SUM0=""
backup_start(){ [ -z "$BACKUP" ] && BACKUP=$(ls -1t "$HOME"/kiroo-backups/data-*.tgz 2>/dev/null | head -n1)
  [ -n "$BACKUP" ] && [ -f "$BACKUP" ] && BK_SUM0=$(sha_of "$BACKUP"); }
c_backup_intact(){ [ -z "$BK_SUM0" ] && { rec backup-intact NAO_VERIFICADO "sem arquivo de backup (use --backup ARQUIVO.tgz)"; return; }
  local s1; s1=$(sha_of "$BACKUP"); [ -z "$s1" ] && { rec backup-intact NAO_VERIFICADO "não consegui calcular o checksum final"; return; }
  [ "$s1" = "$BK_SUM0" ] && rec backup-intact PASS "checksum do backup idêntico no início e no fim (sha256 ${s1:0:12}…)" || rec backup-intact FAIL "o arquivo de backup MUDOU durante a verificação"; }

# ------------------------------------------------------------ execução
for s in $(printf '%s' "$ONLY" | tr ',' ' '); do case " $IDS all 2a 2b 2c 2d 2e kill9 backup " in *" $s "*) ;; *) echo "verificação/grupo desconhecido: $s (use --list)" >&2; exit 2;; esac; done
selected backup-intact && backup_start
[ -n "$BK_SUM0" ] && echo "backup monitorado: $(basename "$BACKUP") sha256=${BK_SUM0:0:12}… (somente leitura)"
for id in $IDS; do selected "$id" || continue; "c_$(printf '%s' "$id" | tr '-' '_')"; done

# ------------------------------------------------------------ resumo
np=0; nf=0; nn=0; rerun=""
for i in "${!RES_ID[@]}"; do case "${RES_ST[$i]}" in PASS) np=$((np+1));; FAIL) nf=$((nf+1)); rerun="$rerun,${RES_ID[$i]}";; *) nn=$((nn+1)); rerun="$rerun,${RES_ID[$i]}";; esac; done
printf '\n== RESUMO: PASS=%d FAIL=%d NAO_VERIFICADO=%d ==\n' "$np" "$nf" "$nn"
if [ -n "$rerun" ]; then
  bk=""; [ -n "$BACKUP" ] && bk=" --backup \"$BACKUP\""
  echo "Repetir só o que não passou (Git Bash, na raiz do repo):"; echo "  cd \"$(pwd)\" && bash scripts/verify_phase3.sh --only ${rerun#,}$bk"; fi
[ "$nf" -eq 0 ] && [ "$nn" -eq 0 ] && [ "$np" -gt 0 ] && exit 0 || exit 1
