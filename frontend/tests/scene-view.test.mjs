// Cena bloqueada só pode ser aprovada se a tentativa atual saiu (bug: "Aprovar cena" numa cena sem imagem).
import assert from 'node:assert/strict';
import { sceneView, deriveStage } from '../src/engine/adapter.js';

const base = { idx: 1, title: 'c', motion: '', target_duration_s: 4, image_attempts: 3, video_attempts: 0, image: null, video: null, approved_image: null };
const failed = { id: 'a', status: 'failed', url: null, error: 'timeout' };
const ok = { id: 'b', status: 'succeeded', url: '/media/x.png' };

assert.equal(sceneView({ ...base, status: 'blocked', image: failed }).img, 'falhou');
assert.equal(sceneView({ ...base, status: 'blocked', image: null }).img, 'falhou');
assert.equal(sceneView({ ...base, status: 'blocked', image: ok }).img, 'pronta');
assert.equal(sceneView({ ...base, status: 'blocked', approved_image: 'b', image: ok, video: failed }).vid, 'falhou');
assert.equal(sceneView({ ...base, status: 'blocked', approved_image: 'b', image: ok, video: ok }).vid, 'pronta');
// Cena que falhou leva para a revisão (onde aparece "Tentar de novo"), não para "gerando".
assert.equal(deriveStage({ status: 'producing', creative: {}, go_ahead: 'images', scenes: [{ ...base, status: 'blocked', image: failed }] }), 'img_revisao');
console.log('scene-view ok');
