# Stripe — configuração e roteiro de teste (Fase 6)

Planos mensais (Básico, Pro, Estúdio) e créditos avulsos pela Stripe. Código: `src/studio/stripe_client.py` (cliente
REST, assinatura do webhook), `src/studio/payments_stripe.py` (checkout, portal, webhook), `src/studio/credits.py`
(livro por origem). Variáveis: [ENVS.md](ENVS.md), seção "Planos e créditos (Stripe)". **Só chaves de teste no staging.**

## 1. O que configurar no painel da Stripe (sandbox)

1. **Produtos e preços** (já existem): Básico/Pro/Estúdio mensais em BRL com metadados `credits` (120/320/800) e
   `plan`; avulso em BRL por unidade com `plan=avulso`, `credits_per_unit=1`. Os ids `price_...` vão nas variáveis.
2. **Formas de pagamento** (Settings → Payment methods): ligar **Cartão** e **Pix**. O Checkout usa as formas ligadas
   na conta (não fixamos a lista no código). Pix em assinatura (Pix Automático) aparece só se a conta tiver o recurso.
3. **Webhook** (Developers → Webhooks / Event destinations → Add endpoint):
   - URL: `https://<host do staging>/api/payments/stripe/webhook`
   - Eventos: `checkout.session.completed`, `checkout.session.async_payment_succeeded`,
     `checkout.session.async_payment_failed`, `checkout.session.expired`, `invoice.paid`, `invoice.payment_failed`,
     `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`,
     `charge.refunded`, `charge.dispute.created`.
   - Copie o **Signing secret** (`whsec_...`) para `STRIPE_WEBHOOK_SECRET`.
4. **Portal do cliente** (Settings → Billing → Customer portal):
   - Ligar: atualizar forma de pagamento, ver histórico de faturas, cancelar assinatura (no fim do período).
   - **Trocar de plano**: ligar e adicionar os 3 preços mensais (Básico, Pro, Estúdio) como produtos permitidos.
   - Proração: "Prorate and invoice immediately" para upgrades (o Kiroo concede a diferença de créditos na hora).
   - Downgrade: de preferência "agendar para o fim do período" (o Kiroo já trata o downgrade como próximo ciclo).
   - Link de retorno padrão: `https://<host do staging>/pricing`.

## 2. Variáveis no Railway (staging)

```
PAYMENTS_ENABLED=true
STRIPE_SECRET_KEY=sk_test_...            # selada
STRIPE_WEBHOOK_SECRET=whsec_...          # selada (do endpoint do staging)
STRIPE_PUBLISHABLE_KEY=pk_test_...       # opcional
STRIPE_PRICE_BASICO_M=price_...
STRIPE_PRICE_PRO_M=price_...
STRIPE_PRICE_ESTUDIO_M=price_...
STRIPE_PRICE_AVULSO=price_...
TOPUP_MIN_CREDITS=50
TOPUP_MAX_CREDITS=1000
```
`STUDIO_ENV` do staging **não** pode ser `production` (chave de teste em produção é recusada na subida).

## 3. Antes do deploy: backup e migração 16

A migração 16 roda sozinha na subida: cria os lotes e converte o saldo atual de cada conta em um lote **avulso sem
validade**. Faça o backup antes (procedimento em [BACKUP.md](BACKUP.md)) e rode primeiro no staging. Conferência depois:
`python -m studio admin credits --email <conta>` deve mostrar o mesmo saldo de antes.

## 4. Roteiro local com a Stripe CLI

```bash
stripe login
stripe listen --forward-to http://127.0.0.1:8765/api/payments/stripe/webhook
```
O `listen` mostra um `whsec_...` próprio: use-o em `STRIPE_WEBHOOK_SECRET` só na máquina local e suba o servidor
(`studio ui`) com as variáveis de teste.

1. **Avulso:** em `/pricing`, escolha 100 créditos e pague com o cartão `4242 4242 4242 4242`. Esperado: volta para
   `/pricing?compra=...`, "Pagamento confirmado: 100 créditos adicionados" e um lote avulso de 100.
2. **Quantidade inválida:** digite 49 ou 1001 → botão desligado; via API (`kind=topup`, `credits=49`) → 400.
3. **Plano:** "Assinar Pro" com `4242...`. Esperado: `invoice.paid` concede 320 créditos do plano (vencem no fim do ciclo).
4. **Upgrade:** "Mudar para Estúdio" (abre o Portal) → +480 créditos na hora. **Downgrade** para Básico → nada agora.
5. **Falha de cobrança:** `stripe trigger invoice.payment_failed` (ou cartão `4000 0000 0000 0341` no Portal) →
   assinatura `past_due`.
6. **Reembolso:** no painel, reembolse o avulso → só os créditos não usados saem; conta com `billing_flag=refund`.
7. **Contestação:** pague um avulso com `4000 0000 0000 0259` → `charge.dispute.created` tira o que não foi usado.
8. **Evento repetido:** no painel do webhook, "Resend" de um `invoice.paid` → resposta `duplicate`, saldo igual.
9. **Assinatura inválida:** `curl -X POST .../api/payments/stripe/webhook -d '{}'` → 400.

## 5. Renovação de ciclo com test clock

1. Developers → **Test clocks** → criar um relógio (ex.: hoje).
2. Criar um cliente **dentro do test clock** e ligar ao workspace de teste: no banco local,
   `UPDATE workspaces SET stripe_customer_id='cus_...' WHERE id='ws_...';` (ou assine pelo app com uma conta nova e
   use o cliente que o app criou, se ele estiver no relógio).
3. Criar a assinatura Pro para esse cliente (painel ou Checkout). Conferir 320 créditos do plano.
4. Gastar alguns créditos (um vídeo de 20).
5. **Avançar o relógio** 1 mês + 1 dia. A Stripe gera `invoice.paid` (`subscription_cycle`). Esperado: o que sobrou do
   ciclo anterior vence (lançamento "Créditos do plano expirados" no extrato) e entram 320 novos, com validade no fim do
   novo ciclo. Avulsos continuam intactos.
6. Avançar mais um mês com o cartão `4000 0000 0000 0341` → `invoice.payment_failed` e `past_due`.

## 6. Webhook perdido

`python -m studio payments reconcile` reprocessa eventos que ficaram sem `processed_at` (relendo na API) e confere os
checkouts ainda abertos. A tela também confere a sessão na volta do checkout (a cada 10 s) se o webhook atrasar.
