# SPEC-AGENTES-001 — Pivoo como plataforma de agentes configuráveis (Fase 7)

> Status: **aprovada com ajustes (2026-11-04).** As decisões do Chris estão em §10 e §11 e **prevalecem sobre o resto do texto** quando houver diferença (§11 vale sobre §10).
> Fases 4–6 validadas pelo Chris; 7.0 feita na branch `chore/fases-4-a-6`. Ordem: 7.1 → 7.2 → 7.M → 7.3 → 7.4, com parada e resumo ao fim de cada fase.
> Base: working tree de `feat/mapa-tiled-phaser` (com as Fases 4, 4b, 5 e 6 ainda sem commit).

## 0. Resumo em 10 linhas

1. O usuário passa a gerenciar a própria equipe: criar, editar, duplicar, pausar e arquivar agentes, e ligá-los em fluxos com aprovações.
2. **Vídeo Shopee vira um "pack"** (`video_shopee@1`): os mesmos 6 agentes, o mesmo `orchestrator.py`, os mesmos créditos e entregáveis. Vem instalado em toda conta nova e em todas as que já existem.
3. O orquestrador de vídeo **não é reescrito**. Ele vira o executor nativo do pack, e o motor genérico conversa com ele por um adaptador. Risco de regressão na receita: mínimo.
4. Motor genérico novo e pequeno: fluxo **linear** de passos `texto → texto` com gates de aprovação, teto de custo e de passos, e kill switch. Não tem laço, não chama ferramentas e não executa nada irreversível.
5. Um template extra só: **"Conteúdo de produto"** (Redator → Revisor → aprovação), e mais a **"Equipe em branco"**.
6. Escritório: **opção A (slots)**. O mapa continua pré-gerado offline. As 6 salas de agente viram vagas que o usuário atribui e renomeia.
7. Limite: **12 agentes não arquivados por workspace**, com **6 mesas no mapa** na v1. Quem fica sem mesa aparece na Equipe e na Central, mas não no mundo.
8. Ids estáveis: os agentes do pack mantêm os slugs `nina…beto`. Treino, chat, histórico e `localStorage` continuam valendo sem conversão.
9. A primeira fase de código (7.1) só **troca constantes por dados** e não muda nada na tela.
10. Tudo fica atrás de uma flag por workspace (`platform_enabled`) e de uma flag global (`STUDIO_PLATFORM`). As migrações só criam tabelas (são aditivas), são idempotentes e reversíveis.

---

## 1. Auditoria: o que hoje assume os 6 agentes, as 9 salas ou o domínio Shopee

Legenda da última coluna: **Dado** (vira registro do workspace ou do pack), **Pack** (fica, mas só dentro do pack de vídeo), **Fica** (pode continuar fixo).

### 1.1 Frontend: mundo e dados

| Arquivo | O que está fixo | O que precisa virar dado | Destino |
|---|---|---|---|
| `frontend/src/game/data.js` | `AGENTS` (6 objetos com id, nome, função, aba, caneca, look); `TABS` (aba → agente); `STAGES`/`STAGE_LABELS` (11 etapas do vídeo); liga agente → sala por `ROOMS.find(r => r.agent === a.id)` | Equipe vinda de `/api/team` (id, nome, função, avatar, sala, estado). `TABS`, `STAGES` e `STAGE_LABELS` vão para o módulo do pack (`packs/videoShopee.js`). A ligação agente ↔ sala passa a vir da atribuição (`room_assignments`) e não da propriedade do `.tmj` | Dado + Pack |
| `frontend/src/game/map.js` (canvas) | `ROOMS` com `agent: 'nina'…` e `tab`, nomes e dicas das salas | `agent` e `tab` viram só o *padrão do pack*. Nome e agente da sala vêm da atribuição | Dado |
| `frontend/src/game/world/tmjWorld.js` | Lê `agent`/`tab` das propriedades do objeto `room` do `.tmj` e mescla com `meta` (`OLD.ROOMS`) | `buildWorld(tmj, meta, assignments)`: a geometria vem do `.tmj` e quem ocupa a sala vem das atribuições. Sala sem agente vira `vacant: true` | Dado |
| `frontend/src/game/phaser/sprites.js` | `CHARACTER_SHEETS = {nina:'nina', …, __player:'voce'}`, `PIVOO_IDS` | Mapa **avatar → folha** (catálogo), sem relação com o id do agente. `agent.avatar = 'pivoo:nina'` | Dado (catálogo) |
| `frontend/src/game/phaser/OfficeScene.js` | Carrega as folhas pelo `CHARACTER_SHEETS`; o resto é genérico (lê `v.chars`) | Carrega as folhas dos avatares que a equipe usa | Dado |
| `frontend/src/game/agentLife.js` | Nada de nomes (só `seat`/`status`) | — | Fica |
| `frontend/src/ui/WorldPhaser.jsx`, `ui/world/InfoCard.jsx`, `RoomDialog.jsx` | `onOpen={r.agent ? r.work : null}`: supõe que toda sala com agente tem "trabalho" (aba do vídeo) | A ação "Abrir trabalho" vem do pack, ou cai na ficha do agente / passo da missão. Placa de "Vaga disponível" | Dado |
| `frontend/src/ui/Minimap.jsx` | `COL[r.id]`: cor por id de sala | Cor por tipo/slot, com valor padrão | Dado |
| `frontend/src/landing/art.js` | `SEATS = {nina:[2,5], …}` | É marketing da home, mostra o pack de vídeo | Fica |
| `frontend/src/landing/Landing.jsx` | 6 agentes, FAQ da Shopee | Home é vitrine do carro-chefe | Fica (rever a copy depois) |
| `frontend/src/ui/Auth.jsx` | `ART` com nina/theo/iris e a lista dos 6 na arte da tela de acesso | Decorativo | Fica |
| `frontend/src/assets/home/*.png`, `tools/render_home.py` | Retratos e `sede.webp` com os 6 | Marketing | Fica |

### 1.2 Frontend: lógica e telas

| Arquivo | O que está fixo | O que precisa virar dado | Destino |
|---|---|---|---|
| `frontend/src/App.jsx` | `statusOf(id)`: um `if` por agente (l. 221–230); `roomStatus` com `switch` por agente (l. 481–489); `dialogFor(id)`: falas por agente (l. 701–743); `nextLabel = {nina:'Abrir ficha', …}` (l. 793); `learn: {agent: 'iris'/'lia'}` (l. 619, 628, 983); `'Trilhas'` só para lia/beto (l. 811, 826); `rivalA … AGM.rui` (l. 955); `rsOf('nina'…)` no pipeline (l. 966); `statuses.nina` (l. 973); validação de link `shopee.com.br` (l. 526); textos "publique pelo app da Shopee" | O pack de vídeo exporta `statusOf(roleKey, ctx)`, `roomStatus`, `dialogFor`, `nextAction`, `extraActions`. O App chama pelo `role_key` do agente (`video.prep`…), não pelo id. Agentes genéricos usam o estado da **missão genérica** (passo atual/gate). A validação de link fica no formulário de missão do pack | Pack + Dado |
| `frontend/src/shell/pipeline.js` | Fases `roteiro/criativo/video/revisao/entrega` com agentes `nina…beto` e índices de `STAGES` | `buildPipeline` genérico a partir dos `steps` da missão. O pack de vídeo mantém um "projetor" que monta os passos a partir do estado da produção (o que existe hoje) | Pack + Dado |
| `frontend/src/shell/Central.jsx` | Saudação ("Boa tarde"), "Criar primeira missão", progresso e "decisões" derivados do pipeline do vídeo | Lê `v.team`, `v.missions` e `v.attn` genéricos. A saudação continua (é neutra) | Dado |
| `frontend/src/shell/TeamView.jsx` | `DOES = {nina: '…', …}` (descrição por agente) | `agent.description`/`instructions`. Vira a tela **Equipe** (§5) | Dado |
| `frontend/src/shell/MissionView.jsx` | "Nenhuma missão aberta", fluxo e custo do vídeo | Missão genérica + visão do pack | Dado |
| `frontend/src/shell/Shell.jsx` | "Nova missão" abre direto o formulário de produto Shopee (`v.newProd`) | "Nova missão" passa a abrir a escolha de fluxo (o fluxo de vídeo continua sendo o 1º e o padrão) | Dado |
| `frontend/src/ui/Sectors.jsx` | Genérico na forma (lê `v.rooms`), mas `r.work` é a aba do vídeo | Sala vaga e sala comum entram na lista. "Resolver" aponta para o gate da missão | Dado |
| `frontend/src/ui/ProdWindow.jsx` | Janela inteira do fluxo de vídeo (Produto, Direção, Imagens, Revisão, Vídeos, Entrega) e textos da Shopee | É a UI do pack | Pack |
| `frontend/src/ui/Training.jsx` | `TEST_TASK = {nina:'…', …}`; abas especiais para `beto` (estilo) e `lia` (música) | Testes e campos especiais declarados pelo pack. Agente genérico: só "Jeito de trabalhar" + exemplos | Pack + Dado |
| `frontend/src/ui/Music.jsx` | `v.openTraining('lia')` | "Agente responsável por trilhas" vem do pack (`role_key = video.videos`) | Pack |
| `frontend/src/ui/Pilot.jsx` | Textos citam "o Rui" e "imagem e take" | Texto neutro no produto, com o detalhe do vídeo só dentro do pack | Pack + texto |
| `frontend/src/ui/world/AgentChat.jsx` | Manda `agent: id` e `needs` com ids fixos | Manda `agent_id` (o slug continua funcionando). O servidor resolve a persona pelo registro | Dado |
| `frontend/src/onboarding/tour.js` | "transforma um produto em uma missão de produção", "Sua equipe está esperando o primeiro produto" | Texto neutro, com o passo novo "Escolha um pack ou crie seu primeiro agente" | Texto + Dado |
| `frontend/src/onboarding/Onboarding.jsx` | `finish('mission')` → "Criar primeira missão" de vídeo | A conclusão segue a escolha do passo de pack | Dado |

### 1.3 Backend

| Arquivo | O que está fixo | O que precisa virar dado | Destino |
|---|---|---|---|
| `src/studio/agent_config.py` | `AGENTS` com **ids do motor** (`orchestrator, prep, creative, images, review, videos, editor, operator`), campos por agente, `validate_agents` só aceita esses ids | Vira a **definição técnica do pack** (`packs/video_shopee.py`): `role_key` → campos de configuração. Nome e cor deixam de morar em `data/agents.json` e passam para a tabela `agents` | Pack |
| `src/studio/web/view.py` | `_STATUS_TO_AGENT`, `_SCENE_TO_AGENT`, `event_agent()` mapeiam estado/evento → id do motor | Mapeia para `role_key`. A UI troca para o agente atribuído àquela função | Pack |
| `src/studio/agent_chat.py` | `AGENTS` (persona por agente), `NEED_ACTION`, `ROLE_LINES`, `STAGE_LABELS`, `RULES` ("estúdio que produz vídeos… Shopee Vídeo"), gênero do artigo `('nina','iris','lia')` | Persona vem do agente (`instructions`). `RULES` divide em base neutra + bloco do pack. Atalhos (`template_reply`) recebem do pack as frases de função e de "precisa de você". Artigo vem de `agent.pronoun` (opcional; padrão neutro "Sou Fulano") | Dado + Pack |
| `src/studio/training.py` | `AGENTS = ("nina", …)`, `WHERE_USED`, `DEFAULTS`, `SUGGESTIONS`, regras especiais `beto`/`lia`/`theo`, `can_execute` exclui nina/beto | Tabela de treino já é por `(workspace_id, agent_id)`: **não muda o esquema**. As listas viram dados do pack. Agente genérico ganha um padrão (função, objetivo, tom, cuidados) | Pack + Dado |
| `src/studio/web/agents_api.py` | `ROLE = {theo:…, iris:…}`, `if agent in ('nina','beto')`, música de `lia` | Lê o pack | Pack |
| `src/studio/orchestrator.py` (976 l.) | Fluxo de vídeo inteiro (estados, cenas, tentativas, orçamento, créditos, piloto) | **Não muda nesta fase.** Ganha só um adaptador (`VideoShopeeExecutor`) que expõe estado/gates/custo para a missão | Pack (intacto) |
| `src/studio/db.py` | Tabelas `productions/scenes/attempts/reviews/events` (vídeo) | Continuam. `missions` e `mission_steps` são tabelas **novas**, e a missão de vídeo aponta para `production_id` | Fica + novo |
| `src/studio/credits.py` | `STAGES` (rótulos de etapas de vídeo); `credit_entries.production_id` | Coluna nova `mission_id` (nula para o legado); rótulos das etapas genéricas (`agent_step`) | Dado |
| `src/studio/accounts.py` | `workspaces` sem conceito de pack/equipe | Colunas `platform_enabled`, `max_agents` (ou via plano) e instalação do pack na criação | Dado |
| `src/studio/models.py` | `ProductInput._shopee_link`, `ProductSheet`, `Script`, `EditPlan` | Contratos tipados do pack (ficam) | Pack |
| `src/studio/web/server.py` | Rotas `/api/productions/...`, `/api/chat`, `/api/training/...`, `/api/config` (agentes do motor) | Rotas novas: `/api/team`, `/api/agents/...`, `/api/rooms`, `/api/workflows`, `/api/missions/...`, `/api/packs`. As de produção continuam iguais | Novo |
| `src/studio/agents/*.py`, `creative_options.py`, `profiles.py` (Bia), `music.py`, `ffmpeg.py` | Domínio de vídeo | — | Pack (intacto) |

### 1.4 Ferramentas do mapa (`tools/`)

| Arquivo | O que está fixo | O que precisa virar dado | Destino |
|---|---|---|---|
| `tools/layout.yaml` | `cells[].agent: nina…` e `tab`; nomes das salas | `agent`/`tab` viram `default_agent` (padrão do pack). Entra `slot: 1..6` e `kind: agent|common` | Dado (padrão) |
| `tools/rooms/*.yaml` | `agent: beto`, `tab: entrega` no cabeçalho; comentários "estação A: Beto" | `agent` sai do arquivo da sala (fica só no `layout.yaml` como padrão). Mobília temática (estúdio em Vídeos, timeline em Edição) **fica**: é a identidade da sala | Dado |
| `tools/build_map.py` | Emite `agent`/`tab` nos objetos `room` e `seat kind=agent` | Emite `slot`, `room_kind` e `default_agent`. Continua sendo a **única** fonte do `.tmj` (nada de tile por código) | Dado |
| `assets/maps/office.tmj` | Gerado | Regenerado uma vez (7.3) com as propriedades novas, e a geometria não muda | — |

### 1.5 Testes

| Arquivo | O que fixa | Como fica |
|---|---|---|
| `frontend/tests/tmj.test.mjs` | `SETORES = {planejamento:'nina', …}`, `ed.agent === 'beto'`, assento do `beto` | Dirigido por dados: para cada sala `kind: agent`, existe slot, mesa e assento alcançável. O mapeamento padrão vem de `packs/videoShopee.js` |
| `frontend/tests/sprites.test.mjs` | Chaves de `CHARACTER_SHEETS` | Testa o catálogo de avatares (toda folha do catálogo tem spec válida) |
| `frontend/tests/sprite-layout.test.mjs` | Loop sobre os 6 nomes | Loop sobre o catálogo |
| `frontend/tests/sprite-motion.test.mjs` | `'nina'` como id de exemplo | Id qualquer |
| `frontend/tests/pipeline.test.mjs` | `statuses` por nome | Dois grupos: projetor do pack (mantém os casos de hoje) + pipeline genérico |
| `tests/test_agent_chat.py` | `agent="iris"` | Continua (slug estável) + casos de agente criado pelo usuário |
| `tests/test_training_music.py`, `test_web_ui.py`, `test_game_flow.py`, `test_orchestration.py`, `test_creative_flow.py`, `test_editor_craft.py`, `test_product_and_script.py`, `conftest.py` | Fluxo de vídeo e ids do motor | **Não mudam** (o pack fica intacto). São a rede de proteção contra regressão |

### 1.6 Textos pt-BR

- **Neutros no produto** (passam a valer para qualquer equipe): "Nova missão", "Boa tarde", "Decisões aguardando", "Sua equipe", "Escritório".
- **Específicos do domínio que saem das telas gerais** e vão para o pack: "transformar produto em missão", "Sua equipe está esperando o primeiro produto", "publique pelo app da Shopee", "Aguardando produto", "Abrir ficha", "Liberar imagens", menções ao Rui no Piloto.
- **Ficam como estão**: landing, Auth, `ProdWindow` (UI do pack).

### 1.7 Achado importante: dois espaços de id

Hoje existem **dois conjuntos de ids** para os mesmos agentes: o de **persona** (`nina, theo, iris, rui, lia, beto`), usado no front, no chat e no treino, e o do **motor** (`prep, creative, images, review, videos, editor`, mais `orchestrator` e `operator`), usado em `agent_config.py` e `view.py`. O modelo novo resolve isso com dois campos:
`agent.slug` (persona, estável) e `agent.role_key` (função no pack: `video.prep`, `video.creative`, `video.images`, `video.review`, `video.videos`, `video.editor`). `orchestrator` e `operator` deixam de ser agentes: são o **sistema** e o **usuário**.

---

## 2. Modelo de dados

Princípio: **somar, não trocar.** As tabelas de vídeo continuam como estão. As novas guardam equipe, salas, fluxos e missões, e a missão de vídeo aponta para a produção.

### 2.1 Tabelas novas (SQLite agora, Postgres na fase E)

```text
workspaces (+ colunas)
  platform_enabled INTEGER DEFAULT 0      -- flag por workspace
  max_agents       INTEGER DEFAULT 12     -- teto (depois vem do plano)
  agents_daily_cap_cc INTEGER DEFAULT NULL -- teto diário de créditos de agentes genéricos (NULL = padrão do plano)

packs_installed
  workspace_id, pack_id ('video_shopee'|'conteudo_produto'|'blank'), version INTEGER, installed_at, status ('active'|'removed')
  PK (workspace_id, pack_id)

agents
  id TEXT PK ('ag_' + 10 hex)       workspace_id
  slug TEXT                          -- 'nina' para os do pack; para novos, derivado do nome; UNIQUE (workspace_id, slug)
  name TEXT (1–24)                   role_label TEXT (função exibida, ex.: "Imagens")
  role_key TEXT NULL                 -- 'video.images' para agentes do pack; NULL ou 'generic' para os do usuário
  pack_id TEXT NULL, pack_version INTEGER NULL   -- origem
  instructions TEXT (≤ 2000)         -- persona / instruções
  description TEXT (≤ 240)           -- "o que faz" (cartão da equipe)
  avatar TEXT                        -- 'pivoo:nina' | 'limezu:<arquivo>' | 'gen:<id>' (Character Generator, futuro)
  color TEXT '#RRGGBB'               pronoun TEXT NULL ('a'|'o'|NULL)
  status TEXT ('active'|'paused'|'archived')
  model TEXT                         -- só modelos com preço em pricing.LLM_PRICES; padrão barato
  max_tokens INTEGER (≤ 1024)
  budget_task_cc INTEGER             -- teto por passo/tarefa
  budget_day_cc INTEGER              -- teto por dia
  skills_json TEXT                   -- lista de habilidades permitidas (v1: ['text'] apenas)
  locked_json TEXT                   -- campos que o pack não deixa editar (ex.: role_key)
  created_at, updated_at, archived_at

rooms                                -- vagas do mapa (espelho do .tmj, por workspace)
  workspace_id, room_id TEXT ('planejamento'… id da sala no .tmj = slot estável)
  kind TEXT ('agent'|'common')       name TEXT NULL (renomeada; NULL = nome do mapa)
  agent_id TEXT NULL                 -- NULL = "vaga disponível"
  PK (workspace_id, room_id); UNIQUE (workspace_id, agent_id) quando não nulo

workflows
  id ('wf_…'), workspace_id, pack_id NULL, key ('video_shopee'|'conteudo_produto'|custom), name, version INTEGER
  executor TEXT ('native:video_shopee'|'generic')
  steps_json TEXT                    -- ver 2.2
  max_steps INTEGER (≤ 12), max_cost_cc INTEGER, status ('active'|'archived'), created_at, updated_at

missions
  id ('mis_…'), workspace_id, workflow_id, workflow_version, title
  production_id TEXT NULL UNIQUE     -- missão de vídeo ↔ produção (1:1)
  status ('draft'|'running'|'awaiting_approval'|'paused'|'completed'|'failed'|'cancelled')
  input_json TEXT, output_json TEXT
  cost_cc INTEGER (acumulado), budget_cc INTEGER, created_by, created_at, updated_at

mission_steps                        -- só para executor 'generic' (o vídeo projeta os passos a partir da produção)
  mission_id, idx, agent_id, status ('pending'|'running'|'awaiting_approval'|'approved'|'rejected'|'done'|'failed'|'skipped')
  input_text, output_text, attempts INTEGER, cost_cc INTEGER, approved_by, note, started_at, finished_at
  PK (mission_id, idx)

credit_entries (+ coluna)  mission_id TEXT NULL     -- production_id continua; vídeo grava os dois
mission_events             id, mission_id, step_idx, ts, type, message, data_json
                           -- tabela própria: events continua só de produções (não mistura FK)
```

### 2.2 Contrato de um passo (`steps_json`)

```json
{ "id": "redigir", "title": "Redigir descrição", "role": "redator",
  "agent_id": "ag_…",                       // escolhido no editor; vazio = usa o agente com role compatível
  "input": { "type": "text", "from": "mission.input" },   // ou "from": "steps.redigir.output"
  "output": { "type": "text", "max_chars": 2000 },
  "approval": "before_next" | "none",       // gate humano depois do passo
  "max_attempts": 2,                         // retry limitado
  "irreversible": false }                    // reservado; true sempre força gate (v1 não tem passo irreversível)
```

O pack de vídeo declara os passos dele (Produto → Direção → Imagens → Revisão → Vídeos → Entrega) **só como descrição** (rótulo, agente, gates). A execução e os contratos tipados (`ProductInput`, `ProductSheet`, `Script`, `EditPlan`, `ReviewResult`) continuam em `orchestrator.py` e `models.py`.

### 2.3 Pack

Arquivo versionado no código, não no banco: `src/studio/packs/video_shopee.py` e `frontend/src/packs/videoShopee.js` (mesmo `version`).

```text
Pack = { id, version, name, description,
         agents:    [{ slug, name, role_key, role_label, description, instructions, avatar, color, pronoun, default_room }],
         rooms:     { room_id: { name, kind, default_agent_slug } },
         workflows: [{ key, name, executor, steps }],
         locked:    ['role_key', 'status=archived'] }     // o que o usuário não pode mudar nos agentes do pack
```

Para instalar um pack, o sistema cria as linhas em `agents/rooms/workflows`, marcadas com `pack_id`. Atualizar a versão do pack **nunca sobrescreve** o que o usuário editou (nome, persona, avatar, sala). Só os campos travados são atualizados.

### 2.4 O que muda em relação a hoje

| Hoje | Depois |
|---|---|
| Agentes = constantes em 6 arquivos (front e back) | Linhas em `agents` por workspace; constantes só no módulo do pack |
| Nome e cor editáveis globalmente em `data/agents.json` | Por workspace, na tabela `agents` (`agents.json` fica só com as `settings` técnicas do motor) |
| Sala ↔ agente gravado no `.tmj` | `rooms.agent_id` por workspace; o `.tmj` só sugere o padrão |
| "Produção" = único tipo de trabalho | `missions` (genérico); a produção de vídeo é uma missão com `production_id` |
| Custo por produção | Custo por missão; vídeo continua gravando `production_id` e ganha `mission_id` |
| Piloto por produção | Igual para vídeo; nos fluxos genéricos o piloto decide quais gates param (§4.4) |

**Por que não renomear `productions` → `missions`:** essa troca tocaria ~20 arquivos e todos os testes do motor sem trazer nada ao usuário. A ligação 1:1 dá o mesmo resultado sem risco.

---

## 3. Escritório dinâmico: decisão

### 3.1 Opções

| | A) Slots (mapa pré-gerado) | B) Composição em execução |
|---|---|---|
| Como | O `.tmj` continua saindo de `build_map.py`. As 6 salas de agente são **vagas** com id estável. O usuário atribui agentes, renomeia salas e vê "vaga disponível" | Salas pré-fabricadas (chunks gerados pelo pipeline) montadas numa grade conforme o tamanho da equipe |
| Prós | Nada novo no renderer. Colisão, BFS, câmera, assentos e `tmj.test` continuam valendo. Nítido (pixel art feito para aquele layout). Entrega em dias | Escala para qualquer tamanho de equipe. Salas temáticas por função |
| Contras | Limite de mesas fixo por versão do mapa. Mobília temática (estúdio em "Vídeos") pode não combinar com a função nova | Costura de paredes e portas entre chunks, colisão e corredores recalculados, câmera, minimapa, testes de alcançabilidade em tempo de execução, tela de carregamento. Semanas de trabalho e risco alto de regressão visual. Mexe na regra "não desenhar tile por código" (montar chunks é composição, mas a costura tende a virar código) |
| Custo | P | G |

### 3.2 Recomendação: **A**

- **Limite:** **12 agentes não arquivados por workspace** (`max_agents`, ajustável por plano). **6 com mesa no mapa** na v1, que são as 6 salas de agente do `layout.yaml`.
- **Agente sem mesa:** aparece na Equipe, na Central, no painel e no chat (pelo painel), com o selo "Sem mesa". No mundo ele **não aparece**. O caminho já existe: `data.js` trata `seat = null` desde a Fase 2b.
- **Sala vazia:** placa "**Vaga disponível**" em cinza. O hover mostra "Atribuir agente" e abre o wizard na etapa de sala. A cadeira do agente fica livre, e o jogador pode sentar.
- **Sala renomeada:** só muda a placa, o card, os Setores e o minimapa (`rooms.name`). Id, geometria e mobília não mudam. Limite de 24 caracteres.
- **Agente trocado de sala:** troca atômica no servidor (`UNIQUE (workspace_id, agent_id)`). Se a sala de destino estiver ocupada, a UI oferece **trocar os dois** ou deixar o outro sem mesa. No mundo, o agente reaparece na nova cadeira no próximo estado (sem caminhar: agentes ficam sentados e só o jogador navega, como manda a regra da Fase 6).
- **Salas comuns** (Entrada, Jogos, Pátio, "Meu escritório") são `kind: common`: podem ser renomeadas, mas não recebem agente.
- **Evolução sem B:** a segunda estação que já existe em 4 salas (Edição, Imagens, Revisão, Vídeos têm `kind: visitor` com monitor) pode virar `kind: agent` de slot B numa regeneração offline. Isso dá **10 mesas** sem mexer no renderer. Fica como fase opcional 7.8, se a demanda aparecer.

---

## 4. Motor de orquestração

### 4.1 Camadas

```text
MissionService (novo, ~300 linhas)
  ├─ executor 'native:video_shopee' → VideoShopeeExecutor (adaptador) → Orchestrator (intacto)
  │     start = create_production + run; approve/reject/cancel delegam; status/custo/gates projetados de productions/scenes/credit_entries
  └─ executor 'generic'            → GenericRunner (novo, ~250 linhas)
        passo: monta prompt (instructions do agente + contrato + entrada) → hold de créditos → LLM → settle → valida saída → gate?
```

### 4.2 Regras do executor genérico

- **Fluxo linear** (lista ordenada). Não há desvio, laço, chamada de um agente por outro nem "o agente decide o próximo passo". A entrada do passo N é o texto da missão ou a saída de um passo anterior.
- **Handoff:** quando o passo termina, a saída é validada (vazia, maior que `max_chars` ou recusa do modelo contam como falha) e vira a entrada do próximo. Um evento `handoff` registra de quem para quem.
- **Gate de aprovação:** `approval: before_next` deixa a missão em `awaiting_approval`. O usuário pode aprovar, editar a saída e aprovar, pedir ajuste (nova tentativa com a nota, se ainda houver tentativas) ou cancelar. O gate aparece na Central como "Precisa de você", do mesmo jeito que o `!` de hoje.
- **Retry:** no máximo `max_attempts` (padrão 2, teto 3) por passo, contando falhas técnicas e pedidos de ajuste. Erros transitórios usam a mesma espera exponencial do orquestrador (até 4 tentativas internas, sem gastar tentativa). Esgotou, o passo vira `failed` e a missão pausa esperando o usuário.
- **Cancelamento:** a qualquer momento. A reserva é devolvida (`release`) e o passo em voo termina, mas o resultado é descartado.
- **Concorrência:** 1 passo em voo por missão; `STUDIO_MAX_GENERIC_INFLIGHT` (padrão 2) por workspace.

### 4.3 Guardrails de custo (em todo passo, antes de chamar o modelo)

1. Kill switch global `STUDIO_AGENTS_ENABLED=0`: nenhum passo genérico roda. As missões ficam `paused` com motivo, e o vídeo não é afetado.
2. `workspaces.platform_enabled` desligado: as rotas genéricas respondem 404, e só o vídeo existe.
3. Agente `paused`/`archived`: o passo não começa. A missão pausa com "Fulano está pausado".
4. Teto de passos: `max_steps ≤ 12` por fluxo e um total de **24 execuções** por missão (passos + tentativas).
5. Teto por missão (`budget_cc`), por tarefa do agente (`budget_task_cc`), por dia do agente (`budget_day_cc`), diário do workspace (`agents_daily_cap_cc`) e, por fim, o **teto mensal do workspace** (`monthly_cap_usd`, que já existe).
6. Crédito: `Ledger.hold(wid, mission_id, estimate, stage='agent_step')`. Sem saldo, a missão pausa (mesmo comportamento do vídeo).
7. Modelo barato por padrão (`claude-haiku-5-5`, o mesmo do chat da Fase 6), `max_tokens` padrão 600 e teto 1024. A lista de modelos permitidos vem de `pricing.LLM_PRICES`, e um modelo sem preço é recusado.
8. A estimativa usa o pior caso (`tokens de entrada + max_tokens` × preço). O débito usa o uso real informado.

### 4.4 Créditos: "Isento", DEMO, Piloto e chat

| Situação | Comportamento proposto |
|---|---|
| Workspace **Isento** (`credits_exempt=1`) | Igual ao vídeo: reserva e débito **são lançados** (o extrato mostra tudo), mas o saldo não é exigido. **Os tetos (missão, agente, dia, mês) continuam valendo**: isenção não é cheque em branco |
| **DEMO** (`mode='simulated'`) | Passos genéricos usam um chamador simulado (texto determinístico de exemplo), sem crédito e sem chamada externa, como as gerações simuladas de hoje |
| Piloto **Manual** | Todo gate para; além disso, o 1º passo pago de cada missão mostra a estimativa e espera liberação (paridade com o "liberar imagens") |
| Piloto **Assistido** | Para nos gates marcados `approval: before_next` |
| Piloto **Automático** | Pula gates intermediários, mas **nunca** o gate final (entregável) nem passo `irreversible`. É a mesma regra do vídeo, que "não exporta sem a sua revisão final" |
| `classico` (legado) | Só para produções antigas de vídeo; fluxos genéricos não usam |
| **Chat** com agentes | Continua grátis, com as cotas da Fase 6 (por usuário e global) e registro em `chat_log`. Agentes criados pelo usuário conversam com a própria persona. **Pergunta aberta:** cobrar chat de agentes não-pack? |

### 4.5 Ações irreversíveis

Na v1, agentes genéricos **só produzem texto**. Não publicam, não enviam e-mail, não chamam APIs externas e não mexem em créditos ou arquivos de entrega. `skills_json` aceita só `["text"]`. O campo `irreversible` e a regra "gate obrigatório" já ficam no contrato, para quando entrarem ferramentas (fase futura, com spec própria). No pack de vídeo, exportar continua exigindo a revisão final, e a publicação na Shopee continua manual.

### 4.6 Segurança do prompt

Os agentes genéricos reutilizam o padrão do `agent_chat.py`: regras fixas do sistema antes das instruções do usuário, entrada do usuário entre delimitadores (`<entrada>`), saída sanitizada e limitada. As instruções do agente são **dados do usuário** e não conseguem desligar regras de custo nem de formato, porque essas vivem no servidor e não no prompt.

---

## 5. UI de gestão (shadcn, visual claro da Fase 4/4b)

1. **Equipe** (substitui `TeamView`, rota `agentes` do Shell): tabela/lista com avatar, nome, função, sala (ou "Sem mesa"), estado (ponto + texto), gasto hoje / teto diário e pack de origem. Busca por nome e função; filtro por estado. Ações: **Novo agente**, **Duplicar**, **Pausar/Retomar**, **Arquivar** (com confirmação; arquivado sai do mapa e libera a vaga), Editar. Contador "8 de 12 agentes".
2. **Wizard "Novo agente"** (Dialog com 3 passos e preview do personagem à direita):
   - *Função e nome*: templates de função (Redator, Revisor, Pesquisador, Atendimento, Em branco) que já preenchem a persona.
   - *Persona e limites*: instruções (com contador), modelo (select curto: "Econômico" = haiku é o padrão), teto por tarefa e por dia em créditos, com a estimativa de custo de uma tarefa típica.
   - *Avatar e sala*: grade de avatares do catálogo (as 6 folhas PIVOO + `voce` + LimeZu disponíveis) e escolha de vaga no minimapa/lista ("Sem mesa" permitido).
3. **Editor de fluxo** (Sheet): lista ordenável (arrastar + teclado ↑/↓), cada passo com título, agente (select), "de onde vem a entrada" e o toggle **Pedir aprovação**. Mostra o teto de custo estimado do fluxo. O fluxo de vídeo aparece **só em leitura** (os passos são do pack).
4. **Nova missão**: primeiro escolhe o fluxo ("Vídeo Shopee" no topo, como padrão para quem tem o pack), depois o formulário do fluxo (o de vídeo é o de hoje; o genérico é um campo de texto + orçamento).
5. **Central, Setores, painel, ⌘K, onboarding e chat** leem `v.team`/`v.missions`, sem nenhum nome fixo. O onboarding ganha o passo **"Escolha um pack ou crie seu primeiro agente"** (cards: Vídeo Shopee (já instalado), Conteúdo de produto, Equipe em branco).
6. **Textos:** neutros no produto ("sua equipe", "missão", "entregável"); "produto", "Shopee" e "take" só aparecem dentro do pack.
7. **Agentes do pack de vídeo:** dá para editar nome, persona extra, avatar, cor e sala. A função não muda. Pausar um agente do pack mostra o aviso "o fluxo Vídeo Shopee vai parar nesta etapa". Arquivar só funciona se o pack for removido (pergunta aberta).

---

## 6. Migração e compatibilidade

1. **Migração `m7_platform` (aditiva):** `CREATE TABLE IF NOT EXISTS` das tabelas novas e `ALTER TABLE ADD COLUMN` em `workspaces` e `credit_entries`. Segue o mesmo padrão das migrações de `accounts.py`.
2. **Instalação do pack em cada workspace** (idempotente pela PK de `packs_installed`, e `INSERT OR IGNORE` em `agents` por `(workspace_id, slug)`): cria os 6 agentes com os **slugs de hoje**, `role_key`, as 6 atribuições de sala do `layout.yaml` e o workflow `video_shopee`. Nomes e cores editados em `data/agents.json` são importados uma vez, para todos os workspaces (hoje esse arquivo é global).
3. **Produções → missões:** uma linha em `missions` por produção (`production_id UNIQUE`, `INSERT OR IGNORE`), com status projetado. Créditos antigos ganham `mission_id` por `UPDATE … WHERE production_id=? AND mission_id IS NULL`.
4. **Reversível:** nenhuma coluna ou tabela existente é apagada ou mudada de sentido. Para voltar: `platform_enabled=0` (a interface volta ao comportamento de hoje), ou o script `studio admin rollback-platform`, que remove as tabelas novas e anula `mission_id`. As tabelas de vídeo nunca dependem das novas.
5. **Idempotente:** a migração roda em todo boot (como as de hoje), e uma segunda execução não cria nem altera nada (teste dedicado).
6. **Flags:** `STUDIO_PLATFORM` (global; padrão `0` até a 7.6) e `workspaces.platform_enabled`. Com a plataforma desligada, `/api/team` devolve o pack de vídeo, e a interface fica **idêntica à de hoje**.
7. **Mundo:** `?world=canvas` e `?world=phaser` continuam. O canvas lê as mesmas atribuições (o `map.js` tem os mesmos ids de sala). O canvas fica sem placa de "vaga", porque é legado.
8. **Testes:** todos os testes de hoje continuam passando em todas as fases. Os que fixam nomes passam a ler do módulo do pack (§1.5).
9. **Contas novas:** pack de vídeo instalado por padrão. O onboarding oferece os outros sem remover o vídeo.

---

## 7. Plano em fases

Cada fase é um PR pequeno, com o próprio critério de aceite. Nenhuma depende de redesenho do mapa.

| Fase | Entrega | Critério de aceite | Testes |
|---|---|---|---|
| **7.0** | Esta spec aprovada; working tree das Fases 4–6 commitado (pré-requisito) | Chris aprova; branch limpo | — |
| **7.1 — Dados no lugar de nomes fixos** (sem mudança visível) | `frontend/src/packs/videoShopee.js` (agentes, abas, etapas, `statusOf`, `roomStatus`, `dialogFor`, `nextAction`, textos) e registro `game/team.js`. App, pipeline, TeamView, Training, Music, sprites e chat leem dele. No back, `src/studio/packs/video_shopee.py` alimenta `agent_chat`, `training`, `agents_api` e `view` (persona ↔ `role_key`). Catálogo de avatares | Build ok. Telas idênticas em canvas e phaser (capturas antes/depois de Central, Equipe, Escritório, chat e treino). `grep` dos 6 nomes fora de `packs/`, `landing/`, `Auth.jsx` e `assets/` = 0 | Todos os atuais + `tests/team-registry.test.mjs` + testes do registro Python. Os testes de nomes passam a ser dirigidos por dados |
| **7.2 — Modelo e migração** (backend, atrás de flag) | Tabelas §2, instalação do pack, produções → missões, `GET /api/team`, `GET /api/rooms`, `studio admin rollback-platform` | Migração idempotente e reversível numa cópia do banco real; nada muda na interface | `test_platform_migration.py` (2 execuções, rollback, isolamento por workspace, import do `agents.json`) |
| **7.3 — Front lê a equipe real** | `data.js` consome `/api/team`/`/api/rooms`; `tmjWorld` com atribuições e `vacant`; `build_map.py` emite `slot`/`room_kind`/`default_agent` (regenera o `.tmj` sem mudar geometria); placa "Vaga disponível" | Com a flag desligada, a tela não muda. Com ela ligada e uma vaga forçada no banco, a placa aparece e a cadeira fica livre | `tmj.test` por dados; teste do `buildWorld` com vaga, renomeio e troca |
| **7.4 — Gestão da equipe** | Tela Equipe + wizard + duplicar/pausar/arquivar + renomear sala + trocar de sala + limites | CRUD completo no navegador; o limite de 12 é respeitado; pausar um agente do pack avisa | API: validação, limite, unicidade de sala, workspace alheio = 404 |
| **7.5 — Motor genérico** | `MissionService`, `GenericRunner`, `VideoShopeeExecutor`, gates, retry, cancelamento, guardrails §4.3, `mission_id` no ledger, kill switch, template "Conteúdo de produto" e "Equipe em branco" | Missão de 3 passos em DEMO e em real (com teto baixo) termina, para nos gates e respeita todos os tetos. O vídeo não muda (suíte do motor verde) | `test_generic_runner.py`: teto por missão, agente, dia e mês; isento; DEMO; kill switch; retry; cancelamento com estorno; agente pausado |
| **7.6 — Fluxos e missões na UI** | Editor de fluxo, "Nova missão" com escolha de fluxo, visão da missão genérica, Central/Setores/⌘K/chat genéricos, passo de pack no onboarding, textos neutros | Usuário novo: escolhe pack → cria agente → roda missão genérica → aprova gate. Usuário antigo: nada mudou no vídeo | `pipeline.test` (genérico), `onboarding.test` (passo novo e retomada pelo índice) |
| **7.7 — Liberação** | `STUDIO_PLATFORM=1`; flag por workspace ligada para contas novas e, depois, para todas | Uma semana com o próprio estúdio do Chris ligado sem regressão | Smoke de ponta a ponta |
| 7.8 (opcional) | Slot B nas 4 salas com 2ª estação (10 mesas) | — | `tmj.test` |

### 7.1 Estimativa de impacto por área

| Área | 7.1 | 7.2 | 7.3 | 7.4 | 7.5 | 7.6 | Total |
|---|---|---|---|---|---|---|---|
| Frontend | M (App.jsx, pipeline, TeamView, Training, Music, sprites, AgentChat) | — | M (data.js, tmjWorld, placas) | G (Equipe, wizard) | — | G (editor, missões, onboarding) | **G** |
| Backend | M (chat, training, agents_api, view) | M (migração + 2 rotas) | P | M (CRUD) | G (runner, ledger, guardrails) | P | **G** |
| tools/ | — | — | P (`build_map.py`, `layout.yaml`, `rooms/*.yaml`) | — | — | — | **P** |
| Testes | M (dirigidos por dados) | M | P | M | G | M | **G** |

P ≈ até 1 dia · M ≈ 2–3 dias · G ≈ 4–6 dias (ritmo atual de sessões). Total aproximado: **4–5 semanas** de trabalho em fatias.

### 7.2 Ordem em relação às Fases 4, 5 e 6

1. **Antes de tudo:** validar e **commitar** as Fases 4, 4b, 5, 6 e o hover. Hoje são ~40 arquivos modificados e ~30 novos sem commit no mesmo branch, e a 7.1 mexe em boa parte deles (App.jsx, shell, onboarding, AgentChat). Misturar tudo deixaria o diff impossível de revisar e de reverter.
2. A Fase 7 vem **depois** da 6, porque o chat (6) e o onboarding (5) são consumidores diretos da equipe e precisam existir para serem generalizados.
3. As pendências da 4b (migrar `ProdWindow` e as janelas para Dialog/Sheet) **não bloqueiam**. A `ProdWindow` vira UI do pack e pode migrar depois.
4. As pendências da Fase 3 (escolha do avatar do jogador) combinam com o catálogo de avatares da 7.1 e podem entrar junto, sem ser obrigatórias.

---

## 8. Riscos

| Risco | Mitigação |
|---|---|
| Regressão no fluxo de vídeo (receita) | Orquestrador intacto; adaptador fino; suíte do motor como portão de cada PR; flag por workspace |
| `App.jsx` (1.095 linhas) concentra a lógica por agente; mexer nele quebra o jogo | A 7.1 só **move** funções para o pack, sem reescrever; capturas antes e depois |
| Custo descontrolado de agentes genéricos | Teto em 5 níveis + kill switch + fluxo linear sem laço + modelo barato + `max_tokens` baixo; DEMO sem chamada externa |
| Prompt injection nas instruções/entrada | Regras no servidor, delimitadores, saída limitada, nenhuma ferramenta na v1 |
| Sala temática ("Vídeos" com estúdio) recebendo agente de outra função | Renomeio + aviso visual leve; salas neutras numa revisão futura do `layout.yaml` |
| Duas fontes da verdade (pack no front e no back) | Mesmo `version`; teste que compara o JSON exportado pelo Python com o módulo JS |
| SQLite com mais escrita (missões genéricas) | Volume baixo na v1; Postgres na fase E já previsto |
| `data/agents.json` global vs. agentes por workspace | Import único na migração; depois o arquivo fica só com as `settings` técnicas |

---

## 9. Perguntas abertas para o Chris

1. **Limite de agentes:** 12 por workspace (6 com mesa) está bom para a v1? Varia por plano (ex.: Grátis 6 / Pro 12)?
2. **O que é grátis e o que gasta crédito:** passos de agentes genéricos debitam crédito (proposta: sim). O chat continua grátis para todos os agentes, inclusive os criados pelo usuário?
3. **Teto diário padrão** de um agente genérico (proposta: 5 créditos/dia, 1 por tarefa) e de uma missão genérica (proposta: 10 créditos)?
4. **Pack de vídeo removível?** Proposta: não na v1 (pode ser escondido, não desinstalado). Os agentes do pack podem ser arquivados?
5. **Template extra:** "Conteúdo de produto" (descrição + legenda a partir de um texto do produto, com Redator → Revisor → aprovação) serve como prova? Alternativas: Atendimento (respostas-padrão) ou Marketing (calendário de posts).
6. **Marketplace de packs:** vai existir? Se sim, packs de terceiros mudam o modelo de confiança (código vs. dado). A proposta é que packs sejam **só dado** (agentes + fluxo genérico), e que packs com executor nativo como o de vídeo continuem só nossos.
7. **Avatar:** só as folhas PIVOO + LimeZu que já temos, ou esperar o Character Generator para a v1 do wizard?
8. **Membros/convites:** a gestão da equipe é só do dono ou de qualquer membro do workspace? (Hoje todo membro é `owner`.)
9. **Nome do conceito na UI:** "pack", "kit" ou "modelo de equipe"?
10. **Commit das Fases 4–6** antes de começar a 7.1: de acordo?

(Todas respondidas em §10.)

---

## 10. Decisões do Chris (2026-11-04), que valem sobre as seções anteriores

| # | Decisão | Efeito na spec |
|---|---|---|
| 1 | **12 agentes por workspace, 10 com mesa.** Limite numa config única (`STUDIO_MAX_AGENTS=12`, `STUDIO_MAX_DESKS=10`), sem variar por plano | §3.2: a regeneração para 10 vagas deixa de ser opcional (antiga 7.8) e vira a fase **7.M**, entre a 7.2 e a 7.3. `workspaces.max_agents` sai do modelo |
| 2 | Passos de agente genérico **gastam crédito**. O chat continua **grátis** para o usuário, dentro da cota diária e do teto global de tokens da Fase 6, **sem entrar no extrato** (só `chat_log`) | §4.4 confirmado. Agentes criados pelo usuário usam as mesmas cotas de chat |
| 3 | Tetos padrão: **5 créditos/dia por agente** e **10 créditos por missão**, configuráveis | Ver §10.1 (equivalência conferida) |
| 4 | O pack de vídeo **não pode ser removido**. Nos 6 agentes dele dá para editar nome, persona e avatar (a função não muda). Se um deles estiver **pausado ou arquivado**, "Nova missão de vídeo" fica desabilitada com a mensagem "Falta Fulano (Imagens): retome ou restaure para criar missões de vídeo" | §5.7: arquivar agente do pack é permitido, mas bloqueia o fluxo de vídeo. Uma missão de vídeo já em andamento pausa na etapa daquele agente, com o mesmo aviso |
| 5 | Template de prova: **"Conteúdo de produto"** (Redator → Revisor → aprovação) | §4 e 7.5 |
| 6 | **Sem marketplace na v1.** O pack é **dado versionado, sem código próprio** | §2.3 ajustado em §10.2 |
| 7 | Avatares: folhas atuais, **folha repetida é permitida**. O seletor lê as folhas novas de uma **pasta** | §10.3 |
| 8 | Gestão da equipe: **só o dono** (`memberships.role='owner'`) na v1 | Rotas de escrita de equipe, sala e fluxo exigem dono; os outros membros só leem |
| 9 | Na interface: **"Equipe"** e **"Modelo de equipe"**. "Pack" e "kit" nunca aparecem na tela ("kit" é o KIT ONBOARDING). "Pack" fica só no código | §5: o passo do onboarding vira "Escolha um modelo de equipe ou crie seu primeiro agente". "Equipe em branco" vira o modelo "Começar do zero" |
| 10 | 7.0 = **um commit por fase** (4, 4b, 5, 6, hover) **numa branch própria**, só depois da validação manual do Chris | §10.4 |

**Ordem aprovada:** 7.0 → 7.1 → 7.2 → **7.M (mapa com 10 vagas)** → 7.3 → 7.4 → **parada para validação da gestão da equipe** → 7.5 → 7.6 → 7.7.
Cada fase só começa depois que a anterior for aceita. A 7.1 espera autorização explícita depois da 7.0.

### 10.1 Equivalência crédito × custo real (conferida no código)

- Política atual (`billing.policy()`, **marcada como provisória**): 1 crédito = R$ 1,00, custo em US$ × câmbio R$ 5,40 × margem 3. Logo **1 crédito ≈ US$ 0,0617 de custo real** (1 US$ ≈ 16,2 créditos). O débito arredonda para cima em centésimos (0,01 crédito).
- **5 créditos/dia por agente ≈ US$ 0,31 de custo real/dia; 10 créditos/missão ≈ US$ 0,62.**
- Custo de um passo típico (2.000 tokens de entrada + 600 de saída):

| Modelo | Preço (US$/1M entrada · saída) | Custo real do passo | Em créditos | Passos dentro de 5 créditos/dia |
|---|---|---|---|---|
| `claude-haiku-5-5` (o do chat) | 0,10 · 0,50 (valor de `ChatConfig`, "tabela de 2026-10") | ≈ US$ 0,0005 | 0,01 (mínimo) | ≈ 500 |
| `gemini-3.5-flash-lite` | 0,30 · 2,50 (`pricing.LLM_PRICES`) | ≈ US$ 0,0021 | 0,04 | ≈ 125 |
| `gemini-3.8-flash` | 0,75 · 3,75 (`pricing.LLM_PRICES`) | ≈ US$ 0,0038 | 0,07 | ≈ 70 |

- **O que isso quer dizer:** com o modelo econômico, 5 créditos/dia não limitam o uso normal. Funcionam como **trava contra descontrole**, que é o objetivo. A missão de 10 créditos comporta todos os 24 passos de execução permitidos com folga.
- **Pendências antes de fixar os padrões** (entram na 7.5):
  1. `claude-haiku-5-5` **não está** em `pricing.LLM_PRICES`: hoje o preço vive só em `ChatConfig`. Ele precisa entrar na tabela de preços com fonte e data, e o executor genérico deve recusar modelo sem preço.
  2. Conferir o preço do Haiku na página oficial antes de ligar o modo real.
  3. Enquanto a política de créditos for provisória (`STUDIO_CREDIT_POLICY_FINAL` desligado), os tetos ficam em **créditos** (unidade que o usuário vê) e são guardados em centésimos. Se câmbio ou margem mudarem, o teto em créditos fica igual e só a quantidade de passos muda.
- **Config:** `STUDIO_AGENT_DAY_CAP_CREDITS=5`, `STUDIO_MISSION_CAP_CREDITS=10`, `STUDIO_AGENT_TASK_CAP_CREDITS=1`, valores que cada agente ou fluxo pode baixar (nunca subir acima do teto da config na v1).

### 10.2 Pack como dado (ajuste de §2.3)

- Um **manifesto** por pack: `packs/video_shopee/pack.json` e `packs/conteudo_produto/pack.json`, na raiz do repositório e lidos pelo Python e pelo front (Vite importa o JSON). Isso também elimina o risco das "duas fontes da verdade" (§8).
- O manifesto só tem dados: agentes padrão (slug, nome, `role_key`, descrição, persona, avatar, sala sugerida), salas sugeridas, fluxos (passos, gates, contratos de texto), textos e `version`.
- O comportamento específico do vídeo (`statusOf`, falas, projeção dos passos a partir da produção, o orquestrador) **não fica no pack**. Fica num **executor da plataforma**: `executors/videoShopee.js` e `VideoShopeeExecutor`. O manifesto só o referencia por nome (`"executor": "native:video_shopee"`). Os executores aceitos são uma lista fechada no código (`native:video_shopee`, `generic`), o que deixa um futuro marketplace possível sem rodar código de terceiros.
- Na 7.1, os textos e as tabelas que eu tinha chamado de "módulo do pack" se dividem assim: o que é dado (nomes, funções, abas, rótulos das etapas, falas fixas) vai para o `pack.json`; o que é lógica vai para o executor.

### 10.3 Avatares por pasta

- Catálogo = arquivos `assets/characters/*.png` (fora do git, licença) mais um `assets/characters/catalog.json` gerado por `tools/make_avatar_catalog.py`. Esse script lê a pasta, mede cada folha e descobre o formato pelo tamanho (folha PIVOO 512×1536 em quadros 32×32, ou LimeZu/Character Generator 1792×1312 em quadros 32×64). Folha de tamanho desconhecido é ignorada com aviso.
- Para pôr uma folha nova: salvar na pasta, rodar o script e **gerar o build de novo**. Os PNGs entram no bundle por `import.meta.glob` (`WorldPhaser.jsx`), então uma folha nova só aparece depois de `npm run build`. Servir as folhas em tempo de execução fica para depois, se fizer falta.
- `agent.avatar` guarda a chave do catálogo (nome do arquivo sem extensão). Dois agentes podem usar a mesma. Avatar ausente (PNG removido) cai no feijão, como hoje.

### 10.4 Como a 7.0 vai ser feita (quando o Chris avisar)

- Branch nova a partir do `HEAD` atual (`feat/mapa-tiled-phaser`), por exemplo `chore/fases-4-a-6`.
- Um commit por fase, nesta ordem: **4** (UI clara do mundo Phaser), **4b** (shell e modais), **hover** do mapa, **5** (onboarding), **6** (chat com agentes). Em cada commit, só os arquivos daquela fase. Quando o mesmo arquivo tem mudanças de duas fases (provável em `App.jsx`, `styles.css`, `Shell.jsx`, `server.py`), separo por trecho (`git add -p` não roda aqui, então uso patch aplicado ao índice) e mostro a divisão antes de commitar.
- Fora dos commits de fase e listados para decisão: `pivoo-office/` (parece um projeto externo), `.vscode/`, `docs/*.jpg`, `src/img/`, `tools/render_home.py`, `docs/DESIGN_SYSTEM.md`, `docs/VISAO_PRODUTO.md` e esta spec.
- Antes de cada commit: `npm run build`, os `node tests/*.mjs` e `pytest`. Resultado relatado com a saída real.

### 10.5 Fase 7.M — mapa com 10 vagas (nova, antes da 7.3)

- `tools/rooms/{edicao,imagens,revisao,videos}.yaml`: a segunda estação (`kind: visitor`, `monitor: true`) passa a ser `kind: agent`, com `slot: B`. A geometria e a mobília não mudam. Regenera o `office.tmj` com `build_map.py` (nada à mão, nada de tile por código).
- Vagas: 6 A (uma por sala de agente) + 4 B = **10**. Na sala, o pack ocupa a A. Os agentes do usuário vão para as B ou para salas que o usuário liberar.
- Efeito colateral: nessas 4 salas, o jogador perde a cadeira de visita **quando a vaga B está ocupada**. Planejamento e Direção continuam com a cadeira de visita da mesa de reunião. Vaga B vazia = o jogador pode sentar, como hoje.
- `tmj.test`: 10 assentos `kind: agent` alcançáveis a partir do spawn, cada um com tile livre ao lado e no máximo 2 vagas por sala.
- Aceite: render idêntico (a mobília não muda), testes verdes, captura da sede.

---

## 11. Ajustes aprovados para a execução (2026-11-04, 2ª rodada), que valem sobre §10

1. **Teto duplo de custo.** Cada teto existe em **créditos** (o que o usuário vê) e também em **US$ de custo real**, guardado à parte e independente da política provisória de preço. Vale por agente/dia e por workspace/dia. O teto em US$ protege a conta do provedor mesmo se o câmbio, a margem ou o preço do crédito mudarem.
   - Workspace/dia fica **bem abaixo da soma dos agentes**: **20 créditos/dia** (12 agentes × 5 = 60). O mensal é derivado (20 × 30 = 600 créditos), e um mês com menos gasto não acumula saldo para o seguinte.
   - Config: `STUDIO_AGENT_DAY_CAP_CREDITS=5`, `STUDIO_AGENT_DAY_CAP_USD=0.30`, `STUDIO_WORKSPACE_DAY_CAP_CREDITS=20`, `STUDIO_WORKSPACE_DAY_CAP_USD=1.25`, `STUDIO_MISSION_CAP_CREDITS=10`, `STUDIO_AGENT_TASK_CAP_CREDITS=1`. Para o mensal do workspace vale o **menor** valor entre o derivado e o teto mensal que já existe (`monthly_cap_usd`).
   - Um passo só roda se couber em **todos** os tetos, tanto em créditos quanto em US$. Se não couber em algum, a missão pausa e o motivo diz qual teto foi atingido.
2. **`claude-haiku-5-5` em `pricing.LLM_PRICES`**, com fonte e data, e o chat passa a ler o preço de lá. Teste: preço cadastrado, `llm_cost` correto e modelo sem preço recusado. **O modo real dos agentes genéricos só liga depois de o Chris confirmar o preço oficial**: até lá, uma flag (`STUDIO_AGENTS_REAL=0`) mantém o executor genérico no chamador simulado.
3. **Avatares por manifesto explícito.** `assets/characters/manifest.json` lista cada folha (`key`, `file`, `kind`: `pivoo` | `limezu`, rótulo). O script `tools/check_avatars.py` valida o manifesto contra os PNGs (tamanho exato do formato, arquivo existente, chave única). **Folha desconhecida ou fora do manifesto falha com erro claro**, sem ser ignorada em silêncio. O build roda a validação.
4. **`pack.json` validado por schema e versão** (`packs/schema.json`, JSON Schema). Antes de instalar um pack, o loader valida o schema e confere se a versão é inteira e não menor que a instalada. **Executor fora da lista fechada (`native:video_shopee`, `generic`) é rejeitado** com erro. O mesmo teste roda no Python e no Node.
5. **7.M:** o `tmj.test` garante:
   - todo assento de agente alcançável a partir do spawn, com tile livre ao lado;
   - **nenhum retângulo livre 3×3** dentro das salas de agente, para o mapa continuar mobiliado;
   - a cadeira de visita só deixa de existir para o jogador **quando a vaga B está ocupada**. Esse caso é testado com o `buildWorld` recebendo uma atribuição ocupada e outra vazia.
6. **Deploy das folhas:** anotado no `HANDOFF.md` (seção "Arte licenciada fora do git").
