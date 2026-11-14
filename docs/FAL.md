# Motor fal.ai (workflows)

Estado: implementado atras de flag (`STUDIO_VIDEO_ENGINE=gemini` e o padrao), **sem nenhuma chamada paga feita**. O motor Gemini nao foi alterado.

## Como funciona
O cliente envia **1 foto** e escolhe **Escuro** ou **Claro**. O Kiroo envia a foto ao workflow do estilo (`WORKFLOW_ID_DARK` / `WORKFLOW_ID_LIGHT`), acompanha por polling, baixa e valida os artefatos, compoe o MP4 com o FFmpeg do Kiroo e entrega **4 arquivos**:
`final.mp4` (~15 s, 9:16, narracao + trilha), `product_image_01.jpg` (Hero Shot), `product_image_02.jpg` (Lifestyle), `product_image_03.jpg` (Detalhes). Auxiliares: `cover.jpg`, `caption.txt`, `result.json`.

Codigo: `src/studio/providers/fal.py` (REST), `fal_contract.py` (pacote canonico), `fal_pipeline.py` (execucao), `agents/composer.py` (FFmpeg), `package_files.py` (validacao pelos bytes), `providers/simulated_fal.py` (DEMO e testes).

## Garantias
* **Nunca reenvia sozinho.** A tentativa e gravada antes do envio; envio sem resposta fica `fal_submit_uncertain` e pausa. Nova execucao so por `studio fal resubmit <pid>` (passa pelo paid_gate e pelo orcamento operacional).
* **Duplo clique:** `client_request_id` unico por workspace (indice unico no SQLite): a segunda criacao devolve a producao existente e nao reserva de novo.
* **Ledger inalterado.** A tentativa so vira `succeeded` na entrega completa; so entao `settle_pool` cobra. Falha tecnica nao cobra e o pre-orcamento volta (`close_pool`). Entrega incompleta ou em revisao mantem a reserva.
* **Entrega incompleta** (falta imagem): `delivery_status=incomplete`, producao `paused` com `pause_code=delivery_incomplete`, cliente ve "em finalizacao", nada e publicado em `delivery/`. Recuperacao pelo request_id do no (sem novo envio); depois, decisao do admin.
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
2. Salve o JSON do resultado em `tests/fixtures/fal_real/dark/result.json` e `.../light/result.json` (pasta ignorada pelo Git, pode conter a foto). Se possivel, rode com o header `X-Fal-Workflow-Envelope: true` para ter `nodes`.
3. Abra `profiles/fal/workflow_contract.json` e troque cada `A CONFIRMAR (Fase 0)`:
   * `input.image_field`: nome do campo da imagem no input; `input.extra`: campos fixos opcionais;
   * `output.video|narration|music|description|narration_text`: caminho ate cada item (`final.video.url`, `images.0.url`...);
   * `output.images.hero|lifestyle|details`: caminho de cada foto **pelo papel**, nunca pela ordem;
   * `recover.<papel>`: `node_id` do no que gera aquela imagem e `path` dentro da saida do no (permite buscar so ela de novo).
4. `python -m pytest tests/test_fal_real_fixtures.py` confere o contrato contra os resultados salvos.
5. Anote duracao do video, da narracao e da trilha, tempo de execucao e o custo (dashboard) para ajustar `operation_costs.json` (`workflow_dark` / `workflow_light`, hoje PLACEHOLDER de US$ 2,00).

## Fase 5 (voce, com orcamento): validacao paga
Conta de teste (admin), `STUDIO_VIDEO_ENGINE=fal` so nela (`workspaces.video_engine`), `STUDIO_MONTHLY_CAP_USD` baixo, 1 a 2 execucoes por estilo, `studio fal reconcile` para comparar estimado e real. **So com autorizacao explicita.**

## A CONFIRMAR / suposicoes
* Fluxo de upload (`rest.alpha.fal.ai/storage/upload/initiate` + PUT) segue o cliente oficial; a doc nao traz endpoint REST de upload.
* Header de lifecycle no upload, chaves do output, custo no workflow (se os nos somam ou duplicam no billing-events) e retencao do resultado na fila.
