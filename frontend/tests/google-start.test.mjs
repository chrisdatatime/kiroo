import assert from 'node:assert/strict';
import { googleStart, GOOGLE_ERRORS, GOOGLE_START } from '../src/ui/googleStart.js';

// Entrar: sempre o início simples, sem convite nem intenção de cadastro
assert.deepEqual(googleStart({ mode: 'login', signup: 'invite', invite: 'X', consent: true }), { href: GOOGLE_START, ready: true, need: null });

// Criar conta com convite: exige o código e o aceite, e leva os dois
let g = googleStart({ mode: 'signup', signup: 'invite', invite: '', consent: true });
assert.equal(g.ready, false); assert.equal(g.href, null); assert.match(g.need, /convite/);
g = googleStart({ mode: 'signup', signup: 'invite', invite: ' KIROO-AB12-CD34-EF56 ', consent: false });
assert.equal(g.ready, false); assert.match(g.need, /Termos/);
g = googleStart({ mode: 'signup', signup: 'invite', invite: ' KIROO-AB12-CD34-EF56 ', consent: true });
assert.equal(g.ready, true);
const u = new URL(g.href, 'https://staging.kiroo.app');
assert.equal(u.pathname, GOOGLE_START);
assert.equal(u.searchParams.get('intent'), 'signup');
assert.equal(u.searchParams.get('consent'), '1');
assert.equal(u.searchParams.get('invite'), 'KIROO-AB12-CD34-EF56');

// Cadastro aberto: sem convite na URL
g = googleStart({ mode: 'signup', signup: 'open', invite: 'ignorado', consent: true });
assert.equal(new URL(g.href, 'https://x').searchParams.has('invite'), false);

// Todo código de erro do servidor tem mensagem
for (const code of ['google_off', 'google_cancel', 'google_state', 'google_failed', 'google_unverified', 'google_consent',
  'google_other', 'google_throttled', 'convite', 'convite_invalido']) assert.ok(GOOGLE_ERRORS[code], code);

console.log('ok google-start');
