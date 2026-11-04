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
