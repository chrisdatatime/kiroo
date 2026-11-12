# Arquitetura

```
CLI (studio …) / Interface (studio ui) ← operador (aprovações, correções, orçamento, config. dos agentes)
  └─ Orchestrator (orchestrator.py)  ← estados, dependências, tentativas, orçamento, retomada
       ├─ Preparação do produto      agents/product_prep.py   (determinístico)
       ├─ Direção criativa           agents/creative.py       (template + Planner IA + validação)
       ├─ Produção de imagens        ImageGenerator           (submit/poll)
       ├─ Revisão visual             agents/visual_review.py  (checagens técnicas + Reviewer IA)
       ├─ Produção de vídeos         VideoGenerator           (submit/poll, só imagem aprovada)
       └─ Edição e entrega           agents/editing.py + ffmpeg.py (plano validado → FFmpeg)
  Persistência: SQLite (db.py) · arquivos por produção (storage.py) · perfis congelados (profiles.py)
  Provedores: providers/simulated.py (SIMULADO) · providers/gemini.py (real, não validado)
```

Agentes de desenvolvimento (Claude Code) e agentes da aplicação são coisas distintas: a aplicação roda sozinha via CLI, sem conversa aberta.

## Estados

Produção: `received → validated → scripted → producing → editing → awaiting_final_review → completed`, com `awaiting_references`, `paused` (volta ao estado anterior), `failed`, `cancelled`.

Cena: `pending → generating_image → awaiting_image_approval → image_approved → generating_video → awaiting_video_approval → video_approved`, com `blocked` (tentativas esgotadas/falha permanente). Cenas 2 e 3 só começam após a imagem da cena 1 ser aprovada (referência de continuidade).

## Tentativas e retomada

- Cada geração é uma linha em `attempts` com prompt, parâmetros, referências (caminho + sha256), id remoto, saída, erro, tempos, custo estimado e confirmado.
- `submit` grava o id remoto imediatamente; após reinício, `poll` consulta a mesma operação (retomada). Uma **nova tentativa** é outra linha.
- Erros transitórios: mesma tentativa, espera exponencial (2 s, 4 s, 8 s, 16 s; máx. 4). Permanentes: tentativa falha e conta no limite por cena.
- Entrada idêntica (hash de provedor + modelo + prompt + parâmetros + hashes das referências) com resultado não reprovado é reaproveitada sem nova chamada.
- Mudança de prompt de imagem → refaz imagem e vídeo da cena e invalida cenas dependentes. Mudança de prompt de animação → refaz só o vídeo. Nova imagem aprovada da cena 1 → cenas 2 e 3 voltam a `pending`. Nada é apagado: resultados antigos ficam `superseded`.

## Fidelidade ao produto (`agents/fidelity.py`)

- **Ficha técnica visual** (`product_facts.json`, coluna `facts_json`): antes do roteiro, o planner Gemini olha as fotos
  oficiais (texto multimodal, operação `facts`, ~US$0,01, uma vez por conjunto de fotos) e devolve cor, botões (quantidade
  e posição), lado esquerdo/direito, cabo, logos, proporções, assimetria e complexidade. Sem IA (DEMO) ou com falha, a
  ficha repete só os atributos digitados. O bloco `PRODUCT SPEC SHEET` vai em todo prompt de imagem e de vídeo e no
  planner; os itens viram critérios `CRÍTICO` do revisor.
- **Prompt negativo padrão** (`DEFAULT_NEGATIVE_EN`): dedos extras, partes inventadas, lado trocado/espelhado, logos
  alterados — em toda imagem e vídeo.
- **Correções acumulativas** (`{image,video}_corrections_json` por cena): cada nova tentativa recebe as correções
  anteriores como "ALREADY FIXED, KEEP IT FIXED" e a última como "NEW". Antes, só a última ia no prompt e consertar a
  mão desfazia o conserto do produto. Zera ao aprovar.
- **Revisor com gravidade**: `critical_issues` (produto) reprova; `aesthetic_issues` (mãos, luz) vira aviso e a cena
  segue para o operador. Falha técnica (proporção/duração) continua bloqueante. Exceção: em "Produto em destaque" mão ou
  pessoa é sempre crítica (ver abaixo).
- **Limite padrão de 2 imagens automáticas** por cena (`STUDIO_MAX_IMAGE_ATTEMPTS`). Esgotado, a cena fica
  `blocked` e a revisão mostra as versões lado a lado; `POST /api/productions/<id>/choose {scene, stage, attempt_id}`
  aprova uma com um clique.
- **Imagem-âncora** (`POST .../anchor {attempt_id}`; vazio remove): uma imagem gerada e fiel vira a primeira referência
  do produto (`product:anchor`) nas próximas gerações.
- **Sugestão de formato**: produto assimétrico/complexo em "Somente mãos" → aviso para usar "Produto em destaque"
  (heurística gratuita na prévia da Direção; confirmado pela ficha técnica no roteiro). Não troca nem pausa sozinho.
- Cada reprovação/aviso grava o evento `retry_reason` com categorias fixas (métricas do administrador).

## Apresentação → formato (invariante)

- A apresentação gravada na ficha (`product.creative.presentation`) é a ÚNICA fonte do formato:
  `creative_options.profile_ids` dá `format_id` (Somente mãos → `maos_3cenas_15s`, Produto em destaque →
  `produto_3cenas_15s`, Com apresentadora → `bia_3cenas_15s`) e a direção de arte (ambiente). Criação, substituição da
  ficha e Direção passam por `Orchestrator._sync_format` (evento `format_changed`/`art_direction_changed`; troca de
  formato remove a imagem-âncora e o aviso de formato).
- **Barreira antes de gastar** (`format_problems` + `_enforce_format`): em `validated/scripted/producing/editing` e
  antes de criar ou enviar qualquer tentativa de imagem/vídeo, confere `format_id`, perfil congelado, ficha validada,
  roteiro e modo de cada cena. Inconsistente → evento `format_invariant`, recalcula e volta à validação (sem custo); se
  não fechar em 2 tentativas, `failed` com o motivo. A direção de arte é sincronizada, mas não entra nessa barreira (uma
  produção antiga em andamento não perde cenas aprovadas por causa do cenário).
- Produção do app criada sem Direção (`direction_required`, migração 8): formato provisório, nada é roteirizado nem
  gerado até a Direção. `POST .../direction` sem `creative.presentation` explícita é recusado (antes virava "Somente
  mãos" em silêncio).
- **Produto em destaque**: negativo próprio (`PRODUCT_ONLY_NEGATIVE_EN`, sem falar de dedos) e a trava final
  `PRODUCT_ONLY_LOCK_EN` no fim de todo prompt de imagem e vídeo (depois de treino e correções); planejador instruído sem
  "ação das mãos"; roteiro que perca o bloqueio de pessoas é recusado (`validate_script`); revisor reprova qualquer
  mão/pessoa (`fidelity.enforce_product_only`, motivo `pessoa_proibida`), então a cena não chega ao vídeo.
- `production_created` guarda o commit do código que criou a produção (`buildinfo.commit`; Docker: `STUDIO_BUILD_COMMIT`).

## Cancelamento

`cancel` é definitivo: tentativas ainda não enviadas viram falha sem custo; as que já estavam no provedor são
abandonadas sem cobrança do cliente (`cancel_inflight`); `_hold`, `_submit` e `_poll` recusam/descartam qualquer chamada
depois disso; o pré-orçamento não usado volta. O servidor recusa (409) toda ação de avançar numa missão cancelada ou
que falhou, e o `/api/state` marca `ended`, `running: false`, cenas paradas como "Interrompida" e agentes parados.

## Orçamento

Antes de cada chamada paga: `comprometido + estimativa ≤ limite`, senão a produção pausa com motivo. Comprometido = custo confirmado quando houver, senão estimado (no simulado, sempre o estimado equivalente). Concorrência limitada por `STUDIO_MAX_INFLIGHT_OPS`.

## Pasta de uma produção (`data/productions/<id>/`)

```
inputs/references/        cópias das fotos oficiais (nome = papel + hash)
inputs/profile_assets/    cópia da referência da Bia usada
profiles_snapshot.json    perfis congelados
sheet.json                ficha validada (fatos, alegações, desconhecidos, alertas)
script.json / script.md   roteiro estruturado e legível
prompts/                  prompt por cena e ferramenta
scenes/scene_N/images|videos|frames/   todas as tentativas e quadros amostrados
reports/                  review_report.md, cost_report.md/.json, execution_log.md
delivery/                 final.mp4, cover.jpg, caption.txt, product.json, approved/, relatórios
```

## Interface local

`web/server.py` (stdlib, 127.0.0.1) + `web/static/index.html` (SVG isométrico, sem dependências externas).
`web/view.py` deriva o status de cada agente dos estados e eventos persistidos — nada é encenado.
Execuções disparadas pela interface rodam em thread por produção; em produções simuladas o ritmo é
desacelerado para ser acompanhável. Configuração editável: `agent_config.py` → `data/agents.json`
(precedência: padrão → .env → agents.json), com validação contra a tabela de preços.
