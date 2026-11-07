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

Liberar o estúdio não basta para gastar. A chamada paga só sai quando **todos** valem:

1. `STUDIO_KILL_SWITCH` diferente de `1` (o kill switch bloqueia Gemini e Anthropic em qualquer ambiente).
2. `STUDIO_ALLOW_PAID_CALLS=1` (padrão 0 em staging/produção).
3. `STUDIO_MONTHLY_CAP_USD` > 0 (teto do mês da plataforma inteira; obrigatório em staging/produção) e ainda com folga.
4. Teto diário do agente (`STUDIO_AGENT_DAILY_CAP_USD`, se definido), teto mensal do estúdio (a pessoa define ao
   desligar o DEMO), orçamento da produção e saldo de créditos (estúdios não isentos).

Para cortar todo gasto na hora: `STUDIO_KILL_SWITCH=1` e reinicie o serviço. As produções em andamento pausam com aviso
amigável e retomam quando o kill switch sair. Confira com `python -m studio doctor` (linha "portão de chamadas pagas").

## Créditos

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
