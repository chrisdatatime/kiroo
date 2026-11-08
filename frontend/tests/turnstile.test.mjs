import assert from 'node:assert/strict';
import { CAPTCHA_ERRORS, CAPTCHA_MODES, TURNSTILE_SRC, captchaMessage, captchaNeeded, loadTurnstile } from '../src/ui/turnstile.js';

// Só pede captcha quando o servidor entregou a site key, e só nas 4 telas que enviam o token
assert.equal(captchaNeeded({ turnstile: null }, 'login'), false);
assert.equal(captchaNeeded({}, 'login'), false);
assert.equal(captchaNeeded(undefined, 'login'), false);
for (const m of ['login', 'signup', 'forgot', 'verify']) assert.equal(captchaNeeded({ turnstile: '0x4AAA' }, m), true, m);
for (const m of ['reset', 'sent']) assert.equal(captchaNeeded({ turnstile: '0x4AAA' }, m), false, m);
assert.deepEqual(CAPTCHA_MODES, ['login', 'signup', 'forgot', 'verify']);

// Mensagens em PT-BR para os códigos estáveis do servidor e do cliente
for (const c of ['captcha_invalido', 'captcha_indisponivel', 'captcha_script', 'captcha_widget']) assert.match(captchaMessage(c), /verificação de segurança/);
assert.equal(captchaMessage('outro'), null);
assert.equal(captchaMessage(undefined), null);
assert.ok(Object.keys(CAPTCHA_ERRORS).length === 4);

// O script vem só da Cloudflare, por HTTPS, sem token nem chave na URL
assert.ok(TURNSTILE_SRC.startsWith('https://challenges.cloudflare.com/turnstile/v0/api.js'));

// Já carregado: reaproveita; script que não chega: rejeita e deixa tentar de novo
const ts = {};
assert.equal(await loadTurnstile({ turnstile: ts }, {}), ts);
const added = [];
const doc = { createElement: () => ({ remove() {} }), head: { appendChild: (s) => { added.push(s); queueMicrotask(() => s.onerror()); } } };
await assert.rejects(loadTurnstile({}, doc), /turnstile/);
await assert.rejects(loadTurnstile({}, doc), /turnstile/);
assert.equal(added.length, 2);
assert.equal(added[0].src, TURNSTILE_SRC);

console.log('ok turnstile');
