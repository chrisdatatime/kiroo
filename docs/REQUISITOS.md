# Requisitos, decisões e pendências

Fontes: prompt de construção (26/10/2026) e `AFILIADO/ByteCerto_historico_para_outra_IA.md`.
O histórico foi entregue como **Markdown** (não PDF) e declara ser uma reconstrução organizada, sem os anexos binários embutidos. Ele foi lido por completo (462 linhas).

## Entendimento do histórico (estado mais recente)

- Foco exclusivo: Shopee, formato Shopee Vídeo. Personagem: Bia (apresentadora virtual).
- Esteira manual atual por cena: fotos oficiais → Gemini (imagem) → aprovação → Flow (animação dessa imagem) → montagem.
- Produto em andamento: copo azul-claro com alça, sem rosto, sem fala, 3 cenas, ~15 s, cozinha paulistana de alto padrão, mãos com manicure nude rosado.
- Nada sobre o copo foi comprovado além do visual (capacidade, material, vedação, térmico: desconhecidos). O item do link curto não foi confirmado como o da gravação de tela.
- A restrição do histórico de "não voltar à arquitetura de agentes" foi substituída pelo pedido atual de construir a automação.

## Inventário de referências

| Item | Situação |
|---|---|
| `PERFIL BIA.jpg` | **Disponível** em `AFILIADO/SHOPEE/`; copiado para `assets/bia/` (perfil `bia@v1`) |
| `BIA CORPO INTEIRO.jpg`, `QUARTO BIA.jpg`, `Captura de tela ...161438` | Disponíveis; ainda não usados em perfis |
| Regatas (`PRODUTO 01.webp`, `PRODUTO 01 BIA - CROPPED.jpg`, takes em `PRODUTO 01/`) | Disponíveis; produto anterior |
| CSV com 100 produtos | Disponível; fora do MVP (sem descoberta automática) |
| **Fotos oficiais do copo com alça** | **AUSENTES** — necessárias para a primeira produção real |
| `ScreenRecording_10-26-2026 17-33-51_1.mp4` (copo) | **AUSENTE** do disco; serviria só como contexto |
| Imagens `image(20261026-*).png` citadas no histórico | Ausentes com esses nomes |

## Decisões tomadas (reversíveis)

1. **Python modular + SQLite + FFmpeg + CLI.** Sem servidor, fila ou banco externo no MVP.
2. **Sem LangGraph.** O fluxo é um DAG fixo e curto, com portões humanos que duram horas/dias. O estado já precisa viver num banco próprio (cenas, tentativas, custos, auditoria); um checkpointer de framework duplicaria isso. Reavaliar se surgirem fluxos ramificados por produto.
3. **Agentes = papéis no código**, não serviços. IA só em: refinamento do roteiro (planner) e revisão visual (reviewer). Preparação da ficha, prompts-base, estados, custos, cortes e montagem são determinísticos.
4. **Gemini API como provedor único inicial** (imagem, vídeo, texto) — uma chave, uma fatura. Interfaces permitem trocar por Veo na Agent Platform ou outro provedor.
5. **Vídeo: Gemini Omni Flash**, porque o Veo 3.1 Preview foi desligado na Gemini API em 22/10/2026.
6. **Prompts de geração em inglês** (suporte completo do Omni só em inglês); roteiro/relatórios em português.
7. **Áudio**: takes podem vir com áudio; a montagem descarta e insere trilha silenciosa AAC (compatibilidade). A revisão sinaliza áudio audível.
8. **Aprovação humana obrigatória** em imagem e vídeo de cada cena e na revisão final. A revisão automática só reprova (gerando correção limitada) ou encaminha.
9. **Orçamento no modo simulado** é consumido pelo custo equivalente estimado, para que o controle seja testável sem gastar.
10. Perfis versionados (`profiles/<tipo>/<id>/vN.json`) são congelados no banco na criação da produção.
11. Gravação de tela só como `context`: nunca enviada ao gerador.

## Decisões que dependem de você

1. **Orçamento**: teto por produção para o primeiro teste real (sugestão: US$5, cobre ~1 produção com 1–2 refações) e teto mensal.
2. **Credencial**: criar chave da Gemini API com faturamento ativo (AI Studio). A assinatura do Gemini/Flow não cobre a API.
3. **Provedor de vídeo**: aceitar Omni Flash pela Gemini API (padrão) ou preferir Veo 3.1 GA pela Agent Platform (projeto Google Cloud). Recomendo começar pelo Omni e comparar com um take feito por você no Flow.
4. **Fotos oficiais do copo** (frente, lateral, tampa; interior opcional) e confirmação de que o link é dessa variante.
5. **Texto de identificação** (publicidade/IA): validar a redação conforme regras vigentes antes da primeira publicação.

## Pendências técnicas

- Marco 2: executar adaptadores reais (1 imagem com referências, 1 animação), ajustar formato exato de `response_format`/saída se divergir da doc, medir duração real dos takes, comparar qualidade com o Flow.
- Confirmar limites de referências por modelo e se a foto da Bia (rosto realista) é aceita como referência de tom de pele; alternativa: recorte só da mão/pele.
- Preço oficial do Omni Flash em 1080p.
- Cancelamento remoto (`interactions.cancel`) ao cancelar produção: ainda não chamado.
- Janela de risco: se o processo cair entre o envio e o registro do id remoto, a tentativa é reenviada (pode gerar 1 cobrança duplicada). Mitigação: `background=True` retorna rápido.
- Marco 5: interface web simples (depois de validar 1 produto real ponta a ponta).
