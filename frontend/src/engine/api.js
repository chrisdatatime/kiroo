// Cliente da API do motor (servidor Python). Sessão por cookie HttpOnly; ações levam o token CSRF da sessão.
let csrf = null;
let onLoggedOut = () => {};

export class AuthRequired extends Error {}

// Id persistente deste navegador (anti-abuso do bônus de boas-vindas: um bônus por dispositivo). Fica no localStorage e
// num cookie `kiroo_dev` (vai junto no retorno do Google). Não identifica a pessoa: o servidor guarda só o hash.
const DEVICE_KEY = 'kiroo_dev';
export function deviceId() {
  let id = null;
  try { id = localStorage.getItem(DEVICE_KEY); } catch { /* sem armazenamento */ }
  if (!/^[A-Za-z0-9_-]{16,64}$/.test(id || '')) {
    const rnd = (globalThis.crypto && crypto.randomUUID) ? crypto.randomUUID().replace(/-/g, '')
      : Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join('');
    id = rnd;
    try { localStorage.setItem(DEVICE_KEY, id); } catch { /* sem armazenamento */ }
  }
  try { document.cookie = `${DEVICE_KEY}=${id}; Path=/; Max-Age=63072000; SameSite=Lax${location.protocol === 'https:' ? '; Secure' : ''}`; } catch { /* SSR/teste */ }
  return id;
}

export function setLoggedOutHandler(fn) { onLoggedOut = fn; }

async function parse(r) {
  const d = await r.json().catch(() => ({}));
  if (r.status === 401) { csrf = null; onLoggedOut(); throw new AuthRequired(d.error || 'Entre na sua conta'); }
  // `data` leva a resposta inteira (ex.: saldo, custo e faltantes de um 402) para a tela mostrar a conta.
  if (!r.ok) throw Object.assign(new Error(d.error || `HTTP ${r.status}`), { data: d, status: r.status });
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
    headers: { 'Content-Type': 'application/json', 'X-Studio-Client': 'game', 'X-Kiroo-Device': deviceId() }, body: JSON.stringify(body) });
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
