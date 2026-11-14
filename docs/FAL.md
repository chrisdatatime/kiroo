# Motor fal.ai (workflows)

Estado: implementado atras de flag (`STUDIO_VIDEO_ENGINE=gemini` e o padrao), **sem nenhuma chamada paga feita**. O motor Gemini nao foi alterado.

## Como funciona
O cliente envia **1 foto**, escolhe o **cenario** (`home_light` padrao, `studio`, `natural`, `dark_premium`), a **plataforma** (`shopee_video` padrao, `tiktok_shop`, `mercado_livre`) e, se quiser, o nome do produto. Existe **UM unico workflow** (`WORKFLOW_ID`, padrao `workflows/christiandeluco/wf01white`) para qualquer combinacao: nao ha workflow por cenario nem por plataforma. O servidor monta os 6 inputs em `src/studio/prompts/production.py` (`build_fal_arguments`) a partir de dicionarios fixos; o cliente so manda IDs (allowlist; fora dela = 400) e **nunca** texto de prompt. O Kiroo envia, acompanha por polling, baixa e valida os artefatos, confere o video com o FFmpeg do Kiroo e entrega:
`final.mp4` (~15 s, 9:16, **ja com a narracao embutida, sem musica**), `product_image_01.jpg` (1 foto hero) e `caption.txt` (titulo + legenda + identificacao de publicidade). Auxiliares: `cover.jpg` (quadro do video) e `result.json` (historico).

### Escopo real do workflow (wf01white, 6 inputs)
* **Inputs (6):** templates fixos versionados (`PROMPT_VERSION`, gravado em `usage_json.prompt_version`), com os prompts ORIGINAIS de cada no como base (`profiles/fal/wf01white_original_prompts.json`) e cenario/plataforma/produto so como variaveis. `image_url`; `scene_prompt` -> os DOIS FLUX Kontext (preservacao + ENVIRONMENT do cenario + blocos `LIFESTYLE FRAME` e `HERO FRAME` + restricoes; cada no deve citar o seu bloco no fal); `platform_strategy` -> system prompt da NARRACAO (regras originais + 22 a 26 palavras, max. 28, + voz/CTA da plataforma); `product_context` -> system prompt do Vision (regras originais de identificacao + saida rotulada + bloco final `DADOS DO VENDEDOR ... <<<nome>>>`, max. 80 caracteres, so dado); `video_prompt` -> H3 (SHOT 1/2/3 com cortes claros, tempos e ritmo da plataforma, ambiente e luz do cenario, sem musica, narracao preservada); A direcao por plataforma (gancho, ritmo, camera, transicoes, argumento, titulo, legenda, CTA) vem de `docs/PLATFORM_STRATEGY.md` e vive em `PLATFORM_PROFILES` como dado estruturado (hipoteses criativas, nao conversao comprovada; slot `evidence.benchmarks` para metricas futuras). `copywriting_prompt` -> titulo e legenda (regras originais + regras da plataforma; JSON `{"title","caption"}`). `python scripts/dry_run_prompts.py --scene studio --platform tiktok_shop --name "Fone X"` imprime os 6 sem chamar a fal.ai.
* **Saidas usadas:** `video` (`video.url`), `images` (a foto hero, `images[0].url`; **confirmar o indice na fixture real**) e `output` (texto com JSON `{"title","caption"}`).
* **Ignorada:** `audio` / `audio_2` do display e arquivo intermediario de TTS; nunca e entregue nem validada.
* **Nao ha musica.** Isso nao e falha nem aviso.
* **Texto:** `output` e lido como JSON (aceita cerca ```json). Invalido, vazio ou com `title`/`caption` vazios (o prompt manda descrever de forma generica e honesta, nunca devolver vazio; o parser segue defensivo): a entrega segue **com aviso**, `caption.txt` leva so a identificacao de publicidade e o Kiroo **nunca inventa texto**.

### Duracao da narracao
* Saidas OPCIONAIS do display (contrato `output.narration_audio` / `output.narration_text`): `narration_audio: $node-DTAPZaYmdb.audio` (audio do ElevenLabs) e `narration_text: $node-kBVy7SS8xC.output` (texto falado). Nao entram na entrega nem no front.
* Com `narration_audio`: o Kiroo baixa o arquivo, mede com `ffprobe` e grava `usage_json.narration_seconds` (`narration.source = workflow_audio`). `narration_text` vai para `usage_json.narration_text` (+ `narration_words`).
* Sem o campo (ou audio ilegivel/download falhou): fallback pelo **fim da fala** na trilha do video (`silencedetect` a -35 dB, `narration.source = video_audio_track`, `narration.reaches_end`). **A trilha final do H3 (~15,1 s fixos) sozinha nao prova a duracao da narracao**: o H3 recebe o audio em `target_audio_url` e corta o que passar de 15 s.
* Acima de 14,5 s: evento `narration_too_long` e `usage_json.narration_warning`, sem quebrar a entrega, sem cobrar a mais e sem reprocessar.
* Exports reais (14/11): narracao do ElevenLabs com o prompt original de 25-32 palavras = 14,1 s e 15,9 s.

### O que o Kiroo faz com o video (`agents/composer.py`)
Sem mixagem, trilha, ducking, loudnorm ou `atempo`. So:
1. `ffprobe`: precisa ter stream de **video e de audio**. Sem audio (ou sem video) = **falha tecnica, sem debito**.
2. Janela de **14 a 16 s**: dentro, **copia sem reencode**; mais longo, corta em 15 s com fade e reencoda; mais curto, estende com o ultimo quadro (e silencio) ate 2 s e reencoda (alem disso, revisao do admin).
3. Extrai `cover.jpg`.

Codigo: `src/studio/providers/fal.py` (REST), `fal_contract.py` (pacote canonico), `fal_pipeline.py` (execucao), `agents/composer.py` (FFmpeg), `package_files.py` (validacao pelos bytes), `providers/simulated_fal.py` (DEMO e testes).

## Fluxo na interface
* **Nova produção** (modal so de envio; desktop = modal horizontal, celular = bottom sheet): foto (solte ou escolha), nome opcional, cenario (cartoes com miniatura), plataforma (cartoes com logo) e UM botao **"Criar video · N creditos"** (o mesmo pre-orcamento reservado e conferido no `/confirm`, igual para qualquer combinacao). A previa e so ilustrativa (CSS). Cenario com `early_access_plan` em `SCENES` (hoje nenhum) fica bloqueado para planos menores: 403 `early_access` e cadeado "Disponivel no plano Escala" na tela. Clicar = consentimento: o frontend faz `create -> confirm -> run` com `await`; se um passo falha, o modal fica aberto com a mensagem do servidor. So depois do `/run` aceito ele fecha e abre a Missao.
* **A criacao nao inicia nada** (antes ela disparava o laco, que parava em `validated` e a tela dizia "Preparando"). Quem inicia e o `/run`.
* **Idempotencia:** `/confirm` e `/run` devolvem **409 `already_started`** se a producao ja tem tentativa ativa/concluida ou execucao em andamento (`fal_pipeline.started_message`). `/run` tambem recusa sem a confirmacao do custo (`needs_confirmation`) e quando o limite de gastos barraria o envio (`spend_limit`, "Seu limite mensal foi atingido"), sem pausar nada. Nunca ha segundo job para a mesma producao sem `studio fal resubmit`.
* **Missao:** esteira de 6 etapas (PLANEJAMENTO, ROTEIRO, IMAGENS, VIDEOS, REVISAO, EDICAO) com o avanco **estimado pelo tempo** desde o envio (`EST_WORKFLOW_S` = 180 s em `frontend/src/ui/falFlow.js`; a fal so informa fila/andamento/concluido). EDICAO so conclui com a entrega validada. Status sempre do servidor: "Aguardando voce", etapa estimada, "Pausada: limite mensal atingido", "Nao deu certo. Nada foi cobrado.", "Pronto" + entrega na propria Missao.
* **Preco:** `workflow` (operation_costs.json) = US$ 0,60 (medido ~0,52 + folga) como reserva interna; o cliente paga **20 creditos fixos**.

## Garantias
* **Nunca reenvia sozinho.** A tentativa e gravada antes do envio; envio sem resposta fica `fal_submit_uncertain` e pausa. Nova execucao so por `studio fal resubmit <pid>` (passa pelo paid_gate e pelo orcamento operacional).
* **Duplo clique:** `client_request_id` unico por workspace (indice unico no SQLite): a segunda criacao devolve a producao existente e nao reserva de novo.
* **Ledger inalterado.** A tentativa so vira `succeeded` na entrega completa; so entao `settle_pool` cobra. Falha tecnica nao cobra e o pre-orcamento volta (`close_pool`). Entrega incompleta ou em revisao mantem a reserva.
* **Entrega incompleta** (falta a **foto hero**): `delivery_status=incomplete`, producao `paused` com `pause_code=delivery_incomplete`, cliente ve "em finalizacao", nada e publicado em `delivery/`. Recuperacao pelo request_id do no (sem novo envio); depois, decisao do admin (se a missao for encerrada assim, a tela diz "Entrega parcial", nao "Missao cancelada"). **Falta de titulo/legenda nao entra aqui:** e so aviso. **Falta de video ou video sem audio:** falha tecnica, sem debito.
* **Custo real** (`studio fal reconcile`) grava `confirmed_cost_usd` por billing-events, so em tentativas ja decididas no ledger, e **nunca gera debito**. O cliente paga o valor fixo do video (20 creditos).
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
1. No playground da fal.ai, rode o **wf01white uma vez** (com os 6 inputs, de preferencia 1 cenario escuro e 1 claro) com uma foto de teste.
2. Salve o JSON do resultado em `tests/fixtures/fal_real/<nome>/result.json` (pasta ignorada pelo Git, pode conter a foto; nao a confunda com `tests/fixtures/fal_shape/`, que e sintetica e versionada). Se possivel, rode com o header `X-Fal-Workflow-Envelope: true` para ter `nodes`.
3. `profiles/fal/workflow_contract.json` ja esta **CONFIRMADO** com a resposta real do wf01: `input.fields` = os 6 inputs, `output.video=video.url`, `output.image=images.0.url`, `output.text=output`. O `output` e **texto**, normalmente em cerca markdown (```json ... ```): o parser remove cerca com ou sem rotulo, BOM e espacos, e continua aceitando JSON puro. `file_name`/`file_size` da imagem vem `null`: nada depende deles. A caption tem emoji; `caption.txt` e gravado em UTF-8 (bytes, sem traducao de quebra de linha). A forma da resposta esta em `tests/fixtures/fal_shape/light_result.json` (**sintetica**, URLs falsas). Continua **A CONFIRMAR**, mas **sem bloquear o envio** (lista `pending_recover`): o envio real esta liberado, sempre com `X-Fal-Workflow-Envelope: true`, e o envelope bruto fica em `workflow/attempt_NN/result.json` (chave `raw`) para confirmar os itens apos a primeira rodada real. Eles bloqueiam so a **recuperacao de foto pelo no** (recusada; fica manual: `delivery_incomplete` e decisao do admin). `pending` (lista vazia) continua bloqueando o envio se algo for colocado nela:
   * `recover.hero`: `node_id` `node-oTeZSiC32m` e `path` `images.0.url` sao so proposta (no do hero);
   * se cada no traz `request_id` no envelope (`X-Fal-Workflow-Envelope`);
   * o formato do `output` do no de texto (JSON `title/caption`): a primeira execucao real loga o texto bruto (`output bruto do no de texto`) e o guarda em `usage_json.text_output`.
   Ao confirmar, apague os itens de `pending_recover` e o provider passa a recuperar a foto pelo no.
4. `python -m pytest tests/test_fal_real_fixtures.py` confere o contrato contra os resultados salvos.
5. Anote a duracao do video (e se o audio vem mesmo embutido), tempo de execucao e o custo (dashboard) para ajustar `operation_costs.json` (`workflow`, hoje US$ 0,60).

## Fase 5 (voce, com orcamento): validacao paga
Conta de teste (admin), `STUDIO_VIDEO_ENGINE=fal` so nela (`workspaces.video_engine`), `STUDIO_MONTHLY_CAP_USD` baixo, 1 a 2 execucoes por cenario, `studio fal reconcile` para comparar estimado e real. **So com autorizacao explicita.**

## A CONFIRMAR / suposicoes
* Fluxo de upload (`rest.alpha.fal.ai/storage/upload/initiate` + PUT) segue o cliente oficial; a doc nao traz endpoint REST de upload.
* Header de lifecycle no upload, chaves do output, custo no workflow (se os nos somam ou duplicam no billing-events) e retencao do resultado na fila.
