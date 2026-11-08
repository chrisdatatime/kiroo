// Cliente da API do motor (servidor Python). Sessão por cookie HttpOnly; ações levam o token CSRF da sessão.
let csrf = null;
let onLoggedOut = () => {};

export class AuthRequired extends Error {}

export function setLoggedOutHandler(fn) { onLoggedOut = fn; }

async function parse(r) {
  const d = await r.json().catch(() => ({}));
  if (r.status === 401) { csrf = null; onLoggedOut(); throw new AuthRequired(d.error || 'Entre na sua conta'); }
  if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
  return d;
}

export async function me() {
  const r = await fetch('/api/me', { credentials: 'same-origin' });
  const d = await parse(r);
  csrf = d.csrf;
  return d;
}

export async function getJSON(path) {
  return parse(await fetch(path, { credentials: 'same-origin' }));
}

export async function post(path, body = {}, retried = false) {
  if (!csrf) await me();
  const r = await fetch(path, { method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-Studio-Token': csrf }, body: JSON.stringify(body) });
  if (r.status === 403 && !retried) {
    const d = await r.clone().json().catch(() => ({}));
    if (/token/i.test(d.error || '')) { csrf = null; return post(path, body, true); }  // sessão renovada
  }
  return parse(r);
}

// Cadastro e login: cabeçalho próprio do cliente (o servidor recusa sem ele).
export async function auth(action, body = {}) {
  const r = await fetch('/api/auth/' + action, { method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-Studio-Client': 'game' }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(d.error || `HTTP ${r.status}`), { code: d.code });   // code: erro estável (captcha_*)
  if (action === 'logout') csrf = null;
  return d;
}

// O que a tela de acesso pode oferecer: cadastro ('closed' | 'invite' | 'open'), Google, envio de e-mail. Pública.
export async function authConfig() {
  const r = await fetch('/api/config', { credentials: 'same-origin' });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export function readFile(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result);
    fr.onerror = () => reject(new Error('Não foi possível ler ' + file.name));
    fr.readAsDataURL(file);
  });
}
