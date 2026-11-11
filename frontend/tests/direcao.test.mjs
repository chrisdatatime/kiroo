// Etapa Direção: caminho das fotos, SVG de fallback, pedidos livres e painel lateral.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { FORMAT_IDS, formatPhotoUrl, formatArt, splitRequests, joinRequests, summaryRows } from '../src/ui/direcao.js';

assert.equal(formatPhotoUrl('hands_only', '/'), '/assets/direcao/hands_only.webp');
assert.equal(formatPhotoUrl('presenter', '/app'), '/app/assets/direcao/presenter.webp');
assert.equal(formatPhotoUrl('../x'), null);
assert.deepEqual(FORMAT_IDS, ['product_only', 'hands_only', 'presenter']);
assert.deepEqual(formatArt('product_only'), { hand: false, person: false });
assert.deepEqual(formatArt('presenter'), { hand: true, person: true });

assert.deepEqual(splitRequests(' a ; ;b'), ['a', 'b']);
assert.equal(joinRequests('a', ' b;c '), 'a; b,c');
assert.equal(joinRequests('a', '  '), 'a');

const pres = { hands_only: { label: 'Somente mãos' } };
let rows = summaryRows(pres, { presentation: 'hands_only', details_text: '' });
assert.deepEqual(rows.map((r) => r.k), ['Formato', 'Áudio', 'Duração']);
rows = summaryRows(pres, { presentation: 'hands_only', details_text: 'câmera próxima' });
assert.deepEqual(rows.map((r) => r.k), ['Formato', 'Pedidos', 'Áudio', 'Duração']);
// produção antiga com campos salvos: não aparecem no painel
rows = summaryRows(pres, { presentation: 'hands_only', environment: 'cozinha', tone: 'leve', proposal: 'practice', details: ['luz_natural'], details_text: '' });
assert.equal(rows.some((r) => ['Ambiente', 'Proposta', 'Tom'].includes(r.k)), false);

// a aba não oferece mais as opções removidas nem cita produtos de exemplo
const tab = fs.readFileSync(new URL('../src/ui/ProdWindow.jsx', import.meta.url), 'utf8');
for (const t of ['Onde acontece', 'Ajustes rápidos', 'sugerida:', 'Tom</', 'Restaurar proposta']) assert.equal(tab.includes(t), false, t);
for (const f of ['src/ui/ProdWindow.jsx', 'src/App.jsx', 'src/ui/bits.jsx', 'src/ui/Training.jsx', 'src/ui/direcao.js']) {
  const src = fs.readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');
  assert.equal(/Stanley|canudo/i.test(src), false, `${f}: exemplo de copo/Stanley`);
}
console.log('ok direcao');
