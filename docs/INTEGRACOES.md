# Integrações — o que a documentação oficial diz (consulta em 26/10/2026)

Verifique novamente antes de qualquer execução paga. Nada abaixo foi executado contra a API real ainda.

## Resumo das decisões

| Função | Opção escolhida (padrão) | Status no código |
|---|---|---|
| Imagem com referências | Gemini API · `gemini-nano-banana-2.1` (Nano Banana 2.1) · 9:16 · 2K | adaptador escrito, **não executado** |
| Animação da imagem aprovada | Gemini API · `gemini-omni-1.1-flash` (Gemini Omni Flash) · image-to-video · 720p | adaptador escrito, **não executado** |
| Planejamento e revisão multimodal | Gemini API · `gemini-3.8-flash` | adaptador escrito, **não executado** |
| Edição | FFmpeg 9.0.2 local | **funcionando e testado** |
| Publicação | nenhuma (fora do MVP) | só interface `Publisher` |

Todos os modelos são configuráveis em `.env`. Uma única chave (`GEMINI_API_KEY`) cobre as três funções de IA.

## Gemini API: imagens

Fonte: https://ai.google.dev/gemini-api/docs/image-generation

- Modelos listados: `gemini-nano-banana-2.1` (recomendado para novos projetos), `gemini-3.1-flash-lite-image` (Nano Banana 2 Lite), `gemini-3.1-flash-image` (Nano Banana 2), `gemini-3-pro-image` (Nano Banana Pro), `gemini-2.5-flash-image` (legado).
- Até 14 imagens de referência por pedido. Os limites por tipo (objeto/personagem) variam por modelo; a tabela da página é ambígua — confirmar no primeiro teste real.
- `response_format`: `aspect_ratio` e `image_size` (`1K`, `2K`, `4K`). A página não confirma 9:16 para todos os modelos de forma explícita.
- Todas as imagens geradas têm marca d'água SynthID.

## Gemini API: vídeo

Fontes: https://ai.google.dev/gemini-api/docs/video · https://ai.google.dev/gemini-api/docs/omni

- **Veo 3.1 Preview (`veo-3.1-*-preview`) foi desligado na Gemini API em 22/10/2026.** A recomendação oficial é migrar para o **Gemini Omni Flash** (`gemini-omni-1.1-flash`) ou usar Veo GA pela **Gemini Enterprise Agent Platform** (antigo Vertex AI, exige projeto Google Cloud com faturamento).
- Omni Flash aceita imagem inicial + prompt (image-to-video), 9:16, resoluções 360p/720p (padrão)/1080p e 4K (as duas últimas por upscale), saída até ~10 s por geração (extensões até 40 s).
- **Áudio é gerado por padrão**, sem chave documentada para desligar: o prompt pede silêncio e a montagem descarta o áudio dos takes; a revisão mede o volume e sinaliza fala/áudio.
- A documentação diz que apenas inglês tem suporte completo → os prompts de geração estão em inglês; roteiro, revisão e interface ficam em português.
- Restrições: imagens com "certas pessoas reconhecíveis" não são suportadas; edição de vídeos enviados não funciona na UE/Suíça/Reino Unido. Negative prompt não é suportado (usar "Do not…").
- Todos os vídeos têm SynthID.

## Interactions API (usada pelos adaptadores)

Fonte: https://ai.google.dev/gemini-api/docs/interactions

- GA, recomendada para novos projetos. `background=True` executa em segundo plano; `client.interactions.get(id)` consulta. O SDK `google-genai` 2.33.0 expõe `status` com valores `in_progress`, `queued`, `completed`, `failed`, `cancelled`, `incomplete`, `budget_exceeded`, `requires_action`, e `usage` com tokens.
- Interações ficam guardadas por 55 dias no plano pago (1 dia no gratuito). O código persiste o `id` remoto e retoma a consulta após reinício.

## Preços (fonte: https://ai.google.dev/gemini-api/docs/pricing, "Last updated 2026-10-26")

| Item | Preço usado na estimativa | Confiança |
|---|---|---|
| Nano Banana 2.1, saída 1K / 2K / 4K | ~US$0,0336 / ~US$0,0504 / ~US$0,113 por imagem | oficial (aproximado) |
| Nano Banana Pro, 1K–2K / 4K | US$0,134 / US$0,24 por imagem | oficial |
| Omni Flash 720p | ~US$0,10 por segundo | oficial (aproximado) |
| Omni Flash 1080p | ~US$0,152 por segundo | **terceiros** (opper.ai) — sem valor oficial |
| Gemini 3.8 Flash | US$0,75 entrada / US$3,75 saída por 1M tokens (até 31/12/2026) | oficial |

- Nenhum modelo de imagem/vídeo tem camada gratuita.
- A estimativa de vídeo assume 10 s por geração (a duração não é fixável pela doc consultada). Uma produção de 3 cenas custa por volta de **US$3,20** (3 imagens + 3 vídeos de 720p), sem refações.
- A API não devolve custo final por chamada: o sistema registra `confirmed_cost_usd = vazio` e guarda tokens de uso. A confirmação vem da fatura no Google Cloud/AI Studio.

## Assinatura x API

Fonte: https://ai.google.dev/gemini-api/docs/google-ai-plans

- Os benefícios do Google AI Pro/Ultra valem só na interface web (Gemini, Flow, AI Studio UI). **Uso da Gemini API por chave é cobrado à parte** (faturamento do Cloud/AI Studio).

## Google Flow

- Não encontrei API pública oficial do Flow. As fontes descrevem o Flow como produto acessado pela assinatura (Google AI Plus/Pro/Ultra ou Workspace), com restrição de idade e região.
- **Diferença prática**: chamar o modelo pela API reproduz a lógica "foto aprovada → animação" com prompt e parâmetros controlados por nós, com custo por segundo e rastreabilidade completa; não inclui ferramentas da interface do Flow (projetos, cenas, extensão visual, créditos da assinatura). O modelo usado pela API pode não ser o mesmo que o Flow usa naquele momento — a qualidade precisa ser comparada lado a lado no Marco 2.
- Automação de navegador sobre o Flow **não** foi implementada: dependeria de login, quebraria com mudanças de interface e pode violar termos. Só reavaliar com sua decisão explícita.

## Shopee

- Open API de Afiliados (acesso não liberado na sua conta, segundo o histórico): oferece ofertas, links curtos e relatórios. Não encontrei endpoint de upload/publicação de Shopee Vídeo. O MVP entrega um pacote para publicação manual.
