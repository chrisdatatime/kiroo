# Variáveis do staging

Tabela completa do que o serviço de staging precisa. É a referência para preencher o painel do Railway
(passo a passo em [docs/RAILWAY.md](RAILWAY.md)); a lista geral de todas as variáveis do projeto, com os
padrões do código, continua em [`.env.example`](../.env.example).

Como ler as colunas:

- **Obrig.** — `sim` = sem ela o staging não funciona como queremos; `não` = tem padrão aceitável.
- **Segredo** — `sim` = vai **selada** (*sealed*) no Railway. Variável selada não aparece no painel nem na
  API depois de salva, e **não dá para desselar**: guarde o valor no seu gerenciador de senhas antes de
  colar. Variável não secreta fica visível, o que é bom para conferir configuração.
- **Quando** — `execução` entra no serviço; `build` só existe durante a construção da imagem.
- Os valores de exemplo são **fictícios**. Nunca escreva valor real de segredo em arquivo versionado,
  em issue ou no chat.

---

## 1. Identidade do ambiente e portão de gastos

| Variável | Obrig. | Segredo | Quando | Valor no staging | Para que serve |
|---|---|---|---|---|---|
| `STUDIO_ENV` | **sim** | não | execução | `staging` | Define o prefixo no bucket de backup (`staging/`) e liga os avisos de ambiente. Só aceita `dev`, `staging` ou `production`; qualquer outra coisa impede a subida. |
| `STUDIO_MODE` | **sim** | não | execução | `simulated` | Esteira inteira simulada: nenhum provedor pago é chamado. |
| `STUDIO_ALLOW_PAID_CALLS` | **sim** | não | execução | `0` | Portão único de chamadas pagas (Gemini e Anthropic). Com `0` nada pago roda, mesmo se houver chave. |
| `STUDIO_MONTHLY_CAP_USD` | não | não | execução | `0` | Teto mensal da plataforma e **limite máximo** do teto de qualquer conta (`studio admin set-cap --usd N` recusa N acima dele; o gasto vale o menor dos dois). Com `STUDIO_ALLOW_PAID_CALLS=0` não tem efeito; deixe `0` para não haver teto a liberar por engano. |
| `STUDIO_DEFAULT_PRODUCTION_CAP_CREDITS` | não | não | execução | *(não definir; padrão `80`)* | Piso, em créditos, do **orçamento operacional** (freio interno) de uma produção nova; limitado pelo teto efetivo do estúdio (menor entre o da conta e `STUDIO_MONTHLY_CAP_USD`). Valor ausente, inválido ou ≤ 0 volta a 80. Atingir o orçamento operacional pausa com `ops_budget_reached` e avisa o administrador; nunca cobra nem pede upgrade ao cliente. |
| `STUDIO_OPS_BUDGET_FACTOR` | não | não | execução | *(não definir; padrão `1.5`)* | Orçamento operacional = maior entre o piso acima e pré-orçamento × fator (mínimo 1). |
| `STUDIO_ESTIMATE_IMAGE_TRIES_PER_SCENE` | não | não | execução | *(não definir; padrão `2`)* | Imagens previstas por cena no **pré-orçamento** (valor reservado do saldo do cliente antes de começar). Mínimo 1; inválido volta ao padrão. |
| `STUDIO_ESTIMATE_VIDEO_TRIES_PER_SCENE` | não | não | execução | *(não definir; padrão `2`)* | Takes previstos por cena no pré-orçamento. Mínimo 1. |
| `STUDIO_INCLUDED_ADJUSTMENTS_PER_SCENE` | não | não | execução | *(não definir; padrão `1`)* | Ajustes pedidos pelo cliente por cena já incluídos no pré-orçamento (sem cobrança extra). Além deles, o ajuste exige autorização explícita do cliente com o custo em créditos à vista. `0` = todo ajuste pede autorização. |
| `STUDIO_OPERATION_COSTS_FILE` | não | não | execução | *(não definir)* | Caminho de uma tabela de custos por operação (formato de `profiles/billing/operation_costs.json`: roteiro, imagem, conferências, vídeo; `usd: null` = tabela de preços do modelo). Base do pré-orçamento e das reservas de conferência/roteiro. |
| `STUDIO_CREDIT_PRICE_BRL` | não | não | execução | *(não definir)* | Preço de 1 crédito em R$. **Só com ele definido (> 0) o resumo "Seu próximo vídeo" mostra o valor em R$**; sem ele a interface mostra apenas créditos (o padrão interno 1,00 serve só à conversão de custo). |
| `STUDIO_SUPPORT_CONTACT` | não | não | execução | `ajuda@exemplo.com` | Contato mostrado em "Adicionar créditos" (enquanto não há pagamento pelo site): e-mail (vira `mailto:`), endereço `https://` (formulário, WhatsApp) ou texto livre. Qualquer outro esquema (`javascript:`) aparece só como texto. Vazio: a tela mostra só a instrução. |
| `STUDIO_PAYMENTS_PROVIDER` | não | não | execução | *(não definir; padrão `manual`)* | `manual` (padrão) ou `mercadopago`. O Mercado Pago é só o ponto de integração (`src/studio/payments.py`): ainda não cobra; com `mercadopago` a tela continua no modo manual até o checkout ser implementado. |
| `STUDIO_KILL_SWITCH` | não | não | execução | *(não definir)* | `1` bloqueia qualquer chamada paga em qualquer ambiente. Trava de emergência; com `ALLOW_PAID_CALLS=0` já é redundante. |

> Em staging nunca coloque `GEMINI_API_KEY` nem `ANTHROPIC_API_KEY`. Sem chave o modo simulado funciona
> normalmente e o chat cai no modo "sem IA". Chave que não existe é chave que não vaza.

## 2. Rede, host e cookie

| Variável | Obrig. | Segredo | Quando | Valor no staging | Para que serve |
|---|---|---|---|---|---|
| `STUDIO_HOST` | não | não | execução | `0.0.0.0` | A imagem já define isto. Em contêiner precisa escutar em todas as interfaces, senão o roteador do Railway não alcança. |
| `PORT` | não | não | execução | *(a plataforma injeta)* | O Railway injeta `PORT`; o código a lê. **Não defina `STUDIO_PORT`**, que venceria a da plataforma. |
| `STUDIO_PUBLIC_HOST` | **sim** | não | execução | `staging.kiroo.app` | Host público canônico: usado em links absolutos (e-mail) e no reconhecimento de que o site está na internet. |
| `STUDIO_ALLOWED_HOSTS` | **sim** | não | execução | `staging.kiroo.app` | Lista separada por vírgula dos `Host:` aceitos. Barra acesso pelo domínio cru da plataforma e por host forjado. Se mantiver o domínio `*.up.railway.app`, inclua-o aqui também. |
| `STUDIO_SECURE_COOKIE` | **sim** | não | execução | `1` | Cookie de sessão com `Secure` e resposta com HSTS. Só ligue com HTTPS de verdade na frente (é o caso: Cloudflare + Railway). |
| `STUDIO_TRUST_PROXY` | **sim** | não | execução | `cloudflare` | De quem aceitar o IP real do visitante: lê `CF-Connecting-IP`. Sem isto todo mundo viraria o mesmo IP e o limite por IP puniria todos juntos. |

> `STUDIO_TRUST_PROXY=cloudflare` só é seguro porque **todo** o tráfego entra pela Cloudflare. Se um dia
> o domínio `*.up.railway.app` ficar aberto em paralelo, alguém pode mandar `CF-Connecting-IP` à mão e
> forjar o IP de origem. É um dos motivos para não gerar aquele domínio.

## 3. Cadastro e conta

| Variável | Obrig. | Segredo | Quando | Valor no staging | Para que serve |
|---|---|---|---|---|---|
| `STUDIO_SIGNUP` | **sim** | não | execução | `invite` | Cadastro só com código de uso único, gerado por `studio admin create-invite`. Sem código o cadastro responde `403`. |
| `STUDIO_BOOTSTRAP_ADMIN_EMAIL` | não | não | execução | `voce@exemplo.com` | Cria o administrador no primeiro boot e manda o link para definir a senha. Depois de usar, pode remover. Exige e-mail configurado (seção 5). |
| `STUDIO_INVITE_CODES` | — | — | — | *(não usar)* | Aposentado. Se existir, é ignorado com aviso no log. |

### Verificação anti-robô (Cloudflare Turnstile)

| Variável | Obrig. | Segredo | Quando | Valor no staging | Para que serve |
|---|---|---|---|---|---|
| `STUDIO_TURNSTILE_SITE_KEY` | recomendada | não (pública) | execução | *(chave do widget, `0x4...`)* | Chave pública: o servidor a entrega em `GET /api/config` e o navegador carrega o widget. Passo a passo em `docs/TURNSTILE.md`. |
| `STUDIO_TURNSTILE_SECRET_KEY` | recomendada | **sim** | execução | *(segredo do widget)* | Segredo usado só no servidor para validar o token em `siteverify`. Mascarado em logs e erros. |

As duas andam juntas. Sem nenhuma, o recurso fica desligado (aviso no log em staging/produção). **Só uma delas em staging/produção
falha fechada**: cadastro, login, esqueci a senha e reenvio de código recusam tudo (`503 captcha_indisponivel`) e a subida registra um
aviso crítico. Em `dev`, só uma delas apenas desliga o recurso e avisa.

## 4. Desligamento (precisa casar com o Railway)

| Variável | Obrig. | Segredo | Quando | Valor no staging | Para que serve |
|---|---|---|---|---|---|
| `STUDIO_SHUTDOWN_GRACE_S` | não | não | execução | `25` (padrão) | Tempo drenando requisições em curso depois do `SIGTERM`. |
| `STUDIO_SHUTDOWN_SETTLE_S` | não | não | execução | `3` (padrão) | Espera depois da drenagem para o Litestream sincronizar o último trecho do WAL. `0` desliga. |
| `STUDIO_STOP_GRACE_S` | **sim** | não | execução | `40` | Quanto a plataforma promete dar entre `SIGTERM` e `SIGKILL`. O servidor **recusa subir** se o orçamento não couber. |
| `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` | **sim** | não | execução | `40` | O prazo de verdade, do lado do Railway. **O padrão dele é `0`**, ou seja `SIGKILL` imediato: sem esta variável o banco pode parar no meio de uma escrita. |

A conta do orçamento é `grace + 2 (fechamento HTTP) + settle + 5 (margem do Litestream)`, isto é
`25 + 2 + 3 + 5 = 35 s` no mínimo. Por isso `40`: 5 s de folga. As duas variáveis precisam ter o **mesmo**
valor e `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` nunca pode ser menor que `STUDIO_STOP_GRACE_S`, senão a
plataforma mata antes do que o servidor foi autorizado a usar. O log de subida imprime a conta:

```
desligamento: grace 25s + settle 3s; a plataforma precisa dar pelo menos 35s (STUDIO_STOP_GRACE_S=40)
```

| Variável | Obrig. | Segredo | Quando | Valor no staging | Para que serve |
|---|---|---|---|---|---|
| `RAILWAY_DEPLOYMENT_OVERLAP_SECONDS` | não | não | execução | *(não definir)* | Sobreposição entre o deploy novo e o antigo. **Não use com volume**: o Railway impede dois deploys montados no mesmo volume, então isto não evitaria a parada curta e só confundiria o diagnóstico. |

## 5. E-mail (Resend)

| Variável | Obrig. | Segredo | Quando | Valor no staging | Para que serve |
|---|---|---|---|---|---|
| `STUDIO_MAIL_FROM` | **sim** | não | execução | `Kiroo <nao-responda@kiroo.app>` | Remetente. O domínio precisa estar verificado no Resend (SPF e DKIM), senão a mensagem não sai ou cai em spam. |
| `STUDIO_MAIL_TRANSPORT` | não | não | execução | `resend_api` | `smtp` (padrão) ou `resend_api`. **No Railway use `resend_api`**: a plataforma bloqueia a saída SMTP (465/587 dão `TimeoutError`). `resend_api` envia por HTTPS (`POST https://api.resend.com/emails`, `Authorization: Bearer <chave>`, timeout de 10 s) e **não usa** `STUDIO_SMTP_HOST`, `_PORT`, `_USER` nem `_SECURITY`. Valor desconhecido = envio desligado (falha fechada). |
| `STUDIO_SMTP_HOST` | **sim** (só `smtp`) | não | execução | `smtp.resend.com` | Servidor de envio. Ignorado com `resend_api`. |
| `STUDIO_SMTP_PORT` | **sim** | não | execução | `465` | `465` usa TLS direto. `587` existe, mas exige `STUDIO_SMTP_SECURITY=starttls`. |
| `STUDIO_SMTP_SECURITY` | não | não | execução | `ssl` | `ssl` para 465, `starttls` para as outras. Vazio deixa o código decidir pela porta; preencher evita surpresa. |
| `STUDIO_SMTP_USER` | **sim** | não | execução | `resend` | No Resend o usuário é literalmente `resend`. |
| `STUDIO_SMTP_PASSWORD` | **sim** | **sim** | execução | `re_FICTICIA_nao_use` | A chave de API do Resend, nos dois transportes (senha SMTP ou token Bearer). **Selada.** |

> O envio inteiro tem teto de 12 s: se o Resend não responder, o cadastro volta na hora com `sent: false` e a
> mensagem de que o envio falhou e o administrador pode confirmar o código (`studio admin verify-email`).
>
> Sem `STUDIO_SMTP_HOST` (transporte `smtp`) ou sem `STUDIO_MAIL_FROM` em staging nada é enviado **e o conteúdo não vai para o log**
> (em dev iria). Então convite e confirmação de e-mail simplesmente não chegam: configure antes de testar
> o cadastro de ponta a ponta.

## 6. Backup (R2)

Duas finalidades, mesmas credenciais: o Litestream replica o **banco** continuamente e o
`scripts/backup_media.sh` copia a **mídia** uma vez por dia, agora de dentro do contêiner.

| Variável | Obrig. | Segredo | Quando | Valor no staging | Para que serve |
|---|---|---|---|---|---|
| `BACKUP_BUCKET` | **sim** | não | execução | `kiroo-backups` | Bucket privado no R2. Prefixo dentro dele = `STUDIO_ENV`, logo `staging/`. |
| `BACKUP_R2_ENDPOINT` | **sim** | não | execução | `https://ID_FICTICIO.r2.cloudflarestorage.com` | Endpoint S3 da conta R2. Não é segredo, mas identifica a conta: trate como informação interna. |
| `BACKUP_R2_ACCESS_KEY_ID` | **sim** | **sim** | execução | `AKFICTICIA0000000000` | Chave do token R2. **Selada.** O token deve poder ler e escrever **só** `kiroo-backups`. |
| `BACKUP_R2_SECRET_ACCESS_KEY` | **sim** | **sim** | execução | `segredo-ficticio-nao-use` | Segredo do token. **Selada.** |
| `BACKUP_R2_PREFIX` | não | não | execução | *(não definir)* | Padrão = `STUDIO_ENV`. Só mude em ensaio, para não misturar com o staging de verdade. |
| `STUDIO_RESTORE_ON_EMPTY` | não | não | execução | `1` | Se o volume subir **sem** banco e houver réplica, restaura antes de abrir. Nunca sobrescreve banco existente. Vale para recuperar volume perdido. |
| `STUDIO_ALLOW_NO_BACKUP` | não | não | execução | *(não definir)* | Só `production` exige backup. Em staging não tem efeito. |
| `STUDIO_MEDIA_BACKUP` | não | não | execução | *(não definir)* | Em `staging` o laço diário já vem ligado. `0` desliga, `1` liga em dev. |
| `STUDIO_MEDIA_BACKUP_INTERVAL_S` | não | não | execução | *(não definir)* | Padrão `86400` (24 h). |
| `STUDIO_MEDIA_BACKUP_DELAY_S` | não | não | execução | *(não definir)* | Padrão `300`: espera o servidor subir antes da primeira cópia. |

> Sem as três `BACKUP_R2_*` o staging **sobe mesmo assim**, com aviso alto no log e
> `backup_not_configured` em `/readyz` — e sem nenhuma cópia dos dados. Em `production` ele recusaria subir.

## 7. Pastas e operação

| Variável | Obrig. | Segredo | Quando | Valor no staging | Para que serve |
|---|---|---|---|---|---|
| `STUDIO_DATA_DIR` | não | não | execução | `/data` | Já vem na imagem e é onde o volume do Railway é montado. Banco, produções e uploads moram aqui. |
| `STUDIO_ASSETS_DIR` | não | não | execução | `/app/assets` | Já vem na imagem. |
| `STUDIO_PROFILES_DIR` | não | não | execução | `/app/profiles` | Já vem na imagem. |
| `STUDIO_REFERENCE_DIR` | não | não | execução | `/reference` | Referência pessoal. Em staging fica vazia; o `doctor` apenas informa que falta. |
| `STUDIO_LOG_FORMAT` | não | não | execução | `json` | Já vem na imagem. Linha por evento, que é o que os logs do Railway mostram bem. |
| `STUDIO_WAL_CHECKPOINT_S` | não | não | execução | *(não definir)* | Padrão `300`: checkpoint `PASSIVE` do WAL. |
| `STUDIO_RATE_LIMIT` | não | não | execução | *(não definir)* | Limites já vêm ligados com padrões sensatos. **Não coloque `0` em staging.** |
| `RAILWAY_RUN_UID` | **sim** | não | execução | `0` | Faz o contêiner começar como root para o entrypoint poder ajustar o dono de `/data`. Ele então **desce para o uid 10001** com `setpriv` antes de iniciar o Litestream e o servidor. Ver [docs/RAILWAY.md](RAILWAY.md). |
| `KIROO_SKIP_PRIV_DROP` | não | não | execução | *(não definir)* | Plano B ruim: `1` mantém o app como **root**. Só para desempatar um diagnóstico, nunca como configuração final. |

## 8. Build (só durante a construção da imagem)

Estas **não** existem no serviço em execução: são as credenciais de **leitura** do pacote privado de arte.

| Variável | Obrig. | Segredo | Quando | Valor no staging | Para que serve |
|---|---|---|---|---|---|
| `R2_ACCOUNT_ID` | **sim** | **sim** | build | `ID_FICTICIO_DA_CONTA` | Conta R2 de onde vem o ZIP de arte licenciada. **Selada.** |
| `R2_ACCESS_KEY_ID` | **sim** | **sim** | build | `AKFICTICIA1111111111` | Token **somente leitura** do bucket de assets. **Selada.** |
| `R2_SECRET_ACCESS_KEY` | **sim** | **sim** | build | `outro-segredo-ficticio` | Segredo do token. **Selada.** |
| `GIT_COMMIT` | não | não | build | *(automático)* | Vira o rótulo `org.opencontainers.image.revision`. Não é segredo. |

Pontos de atenção:

- Use um token R2 **separado** e só de leitura para a arte. Não reaproveite o token de backup, que escreve.
- No Railway estas três chegam ao build como `ARG` do estágio `assets`. Elas **não** entram na imagem final,
  nem nas camadas, nem no `Config.Env`, nem no `docker history` — provado por
  `python scripts/verify_build_args.py`. Mas ficam no histórico do **estágio intermediário**, então a imagem
  só pode ir para registro privado.
- Sem as três, o build **falha de propósito**, antes de qualquer acesso à rede.
- Rotacionar o token de leitura depois de validar o staging é uma boa ideia de qualquer forma.

---

## Conferência rápida antes de abrir para alguém

```bash
curl -fsS https://staging.kiroo.app/healthz
curl -fsS https://staging.kiroo.app/readyz          # "warnings" vazio = backup configurado
```

E depois, o roteiro completo:

```bash
python scripts/smoke.py https://staging.kiroo.app
```

Sinais de configuração errada que aparecem logo:

| Sintoma | Causa provável |
|---|---|
| `/readyz` traz `backup_not_configured` | falta alguma `BACKUP_R2_*` |
| Toda requisição cai no limite junta | `STUDIO_TRUST_PROXY` não está em `cloudflare` |
| Página responde `400` por host | host de acesso fora de `STUDIO_ALLOWED_HOSTS` |
| Login não mantém a sessão | `STUDIO_SECURE_COOKIE=1` sem HTTPS na frente |
| Convite e confirmação não chegam | `STUDIO_SMTP_*` ou `STUDIO_MAIL_FROM` ausentes |
| Erro de permissão em `/data` no boot | falta `RAILWAY_RUN_UID=0` |
| Servidor recusa subir citando orçamento | `STUDIO_STOP_GRACE_S` menor que `grace + 2 + settle + 5` |
