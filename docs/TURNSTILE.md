# Cloudflare Turnstile (verificação anti-robô)

O Turnstile aparece em **Entrar, Criar conta, Esqueci a senha e Reenviar código**. O navegador recebe um token do widget; o
servidor o confere na Cloudflare (`siteverify`) **antes** de olhar usuário, sessão ou convite. Sem as duas chaves, nada disso
aparece e o app funciona como antes.

## 1. Criar o widget (staging/produção)

1. Painel da Cloudflare → **Turnstile** → **Add widget** (Adicionar widget).
2. Nome: `Kiroo staging`. **Hostname**: `staging.kiroo.app` (em produção, o domínio de produção; um widget por ambiente).
3. Modo: **Managed**. Salve.
4. Copie a **Site Key** (pública) e a **Secret Key** (segredo; não cole em chat, e-mail, print nem commit).

## 2. Configurar no Railway

No serviço do Kiroo, em *Variables*:

| Variável | Valor |
|---|---|
| `STUDIO_TURNSTILE_SITE_KEY` | a Site Key |
| `STUDIO_TURNSTILE_SECRET_KEY` | a Secret Key |

Salve e faça o redeploy. **As duas juntas**: só uma delas em staging/produção faz o servidor **recusar** cadastro, login, esqueci a
senha e reenvio (`503`), com aviso crítico no log de subida (`Turnstile mal configurado: falta ...`). Garanta também
`STUDIO_TRUST_PROXY=cloudflare` para o servidor mandar o IP real do visitante à Cloudflare.

## 3. Conferir

- `https://staging.kiroo.app/api/config` deve trazer `"turnstile": "<site key>"` (e nunca o segredo).
- Abra a tela de entrar: o widget aparece abaixo dos campos e o botão fica travado até ele concluir.
- No log de subida **não** deve haver aviso de Turnstile. Se houver, leia o texto: ele diz qual variável falta.
- Errou o segredo? A Cloudflare responde `invalid-input-secret` e o app mostra "A verificação de segurança está
  indisponível agora" (o log registra o código de erro, nunca o segredo).

## 4. Desenvolvimento local com as chaves de teste da Cloudflare

Chaves públicas de teste da Cloudflare (confira os valores atuais em *Turnstile → Reference → Testing* na documentação
da Cloudflare antes de usar). Não dependem do hostname e funcionam em `localhost`:

| Objetivo | Site Key | Secret Key |
|---|---|---|
| Sempre passa (widget visível) | `1x00000000000000000000AA` | `1x0000000000000000000000000000000AA` |
| Sempre bloqueia | `2x00000000000000000000AB` | `2x0000000000000000000000000000000AA` |
| Força o desafio interativo | `3x00000000000000000000FF` | `1x0000000000000000000000000000000AA` |
| Token "já usado" | qualquer das de teste | `3x0000000000000000000000000000000AA` |

No `.env` local (nunca versionado), para testar o caminho feliz:

```
STUDIO_TURNSTILE_SITE_KEY=1x00000000000000000000AA
STUDIO_TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA
```

Troque o segredo por um da tabela para ver as recusas. Dois cuidados:

- Chaves de teste **não protegem nada**: nunca as use em staging/produção.
- Misturar chave de teste com chave real recusa tudo (o token de teste não vale para o segredo real e vice-versa).

## 5. O que o usuário vê

- Widget claro, na largura da coluna (cabe em celular de 320 px).
- Botão travado até o token existir; depois de cada tentativa (certa ou errada) o widget recomeça, porque o token vale uma vez.
- Mensagens: "Não foi possível confirmar a verificação de segurança. Tente de novo." (token ruim) e "A verificação de segurança está
  indisponível agora. Tente de novo em instantes." (Cloudflare fora do ar ou chave errada). Se um bloqueador de anúncios impedir o
  script, aparece pedindo para conferir a conexão e recarregar.

## 6. Códigos de erro da API

| Código | HTTP | Quando |
|---|---|---|
| `captcha_invalido` | 400 | token ausente, inválido, expirado ou reutilizado |
| `captcha_indisponivel` | 503 | Cloudflare não respondeu (timeout 5 s, erro, redirecionamento), segredo recusado ou meia configuração em staging/produção |

## 7. Notas de segurança

- A CSP libera apenas `https://challenges.cloudflare.com` em `script-src` e `frame-src`, em um lugar só (`CHALLENGES` em
  `src/studio/web/server.py`).
- O limite de requisições de autenticação continua valendo antes da verificação: tentativas com token ruim contam.
- Nem o token nem o segredo vão para log; o segredo está em `secret_values()` e é mascarado.
- A site key é pública por natureza; o segredo, não. Se vazar, gire-o no painel da Cloudflare e atualize a variável.
