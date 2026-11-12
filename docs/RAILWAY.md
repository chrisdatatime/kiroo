# Subir o staging no Railway — passo a passo no painel

Para você fazer sozinho, na ordem. Cada passo diz **o que clicar** e **como saber que deu certo**.
Os valores das variáveis estão em [docs/ENVS.md](ENVS.md); aqui é só a sequência.

O que vamos montar: **um** serviço, construído pelo Railway a partir do nosso `Dockerfile`, com **um**
volume de 5 GB em `/data`, instância única, healthcheck em `/healthz`, domínio `staging.kiroo.app` atrás
da Cloudflare e **sem** o domínio `*.up.railway.app`.

Três decisões já tomadas, para não precisar pensar nelas no meio:

- **Não usamos `railway.json` nem Config as Code.** A documentação do Railway marca esse recurso como
  depreciado, com os arquivos funcionando para serviços legados só até 2026-12-01. Toda configuração
  vai no painel e está documentada aqui.
- **Sem réplicas.** O servidor é de instância única (o SQLite e o livro de créditos exigem isso) e, de
  todo modo, a documentação do Railway diz que réplicas não funcionam com volume.
- **Plano Hobby.** Basta para este serviço. A única coisa que ele **não** permite é puxar imagem de
  registro privado, o que é exatamente o motivo de construirmos no Railway (ver a última seção).

---

## 1. Autorizar o GitHub só para o repositório do Kiroo

1. No Railway, abra o menu da sua conta → **Account Settings** → **Connected Accounts** (ou **Integrações**).
2. Em **GitHub**, clique em **Configure** / **Install**.
3. Na tela do GitHub, escolha **Only select repositories** e marque **apenas** o repositório do Kiroo.
4. **Save** / **Install**.

**Deu certo quando:** ao criar o serviço (passo 3), o repositório do Kiroo aparece na lista e nenhum outro
repositório seu aparece.

> Não escolha "All repositories". Não há motivo para o Railway ver seus outros repositórios.

## 2. Criar o projeto e o ambiente `staging`

1. **New Project** → dê o nome `kiroo`.
2. Entre no projeto. No alto aparece o ambiente, normalmente `production`.
3. Clique nele → **New Environment** → nome `staging` → crie.
4. **Fique dentro do ambiente `staging`** para tudo o que vem depois. Confira o nome no alto da tela antes
   de cada passo.

**Deu certo quando:** o seletor de ambiente mostra `staging`.

> Se o ambiente `production` ficar vazio, está ótimo: por ora só existe staging.

## 3. Criar o serviço a partir do repositório

1. Dentro do ambiente `staging`: **New** → **GitHub Repo** → escolha o repositório do Kiroo.
2. O Railway cria o serviço e tenta um primeiro build. **Ele vai falhar**, porque as credenciais de build
   ainda não existem. Isso é esperado — é o build falhando fechado, como projetado.
3. Abra **Settings** do serviço:
   - **Service Name**: `kiroo-staging`.
   - **Source** → **Branch**: `deploy/staging`.
   - **Build** → confirme que o **Dockerfile Path** é `Dockerfile` (raiz do repositório). Se o Railway
     tiver escolhido Railpack/Nixpacks sozinho, troque para Dockerfile.
   - **Root Directory**: deixe vazio (o repositório inteiro é o contexto do build).
4. Em **Settings** → **Deploy**, desligue o deploy automático por ora (**Wait for CI** ou
   **Automatic Deploys** → off), para você mesmo escolher quando o próximo build roda.

**Deu certo quando:** Settings mostra a branch `deploy/staging` e o Dockerfile na raiz.

## 4. Variáveis de build e de execução

Abra a aba **Variables** do serviço. Use **Raw Editor** para colar tudo de uma vez — é mais rápido e
erra menos. Os valores saem de [docs/ENVS.md](ENVS.md).

**4a. Primeiro as que vão SELADAS (*sealed*).** Variável selada não pode mais ser lida nem desselada:
**guarde cada valor no seu gerenciador de senhas antes de colar aqui.** Para cada uma, adicione a
variável e marque a opção de selar (**Seal**) antes de salvar:

| Variável | Para que |
|---|---|
| `R2_ACCOUNT_ID` | build (arte) |
| `R2_ACCESS_KEY_ID` | build (arte, só leitura) |
| `R2_SECRET_ACCESS_KEY` | build (arte, só leitura) |
| `BACKUP_R2_ACCESS_KEY_ID` | execução (backup) |
| `BACKUP_R2_SECRET_ACCESS_KEY` | execução (backup) |
| `STUDIO_SMTP_PASSWORD` | execução (chave do Resend) |

**4b. Depois as visíveis**, que é bom poder conferir depois:

```
STUDIO_ENV=staging
STUDIO_MODE=simulated
STUDIO_ALLOW_PAID_CALLS=0
STUDIO_MONTHLY_CAP_USD=0
STUDIO_SIGNUP=invite
STUDIO_PUBLIC_HOST=staging.kiroo.app
STUDIO_ALLOWED_HOSTS=staging.kiroo.app
STUDIO_SECURE_COOKIE=1
STUDIO_TRUST_PROXY=cloudflare
STUDIO_MAIL_FROM=Kiroo <nao-responda@kiroo.app>
STUDIO_MAIL_TRANSPORT=resend_api
BACKUP_BUCKET=kiroo-backups
BACKUP_R2_ENDPOINT=https://SUA_CONTA.r2.cloudflarestorage.com
STUDIO_RESTORE_ON_EMPTY=1
STUDIO_STOP_GRACE_S=40
RAILWAY_DEPLOYMENT_DRAINING_SECONDS=40
RAILWAY_RUN_UID=0
```

Três avisos que valem o tempo de ler:

- **E-mail: use `STUDIO_MAIL_TRANSPORT=resend_api`.** O Railway bloqueia a saída SMTP: `smtp.resend.com` nas portas
  465 e 587 estoura `TimeoutError` (medido no staging; o cadastro chegou a levar 30 s). A API HTTPS do Resend passa.
  Com ela só são necessárias `STUDIO_SMTP_PASSWORD` (a chave, selada) e `STUDIO_MAIL_FROM`; `STUDIO_SMTP_HOST`,
  `_PORT`, `_USER` e `_SECURITY` ficam de fora. Se o envio falhar, o cadastro responde em até ~12 s dizendo que o
  e-mail não saiu e que o administrador pode confirmar o código.

- **Não defina `STUDIO_PORT`.** O Railway injeta `PORT` e o código a usa. `STUDIO_PORT` venceria a
  da plataforma e o healthcheck bateria na porta errada.
- **`RAILWAY_DEPLOYMENT_DRAINING_SECONDS=40` não é opcional.** O padrão do Railway é **0**, isto é,
  `SIGKILL` imediatamente depois do `SIGTERM`. Sem ela o banco pode ser cortado no meio de uma escrita.
- **`RAILWAY_RUN_UID=0` não deixa o app como root.** Ela faz o contêiner *começar* como root para o
  nosso entrypoint poder ajustar o dono de `/data`; em seguida ele desce para o uid 10001 (`setpriv`) e
  só então sobe o Litestream e o servidor. Detalhe no passo 5.

**Deu certo quando:** as seis seladas aparecem como seladas (sem valor visível) e as visíveis estão
exatamente como acima, com o seu endpoint do R2 no lugar de `SUA_CONTA`.

## 5. Volume de 5 GB em `/data`

1. No serviço: **New** (ou **+**) → **Volume**.
2. **Mount path**: `/data` — exatamente isso, que é o `STUDIO_DATA_DIR` da imagem.
3. **Size**: `5 GB` (o máximo do Hobby; o padrão do plano já é 5 GB).
4. Salve. O Railway vai querer um redeploy; pode deixar para o passo 7.

**Deu certo quando:** o volume aparece preso ao serviço com o caminho `/data`.

Sobre o volume, para você não se assustar depois:

- **Só um volume por serviço** e **nada de réplicas** — que é o que queremos.
- **Todo redeploy tem uma paradinha.** O Railway impede dois deploys montados no mesmo volume ao mesmo
  tempo, então o antigo sai antes do novo entrar. Isso acontece **mesmo com healthcheck configurado** e
  não há como evitar; são segundos, e com `DRAINING_SECONDS=40` a parada é limpa.
- **Por que `RAILWAY_RUN_UID=0`:** o Railway monta o volume pertencendo ao `root`, e nossa imagem roda
  como `kiroo` (uid 10001). Sem isso, o servidor não conseguiria escrever em `/data`. Com a variável, o
  entrypoint começa como root, ajusta o dono de `/data`, **troca de usuário** e só então inicia o app.
  Nada do app roda privilegiado. Se algum dia precisar depurar, existe `KIROO_SKIP_PRIV_DROP=1`, que
  mantém tudo como root — **é pior e não deve ficar ligado**: um furo no servidor viraria root no
  contêiner, com acesso de escrita a toda a imagem, não só ao volume.
- **Backup não dispensa volume, e volume não dispensa backup.** O banco vai continuamente para o R2 pelo
  Litestream e a mídia uma vez por dia. O Railway também oferece backup de volume (diário, semanal,
  mensal); se quiser, ligue o diário — é cobrado como volume e não substitui o nosso.
- **Cresce, não encolhe.** Dá para aumentar o volume ao vivo nos planos pagos; **reduzir não existe**.

## 6. Healthcheck em `/healthz`

1. **Settings** → **Deploy** → **Healthcheck Path**: `/healthz`.
2. **Healthcheck Timeout**: deixe o **padrão** (300 s). É o que pedimos.

**Deu certo quando:** o próximo deploy mostra o healthcheck passando antes de virar `Active`.

Dois detalhes úteis:

- O Railway usa o host `healthcheck.railway.app` nessa chamada. Nosso `STUDIO_ALLOWED_HOSTS` **não**
  precisa listá-lo: `/healthz` responde antes da checagem de host. Se algum dia o healthcheck falhar com
  `400`, é aí que se olha primeiro.
- O healthcheck roda **só na subida**. Depois que o deploy fica ativo, o Railway não monitora mais esse
  endereço — não espere dele um alarme de serviço caído.

## 7. Primeiro deploy de verdade

1. **Deployments** → **Deploy** (ou **Redeploy**) na branch `deploy/staging`.
2. Acompanhe o log de build. O estágio `assets` é o primeiro que usa as credenciais; se elas estiverem
   erradas, ele para ali com uma mensagem citando só os **nomes** das variáveis.
3. Depois do build, o log de execução deve mostrar, nesta ordem: ajuste de dono de `/data` (só na
   primeira vez), o Litestream subindo, o orçamento de desligamento e o servidor escutando.

**Deu certo quando** o log de execução traz algo como:

```
desligamento: grace 25s + settle 3s; a plataforma precisa dar pelo menos 35s (STUDIO_STOP_GRACE_S=40)
Kiroo em http://0.0.0.0:8080/ (escutando em 0.0.0.0:8080)
```

E então, pelo domínio temporário do próprio Railway ou já pelo definitivo:

```bash
curl -fsS https://staging.kiroo.app/healthz
curl -fsS https://staging.kiroo.app/readyz
```

`/readyz` com `"warnings": []` quer dizer que o backup está configurado. Se vier
`backup_not_configured`, falta alguma `BACKUP_R2_*`.

## 8. Domínio `staging.kiroo.app` atrás da Cloudflare

**No Railway:**

1. **Settings** → **Networking** / **Public Networking** → **+ Custom Domain**.
2. Digite `staging.kiroo.app`.
3. O Railway mostra **dois** registros: um `CNAME` (algo como `abc123.up.railway.app`) e um `TXT` de
   verificação. **Anote os dois exatamente como aparecem.**

**Na Cloudflare** (DNS do `kiroo.app`):

4. **DNS** → **Add record** → `CNAME`, nome `staging`, destino = o valor que o Railway deu.
   **Proxy status: Proxied** (nuvem laranja).
5. **Add record** → `TXT`, com nome e valor exatamente como o Railway mostrou.
6. **SSL/TLS** → **Overview** → modo **Full**.

**Deu certo quando:** o Railway mostra o domínio como verificado e com certificado emitido, e
`curl -I https://staging.kiroo.app/healthz` responde `200`.

Pontos em que isso costuma dar errado:

- **Os dois registros são obrigatórios.** Só com o `CNAME`, o domínio não verifica e as requisições
  voltam `404`.
- **O modo SSL tem de ser `Full`, não `Full (Strict)`.** Com proxy ligado, a documentação do Railway diz
  que `Full (Strict)` não funciona como se espera. `Flexible` então nem pensar: deixaria o trecho
  Cloudflare→Railway sem criptografia.
- `staging.kiroo.app` é subdomínio de primeiro nível, então pode ficar **proxied** sem problema. A
  restrição de desligar o proxy vale para nomes mais profundos, tipo `a.b.kiroo.app`.
- DNS pode levar horas para propagar. O Railway tenta emitir o certificado por até 72 h.
- O Hobby permite **2 domínios por serviço**, o que sobra para nós.

**Regras de cache na Cloudflare.** Por padrão a Cloudflare não guarda HTML, mas é melhor ser explícito
para que nenhuma resposta de API ou de mídia privada fique em cache compartilhado:

7. **Rules** → **Cache Rules** → **Create rule**:
   - Nome: `kiroo-staging-sem-cache`.
   - Condição: **URI Path** `starts with` `/api/` — clique em **Or** e acrescente **URI Path**
     `starts with` `/media/`.
   - Ação: **Cache eligibility** → **Bypass cache**.
   - **Deploy**.

   - A aba Administrador (`/api/admin/*`) já está coberta por `/api/`. Se um dia a regra for estreitada,
     mantenha uma condição explícita **URI Path** `starts with` `/api/admin/` com **Bypass cache**: dado de
     administrador nunca pode ficar em cache compartilhado (o servidor também manda `Cache-Control: no-store, private`).

**Deu certo quando:** uma resposta de `/api/` vier com `cf-cache-status: BYPASS` (ou `DYNAMIC`).

```bash
curl -sSI https://staging.kiroo.app/api/config | grep -i cf-cache-status
```

> O servidor já manda `Cache-Control: private, no-store` na mídia; a regra é cinto e suspensório. Mídia é
> servida por usuário e com verificação de dono — cache compartilhado ali seria vazamento entre contas.

## 9. Não gerar o domínio `*.up.railway.app`

A recomendação é **nunca clicar em "Generate Domain"**. Se o serviço ainda não tem domínio gerado, é só
não criar: vá direto ao domínio próprio do passo 8.

Se você já gerou um (por exemplo para testar no passo 7), remova depois que o domínio próprio estiver
funcionando: **Settings** → **Networking**, no domínio `*.up.railway.app` abra o menu (`⋮` ou o ícone de
lixeira) e remova.

**NAO_CONFIRMADO:** a documentação do Railway que eu li descreve como **gerar** o domínio, mas não
descreve removê-lo ou desativá-lo. A remoção pelo painel é o caminho esperado, mas eu não a vi
documentada, então confirme no painel antes de contar com ela.

Um cuidado real nessa ordem: o tráfego Cloudflare→Railway é cifrado com o certificado
`*.up.railway.app` do Railway. Por isso **primeiro** confirme `staging.kiroo.app` respondendo `200`,
**depois** remova o domínio gerado. E, enquanto ele existir, mantenha-o em `STUDIO_ALLOWED_HOSTS` —
senão o acesso por ele responde `400`.

Por que isso importa mais que estética: com `STUDIO_TRUST_PROXY=cloudflare` o servidor confia no
cabeçalho `CF-Connecting-IP`. Quem alcançar o serviço **sem** passar pela Cloudflare pode mandar esse
cabeçalho à mão e forjar o IP de origem, contornando o limite de requisições. Fechar a porta dos fundos
é o que torna o `trust_proxy` seguro.

## 10. Criar seu usuário e o primeiro convite

Com `STUDIO_SIGNUP=invite`, o cadastro só aceita código de uso único. Duas formas:

**Pelo bootstrap (mais simples):** adicione `STUDIO_BOOTSTRAP_ADMIN_EMAIL=voce@exemplo.com`, faça
redeploy e espere o e-mail com o link para definir a senha. Depois remova a variável.

**Pela CLI, no contêiner:** abra o serviço no painel → menu do deploy → **Shell** / **Terminal** (ou use
`railway run`, se tiver o CLI instalado) e rode:

```bash
python -m studio admin create-user --email voce@exemplo.com --admin
```

```bash
python -m studio admin create-invite --days 7
```

O código do convite aparece **só nesse momento** (no banco fica apenas o hash). Anote na hora.

**Deu certo quando:** você entra em `https://staging.kiroo.app/` com seu e-mail e senha.

## 11. Ver logs

- **Deployments** → clique no deploy → **Deploy Logs** (execução) e **Build Logs** (construção).
- O log é JSON, uma linha por evento: dá para filtrar pela caixa de busca por `event` (`start`,
  `shutdown_budget`, `settle_start`, `interrupted`, `resumed`).
- Eventos que valem reconhecer:

| O que você vê | O que significa |
|---|---|
| `ATENÇÃO: BACKUP DO BANCO NÃO CONFIGURADO` | falta `BACKUP_R2_*`: os dados estão sem cópia |
| `ajustando o dono de /data` | primeira subida no volume novo (normal; some depois) |
| `ATENÇÃO: KIROO_SKIP_PRIV_DROP=1` | o app está como **root**: corrija |
| `media_backup: ok` | backup diário da mídia concluído |
| `media_backup: FALHOU código=` | backup do dia falhou; o laço tenta de novo no próximo ciclo |
| `settle: inicio` / `settle: fim` | desligamento limpo em andamento |

Nenhuma credencial é impressa em lugar nenhum — nem pelo entrypoint, nem pelo backup, nem pelo build.
Se você vir um valor de segredo num log, isso é um defeito: me avise.

## 12. Voltar a um deploy anterior

1. **Deployments** → encontre o deploy que funcionava.
2. Menu (`⋮`) → **Redeploy** (ou **Rollback**).
3. Espere o healthcheck passar.

Duas coisas para ter em mente antes de rolar para trás:

- **O volume não volta com o código.** `/data` continua como está. Se o deploy problemático já aplicou
  migração de banco, voltar o código **não** desfaz a migração. Nesse caso o caminho é restaurar: veja
  `scripts/restore.sh` e [docs/BACKUP.md](BACKUP.md).
- **Variável selada não volta sozinha.** Se você trocou o valor de uma variável, o redeploy antigo usa o
  valor **atual**. Rollback é de código, não de configuração.

## 13. Custo esperado e o que vigiar

Tarifas do Railway no plano Hobby: assinatura **US$ 5/mês** com **US$ 5 de uso incluído** (que não
acumula de um mês para o outro), e depois **US$ 10 por GB de RAM/mês**, **US$ 20 por vCPU/mês**,
**US$ 0,15 por GB de volume/mês** e **US$ 0,05 por GB** de tráfego de saída. Build não é cobrado.

Para este serviço, 24 h por dia, 30 dias, volume de 5 GB:

| Cenário | CPU | RAM | Volume | Uso | Fatura total |
|---|---|---|---|---|---|
| ocioso quase sempre (0,1 vCPU / 256 MB) | 2,00 | 2,50 | 0,75 | 5,25 | **≈ US$ 5,25** |
| com movimento (0,25 vCPU / 512 MB) | 5,00 | 5,00 | 0,75 | 10,75 | **≈ US$ 10,75** |

Ou seja: **entre US$ 5 e US$ 11 por mês**, e o crédito incluído cobre quase tudo no cenário ocioso. O
consumo de CPU e RAM é estimativa minha — o número real aparece na aba **Usage** depois de alguns dias.
Tráfego de saída não está na conta; cada GB baixado soma US$ 0,05.

O que vigiar, em ordem de risco:

1. **Uso de CPU** (aba **Usage**). É o item mais caro: 1 vCPU contínua = US$ 20/mês sozinho. Em modo
   simulado isso não deveria acontecer; se acontecer, é sinal de laço preso, não de carga real.
2. **Ocupação do volume.** Mídia de produção cresce calado. Quando o volume **enche**, o Railway faz
   um redimensionamento **offline**, que reinicia o serviço. Olhe antes de chegar perto de 5 GB — e 5 GB
   é o teto do Hobby, então o próximo degrau é mudar de plano.
3. **Saída de dados**, se você baixar muitos MP4 de teste.
4. **Aviso de orçamento.** Em **Settings** → **Usage Limits**, ponha um limite (uns US$ 15) para receber
   e-mail antes de qualquer surpresa.

Um lembrete sobre o Trial: ele dá **0,5 GB** de volume, menos que os 5 GB de que precisamos. Para este
desenho, Hobby é o piso.

---

## Por que construir no Railway, e não no GitHub Actions — recomendação em 5 linhas

1. **Vá de (a): construir no Railway, com as credenciais do R2 entrando pelos `ARG` do estágio `assets`.**
2. O motivo decisivo é o plano: puxar imagem de registro privado (GHCR) **exige o plano Pro** no Railway,
   então a opção (b) troca um problema técnico por uma conta maior, para um staging de US$ 5.
3. O risco do `ARG` está contido e medido: as credenciais não entram na imagem final, nem nas camadas, nem
   no `Config.Env`, nem no `docker history` — isso é verificado por `scripts/verify_build_args.py`, com
   controle positivo e negativo; ficam apenas no histórico do estágio intermediário, que não é publicado.
4. O que isso custa: o token de leitura da arte passa a existir no painel do Railway (selado) em vez de
   só no GitHub, e a imagem segue restrita a registro privado — aceitável para staging, com token
   separado e só de leitura.
5. **Reavalie se (b) virar a opção melhor:** se um dia houver plano Pro, se a arte licenciada precisar
   de isolamento mais forte, ou se o build no Railway começar a demorar demais — aí o build no Actions
   com imagem privada no GHCR passa a valer, e o mesmo Dockerfile serve aos dois (as credenciais são sempre `ARG`; sem `--mount=type=secret` e sem `VOLUME`, que o validador do Railway recusa).
