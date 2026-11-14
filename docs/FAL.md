# Motor fal.ai (workflows)

Estado: implementado atras de flag (`STUDIO_VIDEO_ENGINE=gemini` e o padrao), **sem nenhuma chamada paga feita**. O motor Gemini nao foi alterado.

## Como funciona
O cliente envia **1 foto**; por enquanto so o estilo **Claro** e oferecido (sem seletor) e o envio vai sempre ao workflow Claro. O **Escuro** esta pronto no codigo, mas desligado por `STUDIO_FAL_DARK_ENABLED=false` (padrao): a tela nao o mostra e o servidor recusa `style=dark`; ligar a variavel traz de volta o seletor Escuro | Claro. O Kiroo envia a foto ao workflow do estilo (`WORKFLOW_ID_DARK` / `WORKFLOW_ID_LIGHT`), acompanha por polling, baixa e valida os artefatos, confere o video com o FFmpeg do Kiroo e entrega:
`final.mp4` (~15 s, 9:16, **ja com a narracao embutida, sem musica**), `product_image_01.jpg` (1 foto hero) e `caption.txt` (titulo + legenda + identificacao de publicidade). Auxiliares: `cover.jpg` (quadro do video) e `result.json` (historico).

### Escopo real do workflow (o `wf02` Escuro tem a mesma estrutura do `wf01`)
* **Input:** so `image_url`. `descricao_produto` existe no schema, mas nao esta ligada a nenhum no: nao e enviada.
* **Saidas usadas:** `video` (`video.url`), `images` (a foto hero, `images[0].url`; **confirmar o indice na fixture real**) e `output` (texto com JSON `{"title","caption"}`).
* **Ignorada:** `audio` / `audio_2` do display e arquivo intermediario de TTS; nunca e entregue nem validada.
* **Nao ha musica.** Isso nao e falha nem aviso.
* **Texto:** `output` e lido como JSON (aceita cerca ```json). Invalido, vazio ou com `title`/`caption` vazios (o prompt manda devolver strings vazias se nao identificar o produto): a entrega segue **com aviso**, `caption.txt` leva so a identificacao de publicidade e o Kiroo **nunca inventa texto**.

### O que o Kiroo faz com o video (`agents/composer.py`)
Sem mixagem, trilha, ducking, loudnorm ou `atempo`. So:
1. `ffprobe`: precisa ter stream de **video e de audio**. Sem audio (ou sem video) = **falha tecnica, sem debito**.
2. Janela de **14 a 16 s**: dentro, **copia sem reencode**; mais longo, corta em 15 s com fade e reencoda; mais curto, estende com o ultimo quadro (e silencio) ate 2 s e reencoda (alem disso, revisao do admin).
3. Extrai `cover.jpg`.

Codigo: `src/studio/providers/fal.py` (REST), `fal_contract.py` (pacote canonico), `fal_pipeline.py` (execucao), `agents/composer.py` (FFmpeg), `package_files.py` (validacao pelos bytes), `providers/simulated_fal.py` (DEMO e testes).

## Garantias
* **Nunca reenvia sozinho.** A tentativa e gravada antes do envio; envio sem resposta fica `fal_submit_uncertain` e pausa. Nova execucao so por `studio fal resubmit <pid>` (passa pelo paid_gate e pelo orcamento operacional).
* **Duplo clique:** `client_request_id` unico por workspace (indice unico no SQLite): a segunda criacao devolve a producao existente e nao reserva de novo.
* **Ledger inalterado.** A tentativa so vira `succeeded` na entrega completa; so entao `settle_pool` cobra. Falha tecnica nao cobra e o pre-orcamento volta (`close_pool`). Entrega incompleta ou em revisao mantem a reserva.
* **Entrega incompleta** (falta a **foto hero**): `delivery_status=incomplete`, producao `paused` com `pause_code=delivery_incomplete`, cliente ve "em finalizacao", nada e publicado em `delivery/`. Recuperacao pelo request_id do no (sem novo envio); depois, decisao do admin (se a missao for encerrada assim, a tela diz "Entrega parcial", nao "Missao cancelada"). **Falta de titulo/legenda nao entra aqui:** e so aviso. **Falta de video ou video sem audio:** falha tecnica, sem debito.
* **Custo real** (`studio fal reconcile`) grava `confirmed_cost_usd` por billing-events, so em tentativas ja decididas no ledger, e **nunca gera debito**. O cliente paga o valor fixo por estilo.
* **Retencao:** so `workflow/attempt_NN/*` (menos `result.json`) e limpo apos `STUDIO_FAL_RETENTION_DAYS`; `delivery/` nunca.

## Comandos do administrador
```
studio fal list
studio fal recover|deliver-partial|resubmit|waive <pid> [--reason ...]
studio fal adopt <pid> --request-id <id>     # envio incerto que existe na fal.ai
studio fal not-sent <pid>                    # envio incerto que NAO existe la
studio fal reconcile [pid]                   # custo real (exige FAL_BILLING_KEY)
studio fal cleanup [--days N]
studio doctor                                # mostra so se as variaveis existem
```

## Fase 0 (voce): preencher o contrato
1. No playground da fal.ai, rode **cada workflow uma vez** (Escuro e Claro) com uma foto de teste.
2. Salve o JSON do resultado em `tests/fixtures/fal_real/dark/result.json` e `.../light/result.json` (pasta ignorada pelo Git, pode conter a foto; nao a confunda com `tests/fixtures/fal_shape/`, que e sintetica e versionada). Se possivel, rode com o header `X-Fal-Workflow-Envelope: true` para ter `nodes`.
3. `profiles/fal/workflow_contract.json` ja esta **CONFIRMADO** com a resposta real do wf01 Claro: `input.image_field=image_url`, `output.video=video.url`, `output.image=images.0.url`, `output.text=output`. O `output` e **texto**, normalmente em cerca markdown (```json ... ```): o parser remove cerca com ou sem rotulo, BOM e espacos, e continua aceitando JSON puro. `file_name`/`file_size` da imagem vem `null`: nada depende deles. A caption tem emoji; `caption.txt` e gravado em UTF-8 (bytes, sem traducao de quebra de linha). A forma da resposta esta em `tests/fixtures/fal_shape/light_result.json` (**sintetica**, URLs falsas). Continua **A CONFIRMAR**, mas **sem bloquear o envio** (lista `pending_recover`): o envio real do Claro esta liberado, sempre com `X-Fal-Workflow-Envelope: true`, e o envelope bruto fica em `workflow/attempt_NN/result.json` (chave `raw`) para confirmar os itens apos a primeira rodada real. Eles bloqueiam so a **recuperacao de foto pelo no** (recusada; fica manual: `delivery_incomplete` e decisao do admin). `pending` (lista vazia) continua bloqueando o envio se algo for colocado nela:
   * `recover.hero`: `node_id` `node-oTeZSiC32m` e `path` `images.0.url` sao so proposta (no do hero);
   * se cada no traz `request_id` no envelope (`X-Fal-Workflow-Envelope`);
   * a rodada real do wf02 Escuro (mesma estrutura esperada).
   Ao confirmar, apague os itens de `pending_recover` e o provider passa a recuperar a foto pelo no.
4. `python -m pytest tests/test_fal_real_fixtures.py` confere o contrato contra os resultados salvos.
5. Anote a duracao do video (e se o audio vem mesmo embutido), tempo de execucao e o custo (dashboard) para ajustar `operation_costs.json` (`workflow_dark` / `workflow_light`, hoje PLACEHOLDER de US$ 2,00).

## Fase 5 (voce, com orcamento): validacao paga
Conta de teste (admin), `STUDIO_VIDEO_ENGINE=fal` so nela (`workspaces.video_engine`), `STUDIO_MONTHLY_CAP_USD` baixo, 1 a 2 execucoes por estilo, `studio fal reconcile` para comparar estimado e real. **So com autorizacao explicita.**

## A CONFIRMAR / suposicoes
* Fluxo de upload (`rest.alpha.fal.ai/storage/upload/initiate` + PUT) segue o cliente oficial; a doc nao traz endpoint REST de upload.
* Header de lifecycle no upload, chaves do output, custo no workflow (se os nos somam ou duplicam no billing-events) e retencao do resultado na fila.
