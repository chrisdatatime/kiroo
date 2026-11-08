# Segurança do Kiroo: feito e pendente

Estado da segurança mínima para abrir o **staging** (Fase 5 enxuta). Cada item "feito" aponta o código e o teste que
o comprova. O que não foi exercitado de verdade está marcado **NAO_VERIFICADO**. Operação: [ADMIN.md](ADMIN.md).
Variáveis: [.env.example](../.env.example) e [RUNBOOK.md](RUNBOOK.md).

## Feito

### 1. E-mail transacional
- SMTP pronto para o Resend (`smtp.resend.com`, usuário `resend`, senha = chave de API), TLS direto na 465 ou
  STARTTLS nas outras portas; `STUDIO_SMTP_SECURITY=none` só é aceito para 127.0.0.1/localhost. Remetente
  `STUDIO_MAIL_FROM` obrigatório em staging/produção. Mensagens em PT-BR com `Content-Language: pt-BR`, `Message-ID`
  do domínio do remetente e `Auto-Submitted`.
  Segundo transporte, `STUDIO_MAIL_TRANSPORT=resend_api` (padrão `smtp`): HTTPS para `api.resend.com` com
  `Authorization: Bearer` (a mesma chave de `STUDIO_SMTP_PASSWORD`), só biblioteca padrão, timeout de 10 s, sem seguir
  redirecionamentos (a chave não é reenviada a outro destino) e rejeitando quebra de linha em chave/destinatário/assunto.
  O envio inteiro tem teto de 12 s em qualquer transporte, então um SMTP/API travado não segura a resposta do cadastro.
  Em falha o log traz só o tipo do erro ou o status HTTP: nunca a chave, o corpo da resposta, o e-mail, o código ou o link. Recusa cabeçalho com quebra de linha. — `src/studio/mailer.py`
- Código de confirmação: 6 dígitos, 30 min, uso único, 5 tentativas, reenvio a cada 45 s. Link de nova senha: 30 min,
  uso único, só o último pedido vale, derruba as sessões. — `src/studio/accounts.py`
- Falha fechada: em staging/produção (`STUDIO_ENV` ou `STUDIO_SECURE_COOKIE=1`) sem SMTP completo, nada é enviado e
  nem código nem link vão ao log (só em dev o operador vê no terminal). A falha de SMTP registra só o tipo do erro.
- Teste ponta a ponta com servidor SMTP falso (cadastro → código → confirmação; esqueci a senha → link → nova senha):
  `tests/test_mail.py`, `tests/smtp_fake.py`. **O envio real pelo Resend é NAO_VERIFICADO** (fica para o staging).

### 2. Gasto
- Portão único das chamadas pagas (Gemini e Anthropic) — `src/studio/paid_gate.py`:
  `STUDIO_KILL_SWITCH=1` bloqueia tudo; `STUDIO_ALLOW_PAID_CALLS` padrão 0 em staging/produção (0 explícito vale até
  em dev); `STUDIO_MONTHLY_CAP_USD` vira teto do mês da plataforma inteira (gerações, testes de treinamento e chat) e é
  obrigatório em staging/produção; `STUDIO_AGENT_DAILY_CAP_USD` limita cada agente por dia em cada estúdio.
- O orquestrador checa antes de cada chamada e pausa a produção com aviso amigável ("Nada foi cobrado"); os
  adaptadores Gemini e o caller Anthropic têm trava final antes de abrir conexão; o chat cai em resposta pronta; o
  teste de treinamento recusa; criar produção real responde 409 e `/api/me` traz `paid_calls`.
- Teste que os tetos **realmente bloqueiam** (nenhuma chamada sai depois do limite): plataforma, agente/dia, missão
  (orçamento da produção) e workspace (teto mensal), além do kill switch e dos padrões por ambiente —
  `tests/test_paid_gate.py`.

### 3. Abuso
- Limite em memória (janela deslizante) por IP e por usuário em `/api/*`, mais baixo em auth (por IP), chat, upload e
  criação de produção (por usuário); 429 com `Retry-After`; tudo em `STUDIO_RATE_*`. — `src/studio/ratelimit.py`,
  `tests/test_rate_limit.py`
- Continua: limite de login por e-mail e por IP (8 / 15 min) e de convite errado por IP, gravados no banco.
- Cloudflare Turnstile no cadastro, login, esqueci a senha e reenvio de código: token conferido no servidor em `siteverify`
  (timeout 5 s, sem seguir redirecionamento, IP real conforme `STUDIO_TRUST_PROXY`) **antes** de consultar usuário, sessão ou
  consumir convite, então não revela quais e-mails existem. Token ausente/inválido/expirado/reutilizado → `400 captcha_invalido`;
  Cloudflare fora do ar, segredo recusado ou meia configuração em staging/produção → `503 captcha_indisponivel` (falha fechada).
  O segredo entra em `secret_values()`; token e segredo nunca vão a log. CSP libera só `https://challenges.cloudflare.com`
  (`script-src` e `frame-src`). — `src/studio/turnstile.py`, `tests/test_turnstile.py`, `docs/TURNSTILE.md`

### 4. Autorização
- IDOR: usuário A contra o workspace B em todas as rotas com id (estado, as 16 ações de produção, mídia, chat, troca
  de workspace, trilhas, treinamento, gastos/créditos), sem sessão, CSRF de outra pessoa e controle positivo da dona.
  — `tests/test_authz.py`
- Path traversal em `/media` (../, `%2e%2e`, `%2f`, `%5c`, barra invertida, caminho absoluto) e `/assets`: 404.
- Uploads: nome sem caminho nem caractere de controle (até 200), limite por arquivo (20 MB imagem, 100 MB vídeo)
  conferido antes de decodificar, tipo real pelos bytes (PNG, JPG, WEBP, MP4/MOV, WebM), nada gravado se um arquivo
  do envio for recusado; o nome no disco é gerado pelo servidor. Referência de treinamento: imagem conferida pelos
  bytes e texto sem NUL. Trilhas: ffprobe precisa achar áudio. — `src/studio/web/uploads.py`, `src/studio/storage.py`

### 5. Segredos
- `secret_values()` cobre Gemini, Anthropic, Google OAuth (segredo), SMTP, qualquer `MP_*`, backup R2/Litestream e
  códigos de convite antigos. — `src/studio/config.py`
- Redação no log em arquivo (inclusive traceback), no log JSON (só o tipo da exceção), nas respostas 400, no erro de
  produção mostrado na interface e na mensagem do provedor gravada na tentativa. `/readyz` só diz ok/falha.
  Exceção inesperada vira `500 {"error": "erro interno"}` sem stack trace. — `src/studio/logs.py`,
  `tests/test_secrets.py`

### 6. Cadastro e privacidade
- `STUDIO_SIGNUP=invite` com códigos de uso único da CLI (`studio admin create-invite`), validade de 1 a 30 dias,
  opcionalmente presos a um e-mail, reservados de forma atômica (dois cadastros com o mesmo código: só um passa), só o
  hash no banco. `STUDIO_INVITE_CODES` foi aposentado (ignorado com aviso). — schema v2 em `src/studio/migrations.py`
- Consentimento obrigatório no cadastro, gravado com data e versão (`terms_accepted_at`, `terms_version`).
- Páginas públicas `/termos` e `/privacidade`, **rascunho marcado PARA REVISÃO JURÍDICA**. —
  `src/studio/web/static/termos.html`, `privacidade.html`
- Exportar (`GET /api/account/export`) e apagar a própria conta (`POST /api/account/delete`, com senha e `APAGAR`):
  banco e arquivos (produções, uploads, trilhas, treinamento). — `src/studio/privacy.py`, `tests/test_signup_privacy.py`

### Já existia (fases anteriores)
Cadastro fechado por padrão, ninguém vira admin sozinho, CSRF por sessão, cabeçalho de cliente nas rotas de auth,
cookie HttpOnly/SameSite=Lax (Secure em produção), CSP sem script inline, HSTS, lista de hosts, proxy só quando
declarado, senha com scrypt, trava de instância única, backup com Litestream.

## Pendente

| # | Item | Por quê / próximo passo |
|---|---|---|
| 1 | **Envio real pelo Resend** | NAO_VERIFICADO. No staging: domínio verificado (SPF/DKIM/DMARC), `STUDIO_SMTP_*` + `STUDIO_MAIL_FROM`, cadastro real e "esqueci a senha" ponta a ponta. |
| 2 | **Revisão jurídica** de `/termos` e `/privacidade` | Preencher razão social, CNPJ, encarregado, prazos de guarda (logs, créditos, backup), transferência internacional e regras de crédito/reembolso. Ao mudar o texto, subir `TERMS_VERSION`. |
| 3 | Interface para exportar/apagar conta | As rotas existem e estão testadas; falta o botão na área da conta (hoje: chamada direta ou `studio admin export-user/delete-user`). |
| 4 | Aviso visual do kill switch no jogo | `/api/me.paid_calls` e o 409 trazem a mensagem; o frontend ainda não mostra um banner próprio (a mensagem de erro aparece no toast). |
| 5 | Consentimento no login com Google | Só cria conta em `STUDIO_SIGNUP=open` (staging usa `invite`, então não acontece); antes de abrir o cadastro, pedir o aceite na primeira entrada pelo Google. |
| 6 | Limite de requisições com mais de uma réplica | O limite é em memória; com réplicas, mover para Redis ou para o proxy (Cloudflare Rate Limiting). |
| 7 | Backups depois de apagar conta | Dados apagados continuam nas cópias do Litestream/R2 até expirar a retenção. Definir e documentar a retenção. |
| 8 | Créditos de conta apagada | Mantidos sem vínculo (nota trocada, workspace removido) por possível obrigação fiscal: confirmar com o jurídico/contador. |
| 9 | `delete-user` pela CLI com produção rodando | A interface recusa (409); a CLI não confere. Pause as produções antes. |
| 10 | Antivírus/decodificação completa de imagem | A checagem é pelos bytes iniciais e tamanho; a imagem não é decodificada inteira (sem Pillow). Arquivos só são servidos de volta com `nosniff` e tipo fixo. |
| 11 | MFA para o administrador | Não há segundo fator. Mitigação: senha forte, admin só por CLI, sessão de 30 dias (avaliar encurtar para admin). |
| 12 | Auditoria de ações de admin | `studio admin` não grava trilha de auditoria (quem concedeu crédito/liberou real). |
| 14 | Envio real de chamadas pagas no staging | O portão foi testado com provedores falsos. Ligar `STUDIO_ALLOW_PAID_CALLS=1` + teto baixo no staging e conferir uma geração real é NAO_VERIFICADO. |

## Verificação desta fase
- `pytest` (venv Python 3.12 com o projeto instalado), sobre a base `e34ee1a`: **430 passaram, 1 desmarcado** (`-m "not real"`).
- Teste antes intermitente `test_hardening::test_json_logs_have_no_personal_data_and_mask_secrets`: a linha `request` é
  registrada depois da resposta e o teste removia o handler antes (corrida; 1/30 isolado). Corrigido com espera por
  evento, asserções intactas: 30/30, e 5/5 com atraso de 0,2 s injetado entre a resposta e o log.
- `npm test` (frontend): **ok, check:brand + 11 testes**. `npm run build` compilou.
- Tela de cadastro conferida no navegador com servidor local: convite da CLI + aceite → tela de confirmação; botão
  desabilitado sem o aceite; `/privacidade` renderiza.
