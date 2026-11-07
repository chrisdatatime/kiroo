# Kiroo — Diagnóstico de deploy (Fase 0)

Levantamento somente-leitura feito em 2026-11-05 na branch `chore/rebrand-kiroo` (commit `c14104f`). Nenhum arquivo de código foi alterado. Valores de segredos não aparecem aqui.

**Não verificado:** `pip-audit` não está instalado e não foi rodado. Nenhuma suíte de testes foi executada. Os tempos de job (item 4) são deduzidos do código, não medidos.

---

## 1. Backend

| Item | Situação |
|---|---|
| Linguagem | Python (`requires-python >=3.11`). O venv local usa **3.15.0** (pré-lançamento). Fixe 3.12 ou 3.13 no servidor e valide os testes lá. |
| Framework | **Nenhum.** Servidor HTTP da stdlib: `http.server.ThreadingHTTPServer` com `BaseHTTPRequestHandler` ([server.py](../src/studio/web/server.py)). Sem ASGI/WSGI, sem Gunicorn/Uvicorn. |
| Ponto de entrada | CLI `studio` (`studio.cli:main`, também `python -m studio`). Subcomandos: `doctor`, `list`, `new`, `demo`, `run`, `ui`, `publish`, `admin …` etc. |
| Subir local | `python -m studio ui --no-browser --port 8765` (ver [.claude/launch.json](../.claude/launch.json)). |
| Porta / bind | Padrão **8765**. Bind **fixo em `127.0.0.1`** (`serve()`, [server.py:825](../src/studio/web/server.py:825)); não há opção de host. |
| Exposição pública hoje | `studio publish` abre um túnel Cloudflare "quick" (`cloudflared`), que muda de endereço a cada reinício. É um mecanismo de demo, não de produção. |
| Dependências Python | Core: `pydantic>=2.7`, `python-dotenv>=1.0`. Extras: `real` = `google-genai>=2.30`, `chat` = `anthropic` (sem versão), `dev` = `pytest>=8`. |
| Instalado no venv local | pydantic 2.14.1, python-dotenv 1.2.4, google-genai 2.33.0, pytest 9.1.1. O **`anthropic` não está instalado**, então o chat dos agentes cai no modo "sem IA" neste ambiente. |
| Lockfile Python | **Não existe** (só `pyproject.toml` com faixas `>=`). Os builds não são reproduzíveis. |
| Testes | `tests/` (pytest). A CI roda **apenas o frontend** ([.github/workflows/check.yml](../.github/workflows/check.yml)). O backend não tem CI. |

Observação: o servidor trata tudo em threads dentro do próprio processo. Não há health-check endpoint nem log estruturado por padrão.

## 2. Banco de dados

- **SQLite**, arquivo único `data/studio.sqlite3` (937 KB hoje), modo WAL, `foreign_keys=ON`, conexão aberta por requisição (`Database(path)`) com `check_same_thread=False` ([db.py:125](../src/studio/db.py:125)).
- Existe também `data/studio.db` com 0 bytes (resíduo; ignorável).
- **Tabelas** (com contagem de linhas na base local):
  - Produção: `productions` (10), `scenes` (27), `attempts` (96), `reviews` (78), `events` (551).
  - Contas: `users` (7), `workspaces` (7), `memberships` (7), `sessions` (5), `login_attempts`, `email_codes`, `password_resets` (4).
  - Créditos: `credit_entries` (10).
  - Treino dos agentes: `training_state`, `training_versions`, `training_tests`.
  - Música: `music_tracks`, `music_favorites`.
  - Chat: `chat_log` (4).
- **Migração: não há sistema de migração.** Cada módulo roda `CREATE TABLE IF NOT EXISTS` no construtor, e as colunas novas entram por `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` espalhados em [db.py:132](../src/studio/db.py:132) e [accounts.py:114](../src/studio/accounts.py:114). Não há versão de schema (`user_version`), nem down-migration, nem ordem garantida entre módulos. Funciona para SQLite de nó único. Para Postgres precisa ser refeito.
- Concorrência: usa `threading.Lock` no módulo de créditos (`_LOCK`). Isso só protege **um único processo**. Com mais de um worker/réplica, o livro-razão de créditos perde a proteção.
- Os 7 usuários e a base local são dados reais/de teste do desenvolvedor. Decidir se migram ou se o servidor novo começa vazio.

## 3. Arquivos (imagens, vídeos, assets)

Tudo é gravado em disco local, sem camada de abstração para objeto (S3/R2).

| Local | Conteúdo | Tamanho hoje | Git |
|---|---|---|---|
| `data/productions/<prod_id>/` | imagens, takes, `final.mp4`, `cover.jpg`, JSONs (10 produções) | **191 MB** | ignorado |
| `data/uploads/` | uploads dos usuários (base64 → arquivo) | 260 KB | ignorado |
| `data/sound_cache/` | trilhas/SFX gerados com ffmpeg | 13 MB | ignorado |
| `data/sim_ops`, `data/logs`, `data/demo_inputs`, `data/agents.json` | estado do modo simulado, logs, config da UI | ~1 MB | ignorado |
| `data/workspaces/<ws_id>/assets/` | referências próprias de cada workspace | (ainda não criado) | ignorado |
| `assets/bia/` | foto de referência da apresentadora (3,2 MB) | 3,2 MB | ignorado |
| `assets/characters/` | spritesheets LimeZu e do estúdio (5,2 MB) | 5,2 MB | **ignorado (licença)** |
| `assets/tilesets/` | tilesets LimeZu (3,3 MB) | 3,3 MB | **ignorado (licença)** |
| `assets/maps/` | `office.tmj/.tmx` (324 KB) | 324 KB | versionado |
| `frontend/src/assets/home/` | imagens da landing geradas por `tools/render_home.py` | — | **ignorado** |

Total em `data/` ≈ **205 MB** e cresce uns 20 MB por produção. `data/` deve ir para volume persistente com backup.

Pontos específicos:

- **`assets/characters/` e `assets/tilesets/` são incorporados ao build do frontend** via `import.meta.glob` em tempo de build ([WorldPhaser.jsx:15](../frontend/src/ui/WorldPhaser.jsx:15), [WorldPhaser.jsx:22](../frontend/src/ui/WorldPhaser.jsx:22)). Num clone limpo, sem esses diretórios, o `npm run build` **passa** (é o que a CI faz), mas gera um jogo sem personagens e sem tilesets (cai no "feijão"). O mesmo vale para `frontend/src/assets/home/` e a landing ([art.js:3](../frontend/src/landing/art.js:3)). Para o build de produção, os assets precisam ser entregues ao builder por fora do git (volume, secret store, bucket privado).
- **Licença:** os tilesets e personagens são de licença comercial e, quando o `dist/` é publicado, os PNGs seguem para o navegador do usuário. Confirmar que a licença LimeZu cobre essa distribuição num SaaS.
- `assets/bia/PERFIL BIA.jpg` é lido pelo `doctor` e pelo preparo do produto como referência da apresentadora. Sem ela, o modo real perde a referência. É uma foto pessoal (por isso o ignore).
- Diretório untracked de terceiros (escritório virtual) (6,3 MB, projeto de terceiros com `Procfile`/`netlify.toml`/`yarn.lock`, licença própria): **não é parte do deploy** e não deve ser commitado por engano. Também há um `vite.config.js.timestamp-*.mjs` untracked na pasta do frontend, sobra do Vite.
- Mídia é servida pela própria API em `/media/<prod_id>/…` com checagem de dono e suporte a `Range`. Funciona, mas toda leitura de vídeo passa pelo processo Python.

## 4. Orquestrador de vídeo (`orchestrator.py`)

- **Roda dentro do processo da API.** `App.start_run` cria uma `threading.Thread(daemon=True)` por produção ([server.py:171](../src/studio/web/server.py:171)), e o `Orchestrator.run()` itera lá. Há ainda um `ThreadPoolExecutor(max_workers=6)` de revisões. Não existe fila, worker separado, nem retomada automática: se o processo reinicia, a thread morre. O estado fica no SQLite (a produção continua "em andamento" até alguém chamar `run` de novo), mas nada religa sozinho. Há um tratamento de reserva órfã (15 min) no livro de créditos.
- **Duração do job:** não medida. Pelo código, uma produção são 3 cenas × (imagem + revisão + vídeo + revisão), com `poll_interval_s` (10 s padrão, 4 s no `.env.example`) e portões humanos de aprovação. A geração de vídeo é assíncrona no provedor (polling), e há `sync_timeout_s` de 300 s (imagem/texto) e 900 s (vídeo). A edição final com ffmpeg tem `timeout=900`. Estimativa: **minutos por etapa e dezenas de minutos por produção**, com pausas esperando o humano. Isso exige um processo de longa duração, incompatível com serverless de timeout curto.
- **ffmpeg / binários:** sim, [ffmpeg.py](../src/studio/ffmpeg.py) chama `ffmpeg` e `ffprobe` via `subprocess` (montagem, mixagem de áudio, `still_to_clip`, extração de quadros/capa, níveis de áudio). Também gera música e SFX sintetizados com filtros lavfi. Sem ffmpeg o `doctor` acusa e a montagem falha. Usa uma fonte (`STUDIO_FONT_FILE`) para texto sobreposto.
- **APIs externas chamadas:**
  - **Google Gemini** (`google-genai`): planejamento, revisão multimodal, imagem (nano-banana) e vídeo (Omni Flash). Só em `STUDIO_MODE=real`.
  - **Anthropic** (opcional): chat dos agentes, modelo `claude-haiku-5-5`, com limites por usuário/dia e teto global de tokens.
  - **Google OAuth** (login com Google), via `urllib`, e **SMTP** para e-mail. Ambos opcionais.
  - Cloudflare (`cloudflared`) só no `publish`.
  - **Mercado Pago:** ainda não implementado (só há `MP_ACCESS_TOKEN`/`MP_WEBHOOK_SECRET` referenciados em `secret_values()` e nos docs; Fase D).
- No modo `simulated` nada externo é chamado, mas as produções ainda gravam arquivos e passam por ffmpeg.

## 5. Autenticação

Existe e é de produção razoável, implementada à mão ([accounts.py](../src/studio/accounts.py), [server.py](../src/studio/web/server.py)):

- **Cadastro por e-mail + senha** (`/api/auth/signup`), login, logout, "esqueci minha senha" e confirmação de e-mail por código. Senha com `scrypt` (n=2^14), mínimo 10 caracteres.
- **Sessão por cookie** `studio_session` (HttpOnly, SameSite=Lax, 30 dias, `Secure` só se `STUDIO_SECURE_COOKIE=1` ou host público). O token é guardado hasheado (SHA-256) na tabela `sessions`.
- **CSRF** por cabeçalho `X-Studio-Token` em todo POST, mais `X-Studio-Client: game` exigido nas rotas de auth.
- Proteção contra DNS rebinding por lista de hosts permitidos; limite de tentativas de login (8 falhas / 15 min), por e-mail+IP.
- **Login com Google** opcional (OAuth 2.0 no servidor).
- **Multi-tenant por workspace:** cada produção, mídia, gasto e teto pertencem a um workspace; acesso fora dele dá 404. `users`/`workspaces`/`memberships`.
- **Papéis:** `is_platform_admin`. **A primeira conta criada vira administradora** (`_first_account`), recebe as produções órfãs, modo real liberado e isenção de créditos.
- Contas novas ficam em **DEMO** (modo simulado) até o admin liberar o modo real (`studio admin allow-real`).
- Administração é só pela **CLI** (`studio admin create-user | allow-real | reset-link | grant-credits | …`), sem painel web.

Riscos para produção (detalhes em "Bloqueios"):

- O fechamento do cadastro depende de `STUDIO_PUBLIC_HOST` estar definido. Sem ele, `/api/auth/signup` fica **aberto** e, num banco vazio, quem chegar primeiro vira **admin da plataforma**. O `SIGNUP_OPEN` do frontend ([Auth.jsx:17](../frontend/src/ui/Auth.jsx:17)) é só cosmético (`hostname === localhost`).
- O IP do cliente só é lido de `cf-connecting-ip` quando o host é o público configurado; atrás de outro proxy o IP vira `"local"`/`"publico"` e o limite de login passa a valer por e-mail, não por IP.
- Sem SMTP, o código de confirmação e o link de nova senha vão para o **log** do servidor (e `reset-link` só pela CLI).

## 6. Variáveis de ambiente e segredos

Todas lidas pelo código (nomes apenas):

**Núcleo ([config.py](../src/studio/config.py))**
`STUDIO_MODE`, `STUDIO_ALLOW_PAID_CALLS`, `STUDIO_DATA_DIR`, `STUDIO_ASSETS_DIR`, `STUDIO_PROFILES_DIR`, `STUDIO_PLANNER_MODEL`, `STUDIO_REVIEWER_MODEL`, `STUDIO_IMAGE_MODEL`, `STUDIO_IMAGE_SIZE`, `STUDIO_VIDEO_MODEL`, `STUDIO_VIDEO_RESOLUTION`, `STUDIO_MAX_INFLIGHT_OPS`, `STUDIO_MAX_IMAGE_ATTEMPTS`, `STUDIO_MAX_VIDEO_ATTEMPTS`, `STUDIO_POLL_INTERVAL_S`, `STUDIO_FFMPEG`, `STUDIO_FFPROBE`, `STUDIO_FONT_FILE`, `STUDIO_X264_PRESET`, `STUDIO_MONTHLY_CAP_USD`, **`GEMINI_API_KEY`** (segredo).

**Web / acesso ([server.py](../src/studio/web/server.py), [mailer.py](../src/studio/mailer.py))**
`STUDIO_ALLOWED_HOSTS`, `STUDIO_PUBLIC_HOST`, `STUDIO_SECURE_COOKIE`, **`STUDIO_GOOGLE_CLIENT_ID`**, **`STUDIO_GOOGLE_CLIENT_SECRET`** (segredo), `STUDIO_SMTP_HOST`, `STUDIO_SMTP_PORT`, `STUDIO_SMTP_USER`, **`STUDIO_SMTP_PASSWORD`** (segredo), `STUDIO_MAIL_FROM`.

**Créditos ([billing.py](../src/studio/billing.py))**
`STUDIO_FX_BRL_PER_USD` (5,40), `STUDIO_CREDIT_MARGIN` (3,0), `STUDIO_CREDIT_PRICE_BRL` (1,00), `STUDIO_CREDIT_POLICY_FINAL`.

**Chat ([agent_chat.py](../src/studio/agent_chat.py))**
**`ANTHROPIC_API_KEY`** (segredo), `STUDIO_CHAT_ENABLED`, `STUDIO_CHAT_MODEL`, `STUDIO_CHAT_MAX_TOKENS`, `STUDIO_CHAT_MAX_CHARS`, `STUDIO_CHAT_PER_DAY`, `STUDIO_CHAT_PER_HOUR`, `STUDIO_CHAT_COOLDOWN_S`, `STUDIO_CHAT_GLOBAL_DAILY_TOKENS`, `STUDIO_CHAT_TIMEOUT_S`, `STUDIO_CHAT_PRICE_IN`, `STUDIO_CHAT_PRICE_OUT`, `STUDIO_CHAT_FAKE` (só testes).

**Reservadas (Fase D, ainda não usadas)**: **`MP_ACCESS_TOKEN`**, **`MP_WEBHOOK_SECRET`** (só em `secret_values()`).

**Windows-específicas lidas:** `LOCALAPPDATA`, `ProgramFiles`, `ProgramFiles(x86)` (procura ffmpeg do winget e `cloudflared`).

**Frontend:** só `BC_API` (em `vite.config.js`, proxy de dev). Nenhuma `VITE_*`.

**`.env.example` está desatualizado:** não lista `STUDIO_PUBLIC_HOST`, `STUDIO_ALLOWED_HOSTS`, `STUDIO_SECURE_COOKIE`, `ANTHROPIC_API_KEY`, `STUDIO_CHAT_*`, `STUDIO_CREDIT_*`, `STUDIO_FX_BRL_PER_USD`, `STUDIO_PROFILES_DIR` (as de Google e SMTP estão comentadas).

**Segredos no código/git:**
- `.env` existe localmente (com `GEMINI_API_KEY` preenchida), está no `.gitignore` e **nunca foi commitado** (`git log --all -- .env` vazio).
- Varredura por padrões de chave (`AIza…`, `sk-ant-…`, `APP_USR-…`, chaves privadas) nos arquivos versionados e em todo o histórico: **0 ocorrências**. Nenhum segredo hardcoded encontrado.
- O `.env` local cita no comentário o nome e o número do projeto Google Cloud. É só local, mas não copie esse arquivo para imagens/servidores.
- Boa prática já presente: `Settings.secret_values()` existe para ser mascarada em logs.
- Recomendação: como a chave do Gemini já esteve em disco numa pasta sincronizada pelo **OneDrive**, trate-a como exposta à nuvem da Microsoft e **gere uma chave nova para produção**.

## 7. Frontend

- **Stack:** React 18 + Vite 5 + Tailwind 4 + Phaser 3 (jogo do escritório), JS puro (sem TypeScript). Node 22 na CI.
- **Build:** `npm ci && npm run build` em `frontend/` → `frontend/dist/`. O próprio servidor Python serve o `dist/` (`GAME_DIST = <repo>/frontend/dist`, [server.py:63](../src/studio/web/server.py:63)). O caminho é relativo à raiz do repo, então o `dist/` precisa estar na mesma árvore do código Python.
- **URL da API:** **não é hardcoded.** Todas as chamadas usam caminhos relativos (`/api/...`, `/media/...`, `credentials: 'same-origin'`) em [engine/api.js](../frontend/src/engine/api.js). Em dev, o Vite faz proxy para `BC_API` (padrão `http://127.0.0.1:8765`). Isso implica **mesma origem**: front e API têm de ser servidos pelo mesmo host (ou por um proxy reverso que una os dois). Separar o front em CDN/outro domínio exigiria CORS e cookies `SameSite=None`, o que o backend não suporta hoje.
- **Variáveis de build:** nenhuma obrigatória.
- Scripts: `brand:assets`, `check:brand`, `test` (testes node). A CI já roda `npm test` + `npm run build`.
- O `dist/` e `node_modules/` (353 MB) estão no `.gitignore`.
- O build de imagem Docker precisa copiar `assets/` (mapa, personagens, tilesets) para fora do git, pelo item 3.

## 8. Dependências e vulnerabilidades

**Python**
- Sem lockfile; `anthropic` sem faixa de versão; `google-genai>=2.30` sem teto.
- `pip-audit` **não rodou** (não instalado). Rodar `pip-audit` (ou `uv pip audit`) num ambiente de CI é item de saída.

**Frontend (`npm audit`)**
- **Produção (`--omit=dev`): 0 vulnerabilidades.**
- Completo: **8 (2 baixas, 5 moderadas, 1 alta)**, todas de **ferramentas de dev**: `vite@5.4.21` (alta, direta), `esbuild` (moderada), e `shadcn` → `@shadcn/registry`, `@ts-morph/common`, `ts-morph`, `deepmerge`, `minimatch`. O `vite` só afeta o servidor de dev, não o `dist/` servido. Corrigir com upgrade de Vite 5 → versão corrigida (pode exigir major) e dar `npm audit fix` no `shadcn`.
- `npm ls` mostra pacotes `extraneous` (`@fontsource-variable/geist`, `three`) instalados e não declarados. Limpar com `npm prune`/`npm ci`.
- `cn@0.5.2` (pacote homônimo ao helper) está declarado como dependência; verificar se é usado de fato ou se é engano (o helper está em `src/lib/utils.js`).

## 9. Sistema de créditos e `pricing.LLM_PRICES`

- **`pricing.LLM_PRICES`** ([pricing.py:44](../src/studio/pricing.py:44)): dicionário **hardcoded no código** (USD por 1M tokens, entrada/saída) só para modelos Gemini (`gemini-3.8-flash`, `gemini-3.5-flash-lite`). Junto estão `IMAGE_PRICES` e `VIDEO_PRICES`, com data de consulta `2026-10-26` fixa no módulo. Não persiste em banco, não vem de env e não tem refresh automático. Modelo sem preço cadastrado lança `UnknownPrice`. O preço do Claude do chat fica à parte, em `ChatConfig` (`STUDIO_CHAT_PRICE_IN/OUT`). O custo é de **estimativa**: o custo confirmado vem do provedor, quando informado.
- **Política de conversão** ([billing.py](../src/studio/billing.py)): `créditos = ceil(USD × câmbio × margem / preço_do_crédito)`. Padrão: câmbio R$ 5,40, margem 3×, 1 crédito = R$ 1,00. Vem de env e tem flag `provisional` (enquanto `STUDIO_CREDIT_POLICY_FINAL` não for ligado). Há também `profiles/billing/catalog.json` versionado.
- **Persistência:** [credits.py](../src/studio/credits.py), tabela `credit_entries` no SQLite. É um **livro-razão append-only** em centésimos de crédito (inteiro): `grant | purchase | adjust | reserve | release | debit`, `ext_ref` UNIQUE (idempotência para webhooks). Ciclo por chamada paga: reserva → chamada → liberação + débito. Reserva órfã liberada após 15 min. Workspaces do admin são **isentos** de saldo (registram, mas não exigem).
- **Compra pelo cliente: não existe.** Créditos só entram por `studio admin grant-credits`. Mercado Pago (Pix/cartão) é a Fase D, sem código e sem CNPJ ainda (só modo de teste).
- Locking em memória (`threading.Lock`) → só seguro com **um processo**.

## 10. O que impede rodar em servidor limpo

Caminhos e dependências de ambiente Windows/OneDrive:

1. [.claude/launch.json](../.claude/launch.json) tem `C:/Users/chris/OneDrive/.../.venv/Scripts/python.exe` absoluto. É só config de editor, não afeta o servidor, mas está versionado.
2. `config._find_binary` procura o ffmpeg em `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*`; em Linux só funciona se o ffmpeg estiver no `PATH` (ok) ou em `STUDIO_FFMPEG`.
3. `config._default_font` tenta `C:/Windows/Fonts/segoeui.ttf` e `arial.ttf`, depois `DejaVuSans.ttf` do Linux. **Num container sem fontes, devolve `None`** e o texto sobreposto no vídeo pode falhar ou sair sem texto. Instalar `fonts-dejavu` ou definir `STUDIO_FONT_FILE`.
4. `server._find_cloudflared` procura em `LOCALAPPDATA`/`ProgramFiles` (só `publish`; irrelevante em servidor real).
5. `StudioHTTPServer.allow_reuse_address = os.name != "nt"`: ok em Linux.
6. README e docs usam `.venv\Scripts\studio` (sintaxe Windows). Não afeta o runtime.
7. Repositório dentro do **OneDrive**: sincroniza `data/` (SQLite em WAL!) e `.env`. Pode corromper o banco e vaza segredo para a nuvem. Em produção o dado vive fora de qualquer pasta sincronizada.
8. `PROJECT_ROOT = Path(__file__).resolve().parents[2]` define `data/`, `assets/`, `profiles/` e `.env` relativos à árvore do código. Isso funciona se o pacote rodar *in place* (`pip install -e .`), mas **quebra num wheel instalado em `site-packages`**: aí `parents[2]` não é a raiz do repo. O pacote só embute `web/static/*.html`, não `profiles/`. Sempre defina `STUDIO_DATA_DIR`, `STUDIO_ASSETS_DIR`, `STUDIO_PROFILES_DIR` ou rode a partir do checkout.
9. Nenhum `Dockerfile`, `Procfile`, `docker-compose`, unit de systemd ou script de start para Linux existe.

---

# Bloqueios para deploy

Ordenados por gravidade. Esforço: **P** = até ~½ dia, **M** = 1–3 dias, **G** = mais de 3 dias.

| # | Gravidade | Bloqueio | Esforço |
|---|---|---|---|
| 1 | **Crítico** | **Cadastro aberto + primeiro usuário vira admin.** Sem `STUDIO_PUBLIC_HOST`, o signup é público e quem criar a primeira conta num banco vazio vira `is_platform_admin` com créditos isentos e modo real. Ligar o fechamento do cadastro a uma variável explícita (ex.: `STUDIO_SIGNUP=closed`), e criar o admin por CLI/seed no deploy. | P |
| 2 | **Crítico** | **Servidor só escuta em 127.0.0.1, sem TLS, sem health-check, sem host configurável.** Precisa de bind configurável (`0.0.0.0`/`STUDIO_HOST`), proxy reverso com HTTPS (Caddy/nginx/Cloudflare), `STUDIO_PUBLIC_HOST`, `STUDIO_ALLOWED_HOSTS`, `STUDIO_SECURE_COOKIE=1` e leitura do IP real atrás do proxy (hoje só `cf-connecting-ip`). | M |
| 3 | **Crítico** | **Orquestrador vive em threads dentro do processo web.** Reinício/deploy mata produções em andamento e nada as retoma. Mínimo para o 1º deploy: processo único, `systemd`/contêiner com `restart`, rotina de retomada ao subir e *graceful shutdown*. O ideal é worker separado com fila. | M (mínimo) / G (worker + fila) |
| 4 | **Alto** | **Dados em disco local sem backup:** SQLite (WAL) + 205 MB de mídia, hoje dentro do OneDrive. Definir volume persistente fora de pasta sincronizada, backup agendado do `.sqlite3` (`.backup`, não cópia do arquivo) e da pasta `productions/`. Mídia em S3/R2 só se for escalar para mais de uma máquina. | M |
| 5 | **Alto** | **Assets licenciados fora do git** (`characters`, `tilesets`, `frontend/src/assets/home`): o build limpo passa mas sai sem visuais. Definir como o builder os recebe (volume/bucket privado/etapa de CI com secret) e **confirmar a licença LimeZu para distribuição num SaaS**. | M |
| 6 | **Alto** | **Sem Dockerfile/infra para Linux**: Python + ffmpeg + fonte (DejaVu) + build do front + `PROJECT_ROOT` relativo. Criar imagem multi-stage, definir `STUDIO_*_DIR` explícitos e fixar a versão do Python (3.12/3.13, não 3.15). | M |
| 7 | **Alto** | **Segredos:** gerar nova `GEMINI_API_KEY` para produção (a atual esteve no OneDrive), definir `ANTHROPIC_API_KEY`, SMTP e Google OAuth em secret manager; completar o `.env.example`. Nenhum segredo está no git. | P |
| 8 | **Alto** | **E-mail:** sem `STUDIO_SMTP_HOST`, o código de confirmação e o link de senha só aparecem no log. Em produção, usuários não conseguem verificar a conta nem recuperar senha. Contratar SMTP/serviço transacional e verificar domínio (SPF/DKIM). | P–M |
| 9 | **Médio** | **SQLite e locks em memória impedem múltiplos processos/réplicas** (créditos com `threading.Lock`; sem migrações versionadas). OK para 1 instância; Postgres + Alembic é o caminho do SaaS (já previsto no roadmap). | G |
| 10 | **Médio** | **Sem CI do backend nem lockfile Python**, sem `pip-audit`. Adicionar job `pytest` (marker `not real`), lockfile (`uv`/`pip-compile`) e auditoria. Rodar a suíte em Linux pela primeira vez. | M |
| 11 | **Médio** | **Créditos sem compra:** sem Mercado Pago (Fase D), sem CNPJ; só admin concede via CLI. Dá para lançar fechado/por convite, mas não como SaaS autoatendido. Preços e política (`LLM_PRICES`, margem 3×, câmbio 5,40) estão hardcoded/provisórios e precisam de revisão antes de cobrar. | G |
| 12 | **Médio** | **Mídia servida pelo processo Python** (`/media/…` com Range), em servidor `ThreadingHTTPServer` simples, sem compressão, sem cache e sem limites de conexão. Servir `/assets` e `/media` pelo proxy/CDN. | M |
| 13 | **Baixo** | `npm audit`: 8 vulnerabilidades, todas só de dev (Vite 5 alta, `shadcn` e outras). Produção limpa. Atualizar Vite e `shadcn`; podar `extraneous` (`three`, geist) e checar `cn`. | P |
| 14 | **Baixo** | Higiene do repositório: o diretório untracked de terceiros (escritório virtual) e `vite.config.js.timestamp-*.mjs` untracked, `data/studio.db` vazio, `.claude/launch.json` com caminho absoluto versionado, docs com sintaxe Windows. | P |
| 15 | **Baixo** | Operação: sem painel admin web (tudo pela CLI), sem monitoramento, sem logs estruturados, sem rate-limit global fora do login e do chat. | M |

**Rota mínima sugerida (lançamento fechado, 1 instância):** itens 1, 2, 3 (mínimo), 4, 5, 6, 7 e 8. Estimativa total: **~1–2 semanas** de trabalho focado. Os itens 9 e 11 definem o salto para SaaS aberto.

---

## Nota de 2026-11-06 — bloqueios 5 e 6 (assets licenciados e imagem Linux)

Verificado manualmente por Christian em 2026-11-06, fora desta sessão: o build real da imagem Docker (branch `deploy/docker`) foi concluído com os assets licenciados baixados do R2 privado; o escritório abriu com esses assets; o login funcionou; uma produção simulada terminou; o MP4 foi baixado e reproduzido; o crédito ao LimeZu aparece na interface. Detalhes e comandos em [DOCKER.md](DOCKER.md).

- **Bloqueio 6 (Dockerfile/infra Linux):** imagem multi-stage com Python 3.12, ffmpeg, DejaVu e usuário não-root, dependências por lockfile com hashes. Build real feito. **Atualização de 2026-11-07, evidência executada por Christian** no Docker local: o roteiro `scripts/verify_phase3.sh` passou por inteiro (não-root, persistência após recriar, SIGTERM/SIGKILL e varredura das camadas, incluindo `2a-fs`: nenhum `*.zip`, 3 licenças LimeZu em `/app/licenses`, sem `bia` na imagem). A validação Docker está concluída; a sessão de desenvolvimento não reproduziu esses resultados. **Seguem abertos:** o bloqueio 10 (CI do backend, `pip-audit`, suíte em Linux) e a definição do build de produção (onde a imagem é construída, versionada e publicada, em registro privado).
- **Bloqueio 5 (assets licenciados fora do git):** o pacote privado é baixado no build por BuildKit secrets e conferido por SHA256 (`assets.lock`). **Segue aberta** a confirmação de que a licença LimeZu cobre a distribuição dos PNGs no navegador de um SaaS; a validação da imagem não resolve isso.

