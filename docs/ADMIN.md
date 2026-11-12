# Operação: comandos `studio admin`

Comandos para operar o Kiroo em staging/produção **dentro do contêiner**. Todos usam o mesmo banco do servidor
(`/data/studio.sqlite3`) e podem rodar com o servidor no ar (SQLite em WAL; cada comando é uma transação curta).

```bash
docker compose exec kiroo python -m studio admin <ação> [opções]
```

Use `-it` quando o comando pedir senha (`create-user`): `docker compose exec -it kiroo python -m studio admin create-user ...`.
Em outra plataforma (Fly, Railway, Render), troque o prefixo pelo console/SSH do serviço: o comando é o mesmo,
`python -m studio admin ...` (ou só `studio admin ...`).

Regras:

- Nenhum comando imprime segredo do ambiente. Os únicos valores sensíveis que aparecem são os que você pediu para
  gerar (código de convite, link de senha), e só uma vez. Não cole esses valores em ticket ou chat público.
- O log do contêiner não recebe código de convite, código de confirmação nem link de senha.
- Tudo abaixo vale para o banco do ambiente onde o comando roda. Confira o ambiente antes: `python -m studio doctor`.

## Primeiro acesso (administrador)

| O que | Comando |
|---|---|
| Criar o administrador (pede a senha no terminal) | `studio admin create-user --email voce@kiroo.app --name "Seu Nome" --admin` |
| Alternativa sem senha no terminal | defina `STUDIO_BOOTSTRAP_ADMIN_EMAIL` e suba; o link de definir senha vai por e-mail (com SMTP) ou gere com `reset-link` |
| Listar contas, modo e teto de cada estúdio | `studio admin list` |

O administrador já nasce com o estúdio liberado para o modo real e isento de créditos. Ele **não** pode ser apagado pela
interface; só por `delete-user --yes`.

## Convites (cadastro com `STUDIO_SIGNUP=invite`)

| O que | Comando |
|---|---|
| Criar convite de uso único (padrão 7 dias) | `studio admin create-invite` |
| Com validade e nota | `studio admin create-invite --days 3 --note "beta: loja da Ana"` |
| Preso a um e-mail (só ele consegue usar) | `studio admin create-invite --email ana@exemplo.com` |
| Ver convites (válido, usado, expirado) | `studio admin list-invites` |
| Revogar um convite ainda não usado | `studio admin revoke-invite --id inv_xxxxxxxxxx` |

- O código (`KIROO-XXXX-XXXX-XXXX`) aparece **uma vez**, na saída do comando. No banco fica só o hash.
- Validade de 1 a 30 dias. Usado uma vez, não serve mais. Se o cadastro falhar (senha curta, e-mail repetido), o
  convite volta a valer.
- Na tela de cadastro a pessoa digita o código, aceita os Termos e a Política de Privacidade e recebe o código de
  confirmação por e-mail.
- `STUDIO_INVITE_CODES` (códigos fixos e reutilizáveis) foi aposentado: o servidor ignora e avisa no boot.

## Criar conta sem convite

```bash
studio admin create-user --email ana@exemplo.com --name "Ana"      # pede a senha; conta em DEMO
```

Para a pessoa escolher a própria senha, crie a conta e mande um link: `studio admin reset-link --email ana@exemplo.com`.

## Liberar o modo real (custos reais)

| O que | Comando |
|---|---|
| Liberar o estúdio para produções reais | `studio admin allow-real --email ana@exemplo.com` |
| Voltar para DEMO (e bloquear o real) | `studio admin deny-real --email ana@exemplo.com` |
| Ver modo, teto da conta e teto efetivo de cada estúdio | `studio admin list` |
| Trocar o modo do estúdio (`real` só se estiver liberado) | `studio admin set-mode --email ana@exemplo.com --mode real` (ou `simulated`) |
| Definir o teto mensal do estúdio em US$ | `studio admin set-cap --email ana@exemplo.com --usd 3` |

- **Modo** (`simulated` = DEMO, `real`) e **teto** (`monthly_cap_usd`) são por estúdio. Conta nova nasce em `simulated` com
  teto US$ 0. `allow-real` só *libera*; quem liga é `set-mode real` (ou a própria pessoa em Minha conta).
- `set-mode real` recusa estúdio sem `allow-real`. `deny-real` volta o estúdio para `simulated`.
- `set-cap --usd N` aceita N de 0 até `STUDIO_MONTHLY_CAP_USD` (teto da plataforma); acima disso, valor negativo, `nan`
  ou `inf` são recusados e nada muda. Com a plataforma em 0, só o 0 passa.
- **Teto efetivo = o menor entre o da conta e o da plataforma.** É o que o gasto realmente respeita (produções,
  testes de treinamento e chat com IA). Teto efetivo 0 = nenhuma chamada paga: o estúdio opera como DEMO.
  A tela de Minha conta também recusa teto de conta acima do da plataforma.
- Cada `set-mode`/`set-cap` entra no extrato do estúdio como "Ajuste" de 0 crédito com a nota
  (`admin set-mode: simulated -> real`, `admin set-cap: US$0.00 -> US$3.00 (plataforma US$5.00)`), com autor `cli`.
  Nenhum valor de segredo é impresso.

Roteiro para ligar o real na conta de teste do staging (plataforma com `STUDIO_MONTHLY_CAP_USD=5`):

```bash
studio admin allow-real --email voce@kiroo.app
studio admin set-cap    --email voce@kiroo.app --usd 5
studio admin set-mode   --email voce@kiroo.app --mode real
studio admin list
```

Liberar o estúdio não basta para gastar. A chamada paga só sai quando **todos** valem:

1. `STUDIO_KILL_SWITCH` diferente de `1` (o kill switch bloqueia Gemini e Anthropic em qualquer ambiente).
2. `STUDIO_ALLOW_PAID_CALLS=1` (padrão 0 em staging/produção).
3. `STUDIO_MONTHLY_CAP_USD` > 0 (teto do mês da plataforma inteira; obrigatório em staging/produção) e ainda com folga.
4. Teto diário do agente (`STUDIO_AGENT_DAILY_CAP_USD`, se definido), teto mensal efetivo do estúdio (> 0; veja
   `set-cap`), orçamento operacional da produção e saldo de créditos (estúdios não isentos; com pré-orçamento, o saldo
   é reservado na criação).

### Saldo do cliente × orçamento operacional (dois freios diferentes)

- **Saldo do cliente** (créditos concedidos/comprados). Ao criar uma produção em modo real, o servidor calcula o
  **pré-orçamento** do vídeo completo (roteiro + imagens e takes previstos por cena, cada um com conferência, + os
  ajustes incluídos) pela tabela `profiles/billing/operation_costs.json` e **reserva** esse valor do saldo. Saldo menor
  que a estimativa → a produção não começa (`402`, "Nada foi cobrado"). Durante a produção, cada tentativa concluída
  sai dessa reserva; o cliente nunca paga mais que o pré-orçamento + os ajustes extras que ele autorizou. Ao concluir
  ou cancelar, o que sobrou volta ao saldo.
- **"Seu próximo vídeo"** (confirmação): antes de qualquer gasto o cliente vê produto, formato (9:16), nº de cenas, ajustes
  incluídos por cena, custo total em créditos (e R$ só com `STUDIO_CREDIT_PRICE_BRL`), saldo e "Nenhum custo adicional
  será aplicado sem sua autorização", e confirma em **Confirmar e criar vídeo** (`POST /api/productions/{id}/confirm`,
  com o `total_cc` visto; valor diferente é recusado). Sem confirmação a produção real espera em *validada* e não gasta
  (nem roteiro por IA); cancelar antes devolve a reserva. DEMO e produções antigas não têm essa etapa.
- **Falha técnica** (erro do provedor, tempo esgotado): não sai nada do cliente (no regime antigo, a reserva é estornada).
- **Ajustes pedidos pelo cliente**: `STUDIO_INCLUDED_ADJUSTMENTS_PER_SCENE` por cena (padrão 1) já estão no pré-orçamento.
  Além disso, a tela mostra o custo do ajuste extra e só segue com autorização explícita (`authorize_extra`), que
  reserva esse custo do saldo antes de refazer.
- **Orçamento operacional da produção** (`productions.budget_usd`): freio **interno** contra laço ou estimativa ruim
  (padrão: o maior entre `STUDIO_DEFAULT_PRODUCTION_CAP_CREDITS` e pré-orçamento × `STUDIO_OPS_BUDGET_FACTOR`, nunca
  acima do teto efetivo). Ao atingi-lo, a produção pausa as chamadas externas com o código estável
  `ops_budget_reached`, registra o evento `ops_alert` e manda e-mail aos administradores (se o envio estiver
  configurado). O cliente vê só "Estamos finalizando seu vídeo… avisaremos" — **nunca** cobrança automática nem botão
  de subir limite (a rota `/budget` responde `403` para quem não é administrador).
- O teto mensal (plataforma/conta, `set-cap`) continua independente: vale o freio que bloquear primeiro, e teto 0 não
  gasta em nenhum caminho.

| O que | Comando |
|---|---|
| Ver produções pausadas por freio interno | `studio admin ops-alerts` |
| Ajustar o orçamento operacional e retomar | `studio budget <pid> --set <US$>` e `studio resume <pid>` |

Cada acerto com o cliente fica em `production_charges` (uma linha por tentativa: produção, cena, operação, provedor,
modelo, custo interno, créditos cobrados e decisão `charged` | `technical_failure` | `absorbed`); repetir o acerto não
cobra de novo. Produções criadas antes desta versão (sem pré-orçamento) abrem e seguem o regime antigo de reserva e
débito por chamada.

Para cortar todo gasto na hora: `STUDIO_KILL_SWITCH=1` e reinicie o serviço. As produções em andamento pausam com aviso
amigável e retomam quando o kill switch sair. Confira com `python -m studio doctor` (linha "portão de chamadas pagas").

## Créditos

A tela **Créditos e extrato** do cliente mostra saldo, reservado, consumo por vídeo → cena → operação e o extrato.
Quando falta saldo para um **ajuste extra**, o cliente vê "Saldo insuficiente para um novo ajuste" com saldo, custo e o
que falta, e escolhe **Manter meu vídeo como está** (nada muda, nada é cobrado) ou **Adicionar créditos**. Como ainda não há
pagamento, "Adicionar créditos" mostra o contato de `STUDIO_SUPPORT_CONTACT` e o passo a passo; você libera com o comando
abaixo. Um vídeo já pago (pré-orçamento reservado) é entregue mesmo com o saldo livre zerado.

**Mercado Pago (depois):** o ponto de integração é `src/studio/payments.py` — implementar
`MercadoPagoProvider.start_checkout` e, no webhook, creditar com `Ledger.add(wid, cc, kind="purchase",
ext_ref="mp:<payment_id>")` (o `ext_ref` já torna o crédito idempotente). `GET /api/credits/topup` é o que a tela lê.


| O que | Comando |
|---|---|
| Conceder créditos | `studio admin grant-credits --email ana@exemplo.com --credits 100 --note "beta"` |
| Ajustar (aceita negativo) | `studio admin adjust-credits --email ana@exemplo.com --credits -20 --note "estorno"` |
| Ver saldo | `studio admin credits --email ana@exemplo.com` |

## Senha e e-mail

| O que | Comando |
|---|---|
| Gerar link de nova senha (vale 30 min, uso único) | `studio admin reset-link --email ana@exemplo.com` |
| Confirmar o e-mail à mão (sem SMTP, depois de conferir com a pessoa) | `studio admin verify-email --email ana@exemplo.com` |

`reset-link` usa `STUDIO_PUBLIC_HOST` (https) quando definido. Gerar um link novo invalida o anterior; usar o link
encerra todas as sessões da conta. Entregue o link por um canal privado.

## Dados da pessoa (LGPD)

A própria pessoa exporta (`GET /api/account/export`) e apaga a conta (`POST /api/account/delete`, com a senha e a
palavra `APAGAR`). Pelo operador:

| O que | Comando |
|---|---|
| Exportar os dados de uma conta (JSON na saída) | `studio admin export-user --email ana@exemplo.com > ana.json` |
| Apagar conta, estúdio, produções e arquivos | `studio admin delete-user --email ana@exemplo.com --yes` |

O arquivo exportado contém dados pessoais: guarde e entregue com cuidado e apague depois. Apagar é definitivo no
banco e no disco; o livro de créditos fica sem vínculo com a pessoa e as cópias de backup expiram pela retenção do
Litestream/R2 (ver docs/SECURITY.md).

## Diagnóstico

```bash
docker compose exec kiroo python -m studio doctor     # modo, portão de gasto, ffmpeg, pastas (sem valores de segredo)
curl -fsS https://SEU-HOST/readyz                      # banco e pasta de dados (sem segredo, sem detalhe de erro)
```
