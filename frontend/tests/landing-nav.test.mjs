// Navegação da logo e do "Voltar para o início" no app: com STUDIO_LANDING_HOST (landing_url em /api/config) viram <a href> de
// página inteira para a landing e o app nunca mostra a Landing interna; sem a URL, o comportamento antigo continua.
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { renderToStaticMarkup } from 'react-dom/server';
import React from 'react';

globalThis.window = { location: { search: '', pathname: '/login' } };   // Auth lê window.location.search ao renderizar

const front = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const vite = await createServer({ root: front, configFile: path.join(front, 'vite.config.js'), logLevel: 'error', server: { middlewareMode: true, hmr: false }, appType: 'custom',
  optimizeDeps: { noDiscovery: true, include: [] } });
try {
  const { accessScreen } = await vite.ssrLoadModule('/src/ui/accessScreen.js');
  const URL_ = 'https://kiroo.example';

  // Landing interna só com a URL vazia; com URL, qualquer caminho sem sessão cai no login.
  assert.deepEqual(accessScreen({ entry: null, landing: '', resetToken: null }), { kind: 'landing' });
  assert.equal(accessScreen({ entry: null, landing: null, resetToken: null }).kind, 'wait');   // config ainda não chegou: nada de flash
  assert.deepEqual(accessScreen({ entry: null, landing: URL_, resetToken: null }), { kind: 'auth', entry: 'login', landingUrl: URL_ });
  assert.equal(accessScreen({ entry: 'login', landing: URL_, resetToken: null }).kind, 'auth');
  assert.equal(accessScreen({ entry: 'login', landing: '', resetToken: null }).landingUrl, '');
  assert.equal(accessScreen({ entry: null, landing: '', resetToken: 'tok' }).kind, 'auth');
  for (const landing of ['', null, URL_]) assert.notEqual(accessScreen({ entry: 'signup', landing, resetToken: null }).kind, 'landing');
  assert.equal(accessScreen({ entry: null, landing: URL_, resetToken: null }).kind === 'landing', false);

  // Marcação da tela de acesso.
  const { default: AuthScreen } = await vite.ssrLoadModule('/src/ui/Auth.jsx');
  const render = (props) => renderToStaticMarkup(React.createElement(AuthScreen, { onDone() {}, initialMode: 'login', ...props }));

  let html = render({ landingUrl: URL_, onBack() {} });
  assert.match(html, /<a class="au-brand" href="https:\/\/kiroo\.example" aria-label="Kiroo: voltar para o início">/);
  assert.match(html, /<a [^>]*href="https:\/\/kiroo\.example"[^>]*>(?:<svg.*?<\/svg>)?Início<\/a>/);
  assert.doesNotMatch(html, /<button[^>]*au-brand/);
  assert.doesNotMatch(html, /<button[^>]*>(?:<svg.*?<\/svg>)?Início<\/button>/);

  html = render({ landingUrl: '', onBack() {} });   // sem URL: botões de sempre (trocam o estado do SPA)
  assert.match(html, /<button type="button" class="au-brand"/);
  assert.match(html, /<button[^>]*>(?:<svg.*?<\/svg>)?Início<\/button>/);
  assert.doesNotMatch(html, /kiroo\.example/);

  html = render({ landingUrl: URL_, resetToken: 'tok', initialMode: 'reset' });   // reset: logo sem link, como antes
  assert.doesNotMatch(html, /kiroo\.example/);
  console.log('ok: navegação da logo / voltar para o início');
} finally {
  await vite.close();
}
