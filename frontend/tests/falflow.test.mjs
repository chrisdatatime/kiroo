import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { STYLES, draftErrors, createPayload, falActive, falView, gallery, newRequestId, downloadUrl, falSummaryRows } from '../src/ui/falFlow.js';
import { deriveStage } from '../src/engine/adapter.js';
import { summaryRows, credits } from '../src/ui/nextVideo.js';

// estilos e validação: foto + Escuro/Claro, nome e descrição NÃO são obrigatórios
assert.deepEqual(STYLES.map((s) => s.id), ['dark', 'light']);
assert.deepEqual(draftErrors({ style: 'dark', file: { name: 'a.PNG' } }), []);
assert.deepEqual(draftErrors({ style: null, file: null }), ['a foto do produto', 'o estilo (Escuro ou Claro)']);
assert.deepEqual(draftErrors({ style: 'light', file: { name: 'v.mp4' } }), ['uma foto JPG, PNG ou WEBP']);
const body = createPayload({ style: 'dark', file: { name: 'a.png', data: 'data:x' }, requestId: 'abc12345' });
assert.deepEqual(body, { style: 'dark', client_request_id: 'abc12345', files: [{ name: 'a.png', data: 'data:x' }] });   // sem nome
assert.equal(createPayload({ style: 'dark', file: { name: 'a.png', data: 'd' }, requestId: 'abc12345', name: ' Copo ' }).name, 'Copo');

// id do cliente: UUID por envio; sem crypto, cai para um id aleatório de tamanho aceito pelo servidor (8 a 64)
assert.equal(newRequestId(() => 'u-1'), 'u-1');
assert.match(newRequestId(() => null), /^[A-Za-z0-9_-]{8,64}$/);

// o fluxo só aparece com o motor fal.ai; produção Gemini continua no fluxo antigo
const S = { settings: { video_engine: 'fal' } };
assert.equal(falActive(S, null, true), true);
assert.equal(falActive({ settings: { video_engine: 'gemini' } }, null, true), false);
assert.equal(falActive(S, { engine: 'gemini' }, false), false);
assert.equal(falActive({ settings: { video_engine: 'gemini' } }, { engine: 'fal' }, false), true);
assert.equal(falView({ engine: 'gemini' }), null);

// fases mostradas ao cliente; pausa de entrega vira "em finalização", sem detalhe técnico
const P = (o) => ({ engine: 'fal', status: 'producing', fal: {}, delivery: {}, ...o });
assert.equal(falView(P({})).phase, 'working');
assert.equal(falView(P({ fal: { remote_status: 'IN_QUEUE', queue_position: 3 } })).queuePosition, 3);
assert.equal(falView(P({ status: 'editing' })).phase, 'composing');
const fin = falView(P({ status: 'paused', pause_code: 'delivery_incomplete', fal: { finalizing: true } }));
assert.equal(fin.phase, 'finalizing'); assert.equal(fin.label, 'Em finalização'); assert.equal(fin.busy, false);
assert.ok(!JSON.stringify(fin).includes('delivery_incomplete'));
assert.equal(falView(P({ status: 'awaiting_final_review' })).phase, 'ready');
assert.equal(falView(P({ status: 'completed' })).phase, 'done');
assert.equal(falView(P({ status: 'failed', ended: 'failed' })).phase, 'failed');
assert.equal(falView(P({ status: 'cancelled', ended: 'cancelled' })).phase, 'cancelled');

// a esteira existente entende a produção fal (sem cenas): mesmas etapas de entrega
assert.equal(deriveStage(P({ status: 'producing' })), 'img_gerando');
assert.equal(deriveStage(P({ status: 'editing' })), 'montando');
assert.equal(deriveStage(P({ status: 'awaiting_final_review' })), 'entrega');
assert.equal(deriveStage(P({ status: 'completed' })), 'exportado');
assert.equal(deriveStage(P({ status: 'paused', fal: { finalizing: true } })), 'img_gerando');
assert.equal(deriveStage(P({ status: 'cancelled', ended: 'cancelled' })), 'cancelada');

// galeria: vídeo + 3 fotos com rótulo e download individual (?download=1)
const done = P({ status: 'awaiting_final_review', delivery: { 'final.mp4': '/media/p/delivery/final.mp4', 'cover.jpg': '/media/p/delivery/cover.jpg', 'caption.txt': '/media/p/delivery/caption.txt' },
  fal: { delivery_status: 'complete', description: 'Desc', narration_text: 'Texto', images: [
    { role: 'hero', label: 'Hero Shot', file: 'product_image_01.jpg', url: '/media/p/delivery/product_image_01.jpg' },
    { role: 'lifestyle', label: 'Lifestyle', file: 'product_image_02.jpg', url: '/media/p/delivery/product_image_02.jpg' },
    { role: 'details', label: 'Detalhes', file: 'product_image_03.jpg', url: '/media/p/delivery/product_image_03.jpg' }] } });
const g = gallery(done);
assert.deepEqual(g.images.map((i) => i.label), ['Hero Shot', 'Lifestyle', 'Detalhes']);
assert.equal(g.images[1].download, '/media/p/delivery/product_image_02.jpg?download=1');
assert.equal(g.video.download, '/media/p/delivery/final.mp4?download=1');
assert.equal(g.description, 'Desc'); assert.equal(g.narrationText, 'Texto'); assert.equal(g.partial, false);
assert.equal(downloadUrl('/m?x=1'), '/m?x=1&download=1'); assert.equal(downloadUrl(null), null);
assert.equal(gallery({ engine: 'gemini' }), null);
// entrega incompleta não publica nada: sem links
const inc = gallery(P({ status: 'paused', fal: { finalizing: true, missing_images: ['details'], delivery_status: 'incomplete', images: [{ role: 'hero', label: 'Hero Shot', file: 'x', url: null }] } }));
assert.equal(inc.video, null); assert.equal(inc.images[0].download, null);

// "Seu próximo vídeo" no motor fal.ai: estilo e o que vem no pacote, sem cenas nem ajustes
const sm = { engine: 'fal', style: 'light', product: '', total_credits: '32,4', total_brl: null, balance: '500', balance_after: '467,6', exempt: false };
const rows = Object.fromEntries(falSummaryRows(sm, credits));
assert.equal(rows['Estilo'], 'Claro'); assert.ok(!('Cenas' in rows) && !('Ajustes incluídos por cena' in rows));
assert.match(rows['O que você recebe'], /3 fotos publicitárias/);
assert.equal(rows['Custo total autorizado'], '32,4 créditos');
assert.ok(Object.fromEntries(summaryRows({ ...sm, format: '9:16', scenes: 3, included_adjustments_per_scene: 1, product: 'X' }))['Estilo'] === 'Claro');

// o cliente nunca vê modelo, fila técnica ou "fal.ai" nas telas do fluxo
const read = (f) => readFileSync(new URL('../src/' + f, import.meta.url), 'utf8');
const ui = read('ui/FalWindow.jsx');
assert.ok(!/fal\.ai|workflow|queue\.fal/i.test(ui.replace(/\/\/.*$/gm, '')), 'a tela do fluxo cita o fornecedor');
console.log('falflow.test ok');
