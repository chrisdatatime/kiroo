// Abre o app logado num Chrome headless (protocolo DevTools, sem dependências) e falha se a CSP bloquear algo.
// Verifica: mundo Phaser carregado (canvas + WebGL), nenhum "Content Security Policy"/"Refused to" no console, e que a
// política permite o que o Phaser usa (blob:, data:, Worker blob:, imagem blob:).
// Uso: node scripts/csp-check.mjs   (precisa de frontend/dist construído e de Chrome/Edge instalado)
//   env: CHROME=<caminho do chrome>, PYTHON=<python do projeto>, CSP_PORT=8794
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('..', import.meta.url)));
const PORT = Number(process.env.CSP_PORT || 8794), DEBUG = PORT + 100;
const EMAIL = 'csp@kiroo.test', PASSWORD = 'senha-forte-123';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const first = (list) => list.find((p) => p && existsSync(p));
const PY = process.env.PYTHON || first([join(ROOT, '.venv/Scripts/python.exe'), join(ROOT, '.venv/bin/python')]) || 'python';
const CHROME = process.env.CHROME || first(['C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', '/usr/bin/google-chrome', '/usr/bin/chromium',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome']);
if (!CHROME) { console.error('Chrome/Edge não encontrado (defina CHROME).'); process.exit(2); }
if (!existsSync(join(ROOT, 'frontend/dist/index.html'))) { console.error('frontend/dist ausente: rode npm run build.'); process.exit(2); }

const data = mkdtempSync(join(tmpdir(), 'kiroo-csp-'));
const profile = mkdtempSync(join(tmpdir(), 'kiroo-chrome-'));
const seed = spawnSync(PY, ['-c', `from pathlib import Path
from studio.db import Database
from studio.accounts import Accounts
db = Database(Path(r'${data}') / 'studio.sqlite3'); Accounts(db).create_user('${EMAIL}', '${PASSWORD}', 'CSP', verified=True); db.close()`],
  { cwd: ROOT, env: { ...process.env, PYTHONPATH: join(ROOT, 'src') }, encoding: 'utf8' });
if (seed.status !== 0) { console.error(seed.stderr); process.exit(2); }

const server = spawn(PY, ['-m', 'studio', 'ui', '--no-browser'], { cwd: ROOT, stdio: 'ignore',
  env: { ...process.env, STUDIO_DATA_DIR: data, STUDIO_PORT: String(PORT), STUDIO_MODE: 'simulated' } });
const chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${DEBUG}`, `--user-data-dir=${profile}`,
  '--no-first-run', '--no-default-browser-check', '--enable-unsafe-swiftshader', '--use-angle=swiftshader',
  '--ignore-gpu-blocklist', '--window-size=1280,800', 'about:blank'], { stdio: 'ignore' });

function cleanup() {
  try { chrome.kill(); } catch {} try { server.kill(); } catch {}
  setTimeout(() => { for (const d of [data, profile]) try { rmSync(d, { recursive: true, force: true }); } catch {} }, 1500);
}

async function waitHttp(url, tries = 60) {
  for (let i = 0; i < tries; i++) { try { const r = await fetch(url); if (r.ok) return r; } catch {} await sleep(500); }
  throw new Error('sem resposta de ' + url);
}

const problems = [], seen = [];
let probingInline = false;   // a sonda de script inline PROVOCA uma violação de propósito
const isCsp = (t) => /Content Security Policy|Refused to|violates the following/i.test(t);

try {
  await waitHttp(`http://127.0.0.1:${PORT}/healthz`);
  await waitHttp(`http://127.0.0.1:${DEBUG}/json/version`);
  const targets = await (await fetch(`http://127.0.0.1:${DEBUG}/json/list`)).json();
  const page = targets.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  let id = 0; const pending = new Map();
  const send = (method, params = {}) => new Promise((res, rej) => { const n = ++id; pending.set(n, { res, rej }); ws.send(JSON.stringify({ id: n, method, params })); });
  const evalJs = async (expr) => (await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })).result?.value;
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) { const p = pending.get(d.id); pending.delete(d.id); d.error ? p.rej(new Error(d.error.message)) : p.res(d.result); return; }
    if (d.method === 'Log.entryAdded') { const e = d.params.entry; seen.push(`[log ${e.level}] ${e.text}`); if ((isCsp(e.text) || e.source === 'security') && !probingInline) problems.push(`log: ${e.text}`); }
    if (d.method === 'Runtime.consoleAPICalled') {
      const text = d.params.args.map((a) => a.value ?? a.description ?? '').join(' ');
      seen.push(`[console.${d.params.type}] ${text}`); if (isCsp(text)) problems.push(`console: ${text}`);
    }
    if (d.method === 'Runtime.exceptionThrown') {
      const text = d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text;
      seen.push(`[exception] ${text}`); if (isCsp(text)) problems.push(`exceção: ${text}`);
    }
    if (d.method === 'Network.loadingFailed' && /csp/i.test(d.params.blockedReason || '')) problems.push(`rede bloqueada por CSP: ${d.params.requestId}`);
  };
  for (const m of ['Log.enable', 'Runtime.enable', 'Network.enable', 'Page.enable']) await send(m);

  const base = `http://127.0.0.1:${PORT}`;
  await send('Page.navigate', { url: base + '/' });
  await sleep(1500);
  const login = await evalJs(`fetch('/api/auth/login', {method:'POST', credentials:'same-origin',
    headers:{'Content-Type':'application/json','X-Studio-Client':'game'}, body: JSON.stringify({email:'${EMAIL}', password:'${PASSWORD}'})}).then(r=>r.status)`);
  if (login !== 200) throw new Error('login falhou: ' + login);
  await evalJs(`localStorage.setItem('bc.view', JSON.stringify('escritorio')); localStorage.setItem('bc.tutDone', 'true')`);  // abre direto o escritório (mundo Phaser)
  await send('Page.navigate', { url: base + '/?world=phaser' });   // o padrão ainda é o mundo em canvas 2D; o Phaser é opt-in

  // o mundo Phaser: canvas com WebGL e pelo menos alguns quadros desenhados
  let world = null;
  for (let i = 0; i < 60 && !world; i++) {
    await sleep(1000);
    world = await evalJs(`(() => {
      const kind = (c) => { const g = c.getContext('webgl2') || c.getContext('webgl'); if (g) return { context: (typeof WebGL2RenderingContext !== 'undefined' && g instanceof WebGL2RenderingContext) ? 'webgl2' : 'webgl', lost: g.isContextLost(), renderer: g.getParameter(g.RENDERER) }; return { context: c.getContext('2d') ? '2d' : '?' }; };
      const all = [...document.querySelectorAll('canvas')].filter(x => x.width >= 300 && x.height >= 200).map(c => ({ w: c.width, h: c.height, parent: c.parentElement?.id || c.parentElement?.className || '', ...kind(c) }));
      return all.length ? { canvases: all, webgl: all.some(c => c.context.startsWith('webgl') && !c.lost) } : null; })()`);
  }
  await sleep(2000);
  if (!world) {
    const dbg = await evalJs(`JSON.stringify({url: location.href, canvases: [...document.querySelectorAll('canvas')].map(c => [c.width, c.height]), text: document.body.innerText.slice(0, 300)})`);
    problems.push('o canvas do mundo Phaser não apareceu em 60 s: ' + dbg);
  }
  else if (!world.webgl) problems.push('o canvas do Phaser não está em WebGL (caiu para canvas 2D?); veja a sonda webgl_available');
  console.log('mundo:', JSON.stringify(world));

  // a política deixa passar o que o Phaser usa? (cada item precisa dar certo SEM violação)
  probingInline = true;
  const probes = await evalJs(`(async () => {
    const out = {};
    out.webgl_available = !!document.createElement('canvas').getContext('webgl');
    const blob = new Blob(['x'], {type:'text/plain'}), burl = URL.createObjectURL(blob);
    out.fetch_blob = await fetch(burl).then(r => r.text()).then(t => t === 'x').catch(() => false);
    out.fetch_data = await fetch('data:text/plain;base64,eA==').then(r => r.text()).then(t => t === 'x').catch(() => false);
    out.worker_blob = await new Promise((res) => { try { const w = new Worker(URL.createObjectURL(new Blob(['postMessage(1)'], {type:'text/javascript'})));
      w.onmessage = () => { w.terminate(); res(true); }; w.onerror = () => res(false); setTimeout(() => res(false), 4000); } catch { res(false); } });
    const png = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==';
    out.img_data = await new Promise((res) => { const i = new Image(); i.onload = () => res(true); i.onerror = () => res(false); i.src = png; });
    const pb = await (await fetch(png)).blob();
    out.img_blob = await new Promise((res) => { const i = new Image(); i.onload = () => res(true); i.onerror = () => res(false); i.src = URL.createObjectURL(pb); });
    window.__probing = true; out.inline_script_blocked = await new Promise((res) => { window.__x = 0; const s = document.createElement('script'); s.textContent = 'window.__x = 1';
      document.head.appendChild(s); setTimeout(() => res(window.__x === 0), 300); });
    return out; })()`);
  await sleep(500);
  probingInline = false;
  console.log('sondas:', JSON.stringify(probes));
  for (const [k, v] of Object.entries(probes || {})) if (!v) problems.push(`sonda "${k}" falhou`);
  await sleep(1000);
  ws.close();
} catch (e) {
  problems.push('erro do teste: ' + (e.stack || e));
}
cleanup();
if (seen.length) console.log('--- mensagens do console (' + seen.length + ') ---\n' + seen.slice(0, 15).join('\n'));
if (problems.length) { console.error('\nFALHOU:\n- ' + problems.map((x) => x.slice(0, 220)).join('\n- ')); process.exit(1); }
console.log('\nOK: mundo Phaser carregou em WebGL, sem violações de CSP; blob:/data:/Worker liberados e script inline bloqueado.');
process.exit(0);
