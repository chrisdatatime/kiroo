// Cloudflare Turnstile no navegador: o script só é carregado quando o servidor (GET /api/config) entrega a site key.
// A CSP que libera https://challenges.cloudflare.com fica em um lugar só: CHALLENGES em src/studio/web/server.py.

export const TURNSTILE_SRC = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';

// Telas que enviam o token: entrar, criar conta, esqueci a senha e reenvio do código (tela de confirmação).
export const CAPTCHA_MODES = ['login', 'signup', 'forgot', 'verify'];

export const captchaNeeded = (cfg, mode) => !!(cfg && cfg.turnstile) && CAPTCHA_MODES.includes(mode);

// Mensagens em PT-BR por código estável (o servidor manda `code`; o resto vem do cliente).
export const CAPTCHA_ERRORS = {
  captcha_invalido: 'Não foi possível confirmar a verificação de segurança. Tente de novo.',
  captcha_indisponivel: 'A verificação de segurança está indisponível agora. Tente de novo em instantes.',
  captcha_script: 'Não foi possível carregar a verificação de segurança. Confira sua conexão e recarregue a página.',
  captcha_widget: 'A verificação de segurança falhou. Marque-a de novo ou recarregue a página.',
};

export const captchaMessage = (code) => CAPTCHA_ERRORS[code] || null;

let loading = null;

// Carrega api.js uma única vez. Rejeita se o script não chegar (bloqueador, rede, CSP) em 15 s.
export function loadTurnstile(win = window, doc = document) {
  if (win.turnstile) return Promise.resolve(win.turnstile);
  if (loading) return loading;
  loading = new Promise((resolve, reject) => {
    const s = doc.createElement('script');
    s.src = TURNSTILE_SRC; s.async = true; s.defer = true;
    const timer = setTimeout(() => { fail(); }, 15000);
    const fail = () => { clearTimeout(timer); loading = null; s.remove(); reject(new Error('turnstile')); };
    s.onload = () => { clearTimeout(timer); win.turnstile ? resolve(win.turnstile) : fail(); };
    s.onerror = fail;
    doc.head.appendChild(s);
  });
  return loading;
}
