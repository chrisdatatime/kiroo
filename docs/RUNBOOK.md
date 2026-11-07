# Kiroo — Runbook de operação

Servidor HTTP da stdlib (`http.server`), **uma instância por pasta de dados**, SQLite em WAL. Esta página cobre as variáveis de rede, cadastro, proxy e operação. Veja `docs/DEPLOY-DIAGNOSTICO.md` para o panorama e os bloqueios restantes (backup, assets, Dockerfile, SMTP).

## Subir

```bash
studio ui --no-browser          # lê tudo de STUDIO_* (nada é obrigatório para rodar local)
```

Padrões seguros: escuta só em `127.0.0.1`, cadastro **fechado**, nenhum cabeçalho de proxy é confiável, logs JSON no stdout.

## Variáveis

### Rede e proxy

| Variável | Padrão | O que faz |
|---|---|---|
| `STUDIO_HOST` | `127.0.0.1` | Endereço de escuta. Em contêiner use `0.0.0.0`. |
| `STUDIO_PORT` | `PORT`, senão `8765` | Porta. `PORT` (Heroku/Railway/Fly) só vale sem `STUDIO_PORT`. `--port`/`--host` na CLI vencem. |
| `STUDIO_PUBLIC_HOST` | — | Host público (ex.: `app.kiroo.app`). Entra na lista de hosts, o cookie dele é `Secure` e os links de e-mail usam `https`. |
| `STUDIO_ALLOWED_HOSTS` | — | Lista (vírgula) de hosts aceitos no cabeçalho `Host` (anti DNS rebinding). Ex.: `app.kiroo.app,staging.kiroo.app`. Sem porta atrás de proxy. |
| `STUDIO_SECURE_COOKIE` | `0` | `1` = cookie `Secure` em todo host, **HSTS** (`max-age=31536000`) e links `https`. Use `1` em produção/staging. O cookie é sempre *host-only* (sem `Domain`). |
| `STUDIO_TRUST_PROXY` | `none` | `none`: usa o IP do socket. `cloudflare`: IP de `CF-Connecting-IP`. `forwarded`: primeiro item de `X-Forwarded-For`. Só o modo escolhido é lido; valor inválido cai no IP do socket. |

`forwarded` só é seguro se o proxy **substitui** o `X-Forwarded-For` que veio do cliente (Caddy/nginx com `proxy_set_header X-Forwarded-For $remote_addr`) e se a porta do Kiroo não é alcançável sem passar por ele. Com `none` atrás de um proxy, todos os clientes compartilham o IP do proxy e o limite de login por IP (8 falhas / 15 min) passa a barrar todo mundo junto.

Exemplo — produção e staging atrás da Cloudflare/Caddy:

```bash
STUDIO_HOST=0.0.0.0
STUDIO_PORT=8765
STUDIO_PUBLIC_HOST=app.kiroo.app
STUDIO_ALLOWED_HOSTS=app.kiroo.app,staging.kiroo.app
STUDIO_SECURE_COOKIE=1
STUDIO_TRUST_PROXY=cloudflare
```

Staging é outra instância com **outra** `STUDIO_DATA_DIR` e `STUDIO_PUBLIC_HOST=staging.kiroo.app`. Os cookies não vazam entre os dois (host-only).

### Cadastro e administrador

| Variável | Padrão | O que faz |
|---|---|---|
| `STUDIO_SIGNUP` | `closed` | `closed`: `POST /api/auth/signup` responde 403 sempre, em qualquer host (inclusive banco vazio). `invite`: exige o campo `invite` com um código de `STUDIO_INVITE_CODES` (sem códigos configurados, nada passa). `open`: qualquer pessoa cria conta (modo DEMO). O login com Google só cria conta nova em `open`. A tela de entrada lê o valor em `GET /api/config`. |
| `STUDIO_INVITE_CODES` | — | Códigos aceitos em `invite`, separados por vírgula. Use valores longos e aleatórios. **Provisório:** os códigos são fixos e **reutilizáveis** (qualquer pessoa com o código cria quantas contas quiser até você trocá-lo e reiniciar). Códigos de uso único, com expiração e vínculo ao convidado entram na Fase 12. A comparação é em tempo constante (`hmac.compare_digest` contra todos os códigos, sem parar no primeiro) e as tentativas erradas contam no limite por IP (8 / 15 min, HTTP 429). |
| `STUDIO_BOOTSTRAP_ADMIN_EMAIL` | — | No boot, cria esse administrador **sem senha** se não existir e envia o link de definir senha (30 min). Sem SMTP o link não é enviado nem registrado em produção: gere com `studio admin reset-link --email ...`. |

**Nenhuma conta vira administradora sozinha.** O primeiro admin nasce de uma destas formas:

```bash
studio admin create-user --email voce@kiroo.app --name "Seu Nome" --admin   # pede a senha no terminal
# ou: STUDIO_BOOTSTRAP_ADMIN_EMAIL=voce@kiroo.app no primeiro boot, depois:
studio admin reset-link --email voce@kiroo.app                              # se o link expirou / sem SMTP
```

`reset-link` usa `STUDIO_PUBLIC_HOST` (https) quando definido, senão `http://127.0.0.1:<porta>`. Outras contas: `studio admin create-user --email ... --name ...`, depois `allow-real` / `grant-credits` quando for o caso.

### Produção de vídeo

| Variável | Padrão | O que faz |
|---|---|---|
| `STUDIO_SHUTDOWN_GRACE_S` | `25` | Tolerância após `SIGTERM` para os laços de produção terminarem a etapa em curso (≥ 0). |
| `STUDIO_SHUTDOWN_SETTLE_S` | `3` | Janela de assentamento: depois da drenagem, o servidor espera isto antes de sair, sem escrever nada, para o Litestream fazer o último sync e o checkpoint pendente com contexto válido. Aceita de `0` a `15`; `0` desativa. Valor inválido impede a subida. |
| `STUDIO_STOP_GRACE_S` | `40` | Prazo que a plataforma dá entre o `SIGTERM` e o `SIGKILL` (igual ao `stop_grace_period` do compose). O servidor **recusa subir** se o desligamento não couber nele (ver *Prazo de parada* abaixo). |
| `STUDIO_ENV` | `dev` | `dev`/`staging`/`production`. Backup ausente: staging sobe com CRITICAL e `warnings` em `/readyz` (200); **production recusa subir**. Ver `docs/BACKUP.md`. |
| `STUDIO_ALLOW_NO_BACKUP` | — | `1` libera subir em production sem backup; `/readyz` devolve 503 com warning enquanto faltar. |
| `BACKUP_R2_ENDPOINT`, `BACKUP_R2_ACCESS_KEY_ID`, `BACKUP_R2_SECRET_ACCESS_KEY`, `BACKUP_BUCKET` | — | Backup no R2 (Litestream e `scripts/backup_media.sh`). As chaves são segredos. |
| `STUDIO_WAL_CHECKPOINT_S` | `300` | Intervalo do checkpoint PASSIVE do WAL (0 desliga). |
| `STUDIO_RESUME_MAX_ATTEMPTS` | `3` | Retomadas automáticas por produção antes de desistir (a produção vai a *pausada* e um evento `resume_abandoned` é gravado). O contador zera quando uma execução termina normalmente. |

**Desligamento (SIGTERM; no Windows, CTRL_BREAK_EVENT/SIGBREAK, porque o SIGTERM de lá mata o processo sem chamar o handler):** o servidor passa a responder `503` em `/readyz`, recusa criar/avançar produções (`503` + `Retry-After`), mantém as consultas, e espera até `STUDIO_SHUTDOWN_GRACE_S` os laços terminarem a etapa em curso (eles só param **entre** etapas, nunca no meio de uma chamada paga). O que sobrar fica marcado `interrupted` com um evento no log de eventos da produção. `Ctrl+C` espera só 3 s.
Depois disso o HTTP fecha, o servidor espera até 2 s as requisições em andamento e a thread do checkpoint periódico
(evento `drained`; vira WARNING se algo sobrou) e abre a **janela de assentamento** de `STUDIO_SHUTDOWN_SETTLE_S`
(eventos `settle_start` e `settle_end`, com `settle_s`, `duration_ms` e `interrupted`; `settle_skipped` com 0). Um
**segundo** sinal encerra a janela na hora (`settle_abort`) e o processo sai.

### Prazo de parada e janela de assentamento (Litestream)

**Por que a janela existe.** No contêiner o servidor roda como filho de `litestream replicate -exec`. Medido no ensaio
(16 rodadas `a` do passo 7, `docker stop -t 40` com produção e escritas): `error closing db … checkpoint:
mode=PASSIVE err=release read lock: context canceled` (saída 1) em 5 de 5 rodadas com WAL-sombra ≥ 1000 páginas e em
0 de 11 abaixo; `monitor error … RequestCanceled` (saída 0) em 5 de 16, 0,1–0,25 s depois de o servidor sair; nenhuma
escrita aceita perdida. Código do Litestream **v0.3.13** (tag `v0.3.13` de `benbjohnson/litestream`, a versão de
`docker/litestream.lock`):

- `cmd/litestream/main.go` (`case "replicate"`, l. 94–115): no sinal, `c.cmd.Process.Signal(sig)` e depois
  `<-c.execCh` ("waiting for exec process to close"); **só então** `c.Close()`. Se o filho sai sozinho, o mesmo
  `select` vai direto para o `Close`.
- `db.go` `NewDB` (l. 144): `db.ctx, db.cancel = context.WithCancel(context.Background())`; o único `db.cancel()` está
  em `DB.Close` (l. 321–322). Enquanto o Litestream espera o filho, `db.ctx` **não** está cancelado.
- `db.go` `Open` (l. 309–313) sobe `db.monitor()`, que a cada `MonitorInterval` (1 s) chama `db.Sync(db.ctx)`
  (l. 1425–1440); o `Sync` faz o checkpoint quando o WAL-sombra passa de `MinCheckpointPageN` (1000) ou pela regra de
  1 min (l. 774–790).
- `db.go` `init` (l. 487–489): `r.Start(db.ctx)`; `replica.go` `Start` (l. 113–130) deriva o contexto da réplica de
  `db.ctx` e sobe `monitor`, que a cada `sync-interval` (1 s) envia o que mudou (l. 668–700, `monitor error` na l. 699).
- Por que o fechamento falha: `DB.Close` cancela `db.ctx` **antes** do `Sync` final (l. 321–330). Um envio em voo da
  réplica é cancelado (`monitor error`), e se esse `Sync` final precisa de checkpoint, `execCheckpoint` (l. 1378–1422)
  reabre o read lock por `acquireReadLock`, que usa `tx.ExecContext(db.ctx, …)` (l. 611–624) já cancelado.

Conclusão: enquanto o servidor não sai, os monitores do banco e da réplica seguem ativos com contexto válido. A janela
de assentamento usa isso: o servidor já não escreve, o monitor faz o checkpoint pendente (e começa um WAL-sombra novo,
`checkpoint` + `initShadowWALFile`, l. 1301–1376 e 960–998) e a réplica envia o último segmento; quando o servidor sai,
o `Sync` final do `Close` não tem checkpoint a fazer e não há envio em voo. Caminho típico dentro da janela: tique do
monitor do banco (≤ 1 s) + tique da réplica (≤ 1 s) + envio (0,3–0,6 s medidos) ≈ 2,6 s no pior caso, por isso o
padrão 3 s. Se o envio ao R2 demorar mais, aumente (até 15) e refaça o orçamento.

**Limites conhecidos (não resolvidos pela janela):** uma produção que ainda estava no meio de uma chamada paga depois de
`STUDIO_SHUTDOWN_GRACE_S` fica marcada `interrupted`, mas a thread dela continua até o processo sair e pode gravar
durante a janela (o evento `drained` mostra `producoes ainda em chamada=N`). Se essa gravação cair no último segundo,
o `Close` volta a ter o que sincronizar. O mesmo vale para um `SIGKILL` antes do fim da janela.

**Orçamento (validado na subida).** O servidor recusa subir (mensagem com a conta) quando

```
STUDIO_SHUTDOWN_GRACE_S + 2 (fechamento do HTTP) + STUDIO_SHUTDOWN_SETTLE_S + 5 (fechamento do Litestream) > STUDIO_STOP_GRACE_S
```

Os 5 s do Litestream cobrem o `Sync` final do banco e da réplica no `Close`. No boot, o evento `shutdown_budget`
registra o mínimo calculado.

**Mínimo que a plataforma precisa dar ao processo (Fase 7):** `grace + 2 + settle + 5` segundos entre o SIGTERM e o
SIGKILL. Com os padrões: **25 + 2 + 3 + 5 = 35 s**; o compose usa `stop_grace_period: 40s` e `STUDIO_STOP_GRACE_S=40`.
Em outra plataforma, configure o prazo de parada (`kill_timeout`, `terminationGracePeriodSeconds`, `stop_grace_period`)
para **≥ 35 s** (recomendado 40 s) e exporte `STUDIO_STOP_GRACE_S` com esse mesmo valor; se a plataforma der menos,
reduza `STUDIO_SHUTDOWN_GRACE_S` (ex.: prazo de 30 s → grace 20). Exemplos: settle 0 → mínimo 32 s; settle 15 → 47 s.

**Retomada ao subir:** produções com `run_state` `running` (processo morreu) ou `interrupted` são retomadas sozinhas, a partir do estado salvo: tentativas e operações remotas já gravadas (`attempts`, `remote_op_id`) são reaproveitadas, então etapa paga não é refeita. Produções pausadas, encerradas ou esperando decisão humana não são religadas. Reservas de crédito órfãs continuam sendo liberadas pelo livro-razão após 15 min. Eventos: `interrupted`, `resumed`, `resume_abandoned`.

**Instância única:** ao subir, o servidor trava `STUDIO_DATA_DIR/studio.lock` (`flock`; `msvcrt` no Windows) e recusa subir se outro processo já usa a pasta, com mensagem clara. Não rode duas réplicas sobre o mesmo volume, nem em deploy *rolling* sem parar a antiga antes (use `Recreate`/`stop-first`).

### E-mail e segredos

Sem `STUDIO_SMTP_HOST` **e** com `STUDIO_SECURE_COOKIE=1`, o servidor **não** escreve códigos de confirmação nem links de senha no log (falha fechado: `sent=false` para o usuário e um aviso no boot). Sem `STUDIO_SECURE_COOKIE` (desenvolvimento) o conteúdo do e-mail ainda aparece no log do terminal. SMTP: `STUDIO_SMTP_HOST`, `STUDIO_SMTP_PORT`, `STUDIO_SMTP_USER`, `STUDIO_SMTP_PASSWORD`, `STUDIO_MAIL_FROM`.

## Endpoints de operação

| Rota | Uso |
|---|---|
| `GET /healthz` | Processo vivo (liveness). Não toca no banco. `200 {"status":"ok"}`. |
| `GET /readyz` | Prontidão (readiness). Abre o SQLite com transação de escrita e cria/remove um arquivo em `STUDIO_DATA_DIR`. `200` ou `503` com `checks` (`db`, `data_dir`, `accepting`). Durante o desligamento devolve `503`. |
| `GET /api/config` | Público: `{signup: closed\|invite\|open, google, email}`. |

Os dois primeiros ignoram a lista de hosts (sondas de contêiner usam IP interno) e não exigem autenticação nem devolvem dado sensível.

## Cabeçalhos, cache e compressão

- Em toda resposta: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, `X-Frame-Options: DENY`, `Content-Security-Policy` com `frame-ancestors 'none'` e `X-Request-Id`. `Strict-Transport-Security` só com `STUDIO_SECURE_COOKIE=1`.
- CSP do app: `script-src 'self'` (sem inline, sem `eval`), `img-src/connect-src/worker-src` com `blob:`/`data:` para o Phaser. O painel legado `/painel` tem CSP própria com script inline. Se uma tela nova violar a CSP, o console do navegador mostra `Content Security Policy`; ajuste `CSP_APP` em `server.py`.
- Cache: `/assets/*` com hash no nome → `public, max-age=31536000, immutable`; `index.html` → `no-cache`; `/api/*` → `no-store`; `/media/*` → `private, no-store`.
- gzip nos estáticos de texto (html, js, css, json, svg, manifest) quando o navegador aceita; cache em memória do comprimido. Vídeo/imagem não são comprimidos.

## Logs

JSON, uma linha por evento no stdout (`STUDIO_LOG_FORMAT=text` volta ao texto). Campos da requisição: `ts, level, logger, msg:"request", request_id, method, route (sem query), status, duration_ms, workspace_id`. Nunca entram e-mail, senha, código, token, query string nem texto de mensagens do chat. Os valores de `Settings.secret_values()` (chave do Gemini, Mercado Pago) são trocados por `***` em qualquer linha. Exceções registram só o tipo. `/healthz` e `/readyz` logam em nível DEBUG. O arquivo `data/logs/studio.log` continua existindo (texto) e deve ir para o volume de dados.

## Verificações de ponta a ponta (rodar antes de cada deploy relevante)

```bash
python scripts/e2e_shutdown.py   # sobe o servidor de verdade (simulated): sinal mid-produção, kill -9, retomada, lock
node scripts/csp-check.mjs       # Chrome headless logado em /?world=phaser: Phaser em WebGL, zero violação de CSP
```

`e2e_shutdown.py` cria uma pasta temporária, uma produção automática simulada e confere: `/readyz` 503, saída dentro de `STUDIO_SHUTDOWN_GRACE_S`, `run_state=interrupted` e evento, retomada sem duplicar `(cena, tipo, nº da tentativa)` e com os mesmos `attempts`/`remote_op_id`, queda brusca (processo morto sem aviso: `run_state` continua `running` e a retomada funciona) e a segunda instância recusada. `csp-check.mjs` usa o Chrome/Edge instalado (`CHROME=` para outro caminho) e o `frontend/dist` já construído; sem dependências npm novas.

**Por que a CSP tem `data:` e `blob:`:** testado derrubando-os de propósito: sem `data:` em `img-src`/`connect-src` o Phaser perde os quadros dos personagens e do mapa (ele os gera como imagens `data:`), e `blob:` é o que o `csp-check` exige de `worker-src`/`media-src`/`connect-src` para texturas e áudio. `script-src` continua `'self'` puro (sem inline, sem eval). Nenhuma diretiva além do necessário foi aberta.

## Problemas comuns

| Sintoma | Causa provável |
|---|---|
| `403 host não permitido` no navegador | Falta o host em `STUDIO_PUBLIC_HOST`/`STUDIO_ALLOWED_HOSTS`. |
| Todo mundo bloqueado por "muitas tentativas" | `STUDIO_TRUST_PROXY=none` atrás de proxy. Use `cloudflare` ou `forwarded`. |
| Login não persiste | `STUDIO_SECURE_COOKIE=1` acessando por `http://`. |
| `Outro processo do Kiroo já está usando ...` | Duas instâncias na mesma pasta de dados; pare a outra. Um lock sobrando após `kill -9` é solto pelo sistema operacional: apague só se tiver certeza de que não há processo. |
| Produção parada após deploy | Veja os eventos `interrupted`/`resumed`/`resume_abandoned`; se abandonada, retome pela interface. |
