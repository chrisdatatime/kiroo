# Entrar com Google no staging (passo a passo)

Este guia liga o botão **"Continuar com Google"** em `https://staging.kiroo.app/`. Você só precisa de três coisas:
uma tela de consentimento no Google Cloud, uma credencial OAuth e duas variáveis no Railway. Leva uns 15 minutos.

**O que não muda:** o cadastro continua por convite (`STUDIO_SIGNUP=invite`). Com Google:

- **quem já tem conta** entra direto, se o e-mail da conta Google for o mesmo e o Google confirmar que ele é verificado;
- **quem não tem conta** só cria uma em **Criar conta**, digitando um **código de convite válido** e aceitando os Termos
  antes de clicar em **Criar conta com Google**. Sem convite, aparece a mensagem pedindo o código e nada é criado.

---

## 1. A URI de redirecionamento (copie exatamente)

```
https://staging.kiroo.app/api/auth/google/callback
```

- É `https`, sem barra no fim, tudo em minúsculas.
- O servidor monta essa URI a partir de `STUDIO_PUBLIC_HOST` (que no staging já é `staging.kiroo.app`), **nunca** a
  partir do endereço que o navegador digitou. Se você abrir o site pelo domínio do Railway (`*.up.railway.app`), o
  botão leva você primeiro para `staging.kiroo.app` e o login segue de lá.
- Se um dia o endereço público mudar, a URI muda junto: cadastre a nova no Google antes de trocar `STUDIO_PUBLIC_HOST`.

---

## 2. Google Cloud: projeto

1. Abra <https://console.cloud.google.com/> com a conta Google que vai administrar o login.
2. No seletor de projetos (barra de cima), use um projeto existente do Kiroo ou clique em **Novo projeto**
   (nome sugerido: `kiroo-staging`) → **Criar**. Confira que ele ficou selecionado na barra de cima.

## 3. Google Cloud: tela de consentimento (o que o usuário vê ao escolher a conta)

1. Menu ☰ → **APIs e serviços** → **Tela de consentimento OAuth** (em painéis mais novos aparece como
   **Google Auth Platform** → **Branding** / **Público-alvo**).
2. Se pedir para começar, clique em **Começar** / **Configurar**.
3. **Informações do app**
   - Nome do app: `Kiroo`
   - E-mail de suporte do usuário: o seu e-mail.
4. **Público-alvo / Tipo de usuário**: **Externo** (qualquer conta Google pode tentar; quem decide quem entra é o
   convite do Kiroo).
5. **Dados de contato**: o seu e-mail → **Concluir** / **Criar**.
6. **Branding** (opcional agora, recomendado antes de abrir ao público): página inicial `https://staging.kiroo.app/`,
   política de privacidade `https://staging.kiroo.app/privacidade`, termos `https://staging.kiroo.app/termos`,
   domínio autorizado `kiroo.app`.
7. **Escopos / Acesso a dados**: não precisa adicionar nada. O Kiroo só pede `openid`, `email` e `profile`, que são
   escopos básicos e não exigem verificação do Google.
8. **Status de publicação**: em **Teste**, só entram as contas que você listar em **Usuários de teste**
   (adicione o seu e-mail e o de quem for testar). Para liberar qualquer conta, clique em **Publicar app** →
   **Confirmar**. Com só os escopos básicos, a publicação é imediata.

## 4. Google Cloud: credencial OAuth (tipo "Aplicativo da Web")

1. Menu ☰ → **APIs e serviços** → **Credenciais** (ou **Google Auth Platform** → **Clientes**).
2. **+ Criar credenciais** → **ID do cliente OAuth**.
3. **Tipo de aplicativo**: **Aplicativo da Web**. (Não use "Computador" nem "Android/iOS".)
4. **Nome**: `Kiroo staging`.
5. **Origens JavaScript autorizadas**: pode deixar vazio (o login acontece no servidor). Se quiser preencher:
   `https://staging.kiroo.app`.
6. **URIs de redirecionamento autorizados** → **+ Adicionar URI** → cole:
   `https://staging.kiroo.app/api/auth/google/callback`
7. **Criar**. Aparece uma janela com **ID do cliente** (termina em `.apps.googleusercontent.com`) e
   **Chave secreta do cliente** (começa com `GOCSPX-`).
   - Copie os dois direto para o Railway (passo 5). Não cole a chave secreta em chat, e-mail, print ou arquivo do
     repositório.
   - Se perder a chave secreta, volte na credencial e use **Adicionar chave secreta** e depois desative a antiga.

## 5. Railway: as duas variáveis

1. Abra o projeto no Railway → serviço do Kiroo (staging) → aba **Variables**.
2. **+ New Variable**:

   | Nome | Valor |
   |---|---|
   | `STUDIO_GOOGLE_CLIENT_ID` | o **ID do cliente** do passo 4 |
   | `STUDIO_GOOGLE_CLIENT_SECRET` | a **chave secreta do cliente** do passo 4 |

3. Confira que continuam lá, sem mudar: `STUDIO_PUBLIC_HOST=staging.kiroo.app` e `STUDIO_SIGNUP=invite`.
4. Clique em **Deploy** (ou **Apply changes**) para o serviço reiniciar com as variáveis novas.

O servidor só liga o Google com **as duas** variáveis preenchidas. Com uma faltando, o botão simplesmente não aparece.

## 6. Conferir

1. Abra `https://staging.kiroo.app/api/config`. Deve aparecer `"google": true` (o segredo nunca aparece aí).
2. Abra `https://staging.kiroo.app/?entrar`. O botão **Continuar com Google** aparece acima do e-mail.
3. **Conta existente:** clique em **Continuar com Google**, escolha a conta com o mesmo e-mail do seu usuário. Você deve
   entrar no seu estúdio de sempre.
4. **Conta nova com convite:** gere um convite (`python -m studio admin create-invite --days 7`, veja `docs/RAILWAY.md`,
   seção 10), vá em **Criar conta**, cole o código, marque os Termos e clique em **Criar conta com Google**.
5. **Sem convite:** com uma conta Google sem cadastro, clique em **Continuar com Google** na tela de entrar. Deve voltar
   com a mensagem pedindo o código de convite, e nenhuma conta é criada.

## 7. Se der errado

| O que aparece | O que fazer |
|---|---|
| Página do Google: **Erro 400: redirect_uri_mismatch** | A URI do passo 4 está diferente. Cole de novo exatamente `https://staging.kiroo.app/api/auth/google/callback` e espere ~5 min. |
| Página do Google: **Acesso bloqueado / app em teste** | O app está em **Teste** e sua conta não está em **Usuários de teste**. Adicione a conta ou publique o app (passo 3.8). |
| Kiroo: "O login com Google não está ativo" | Falta uma das duas variáveis no Railway, ou o deploy não reiniciou. |
| Kiroo: "expirou antes de terminar" | O login demorou mais de 10 min, o servidor reiniciou no meio, ou o link foi aberto em outro navegador. Tente de novo. |
| Kiroo: "Não conseguimos falar com o Google" | Chave secreta errada/desativada ou o Google fora do ar. Confira a chave no Railway. |
| Kiroo: "O Google não confirmou este e-mail" | A conta Google não tem o e-mail verificado. Entre com e-mail e senha. |
| Kiroo: "Este e-mail já está ligado a outra conta Google" | O e-mail do Kiroo já foi ligado a outra conta Google. Entre com ela ou com e-mail e senha. |

## Como funciona (para quem for revisar)

- Rotas: `GET /api/auth/google/start` → Google → `GET /api/auth/google/callback` (código em `src/studio/web/server.py`,
  regras de conta em `Accounts.google_user`, `src/studio/accounts.py`). Testes: `tests/test_google_login.py`, com um
  Google falso em `tests/google_fake.py`.
- `state` aleatório de uso único (guardado no servidor por 10 min e num cookie HttpOnly), PKCE S256, segredo só no
  servidor. Código, token e segredo não vão para log, mensagem de erro ou resposta.
- Só aceita `email_verified=true`. Liga uma conta existente pelo e-mail só nesse caso. Se essa conta nunca tinha
  confirmado o e-mail, a senha dela é anulada e as sessões caem (protege contra alguém ter cadastrado o e-mail de outra
  pessoa antes). O dono pode criar uma senha depois em "Esqueceu a senha?".
- Conta nova segue `STUDIO_SIGNUP`: `closed` recusa, `invite` exige convite válido (de uso único e, se o convite tiver
  e-mail, só para esse e-mail), `open` cria. Em todos os casos registra o aceite dos Termos.
- As duas rotas contam no limite `STUDIO_RATE_AUTH` (padrão 20 por 5 min por IP). Convites errados também contam no
  bloqueio de tentativas de cadastro.
