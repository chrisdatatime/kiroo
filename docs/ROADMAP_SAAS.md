# Roteiro: Pivoo como jogo + SaaS pago

Decisões do Chris (27/10/2026):

| Tema | Decisão |
|---|---|
| Interface | O escritório-jogo (protótipo React) vira a interface principal, **com atalhos diretos**: toda ação importante fica a 1 clique pelo HUD; andar e conversar com os agentes é opcional. |
| Escopo comercial | **Venda completa**: contas, planos, créditos, cobrança integrada e hospedagem. |
| Unidade de cobrança | **Créditos do estúdio** (internamente o custo continua em US$). |
| Gateway | **Mercado Pago** (Pix e cartão). |
| Empresa | **Ainda sem CNPJ**: tudo roda em **modo de teste** do Mercado Pago até haver CNPJ e conta verificada. Nenhuma cobrança real antes disso. |
| Modelo | **Assinatura mensal com créditos inclusos + pacotes avulsos**. |
| Preço | Crédito = custo do Google × **3** (margem provisória, configurável). |

## Fases

### A — Jogo sobre o motor real *(entregue em 27/10/2026, testado em modo DEMO)*
- Protótipo em `frontend/` (React + Vite), servido pelo servidor Python; o painel anterior fica em `/painel` para administração.
- Timers `SIMULADO` substituídos por chamadas à API e polling dos estados reais.
- Etapas pagas exigem **liberação explícita** depois de mostrar a estimativa (imagens, vídeos, refações).
- Custos mostrados em créditos (conversão provisória: US$ → R$ pelo câmbio configurado × margem ÷ preço do crédito).

### B — Contas e espaços de trabalho *(núcleo entregue em 28/10/2026, testado localmente)*
- **Feito:** cadastro/login no jogo (senha com scrypt; sessão em cookie HttpOnly SameSite=Lax, só o hash do token no banco;
  token CSRF por sessão em todo POST; limite de 8 tentativas erradas em 15 min), sair, recuperação de senha por link de uso único.
- **Feito:** cada conta tem um **workspace** com produções, fotos e gastos isolados (ação ou mídia de outro workspace → 404);
  teto mensal por workspace. A primeira conta vira administradora, herda as produções existentes e o modo real; as demais
  começam em DEMO e só geram de verdade se o admin liberar (`studio admin allow-real --email ...`). `/painel` e
  `/api/config` são só do admin.
- **Falta:** envio de e-mail (hoje o link de nova senha vai para o log do servidor ou sai em `studio admin reset-link`);
  convidar membros e trocar de workspace pela interface; Termos de uso e política de privacidade (LGPD, depende de revisão
  jurídica); perfis (ex.: Bia) ainda são globais.
- Troca do servidor stdlib por um framework (FastAPI/ASGI) ficou para a fase E, junto da hospedagem.

### C — Créditos (livro-razão) *(entregue em 28/10/2026, testado localmente)*
- **Feito:** `src/studio/credits.py`, saldo por workspace em centésimos de crédito (inteiros). Antes de cada chamada paga o
  estúdio **reserva** a estimativa. Ao terminar, **devolve a reserva e debita** o custo (o confirmado, se houver; senão o estimado).
  Recusa sem custo vira **estorno**, e reserva órfã é devolvida em 15 min. Lançamentos nunca são apagados.
  `ext_ref` único deixa cada entrada idempotente, que é a base dos webhooks da fase D.
- **Feito:** sem saldo, a produção pausa antes de gastar e preserva tudo. Limite por produção e teto do mês continuam
  valendo. A conta do dono é **isenta**: tudo fica registrado, mas o saldo não é exigido. DEMO não usa créditos.
- **Feito:** janela "Créditos do estúdio" no jogo, com saldo, consumo por produção e etapa e extrato
  (`GET /api/credits`). O saldo também aparece em `/api/state` e `/api/me`.
- **Feito:** administração com `studio admin grant-credits | adjust-credits | credits --email ... [--credits N --note ...]`.
- **Falta:** a compra pelo cliente (fase D). Por enquanto quem libera créditos é o administrador.

### D — Planos e Mercado Pago
- Assinaturas (pré-aprovação recorrente) com créditos mensais e compra de pacotes avulsos (Pix/cartão).
- Webhooks assinados → créditos no livro-razão (idempotente); conciliação.
- Tudo em **sandbox** até o CNPJ. Nota fiscal de serviço: depende do CNPJ e de um emissor (definir depois).

### E — Hospedagem
- Imagem Docker (Python + FFmpeg + frontend), banco gerenciado (migrar SQLite → Postgres), armazenamento de mídia em objeto (S3/R2), HTTPS, backups, processo de trabalho separado do web, monitoramento e limites contra abuso.

## Riscos a tratar
- **Toda geração é paga na conta Google do Chris**: créditos precisam ser debitados antes da chamada; limites por conta contra abuso.
- Uploads de clientes (pessoas, marcas de terceiros): termos de uso e moderação mínima.
- Preço e câmbio provisórios: revisar com custos reais medidos (ex.: produção real de 27/10: ~US$ 7,24 com refações; takes de 10 s usados pela metade).
