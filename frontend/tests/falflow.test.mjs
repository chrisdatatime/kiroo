import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { STYLES, availableStyles, effectiveStyle, draftErrors, createPayload, falActive, falStatus, falStations, falStepIndex, falAgentStatus, startFal, continueFal, offerFor, createLabel, RECEIVE_LINE, FRIENDLY_FALLBACK, EST_WORKFLOW_S, endedLabel, gallery, newRequestId, downloadUrl, falSummaryRows } from '../src/ui/falFlow.js';
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

// só o Claro está liberado (settings.fal_styles): sem seletor, e o envio é sempre o Claro
const only = { settings: { fal_styles: [{ id: 'light', label: 'Claro' }] } };
assert.deepEqual(availableStyles(only).map((s) => s.id), ['light']);
assert.deepEqual(availableStyles({}).map((s) => s.id), ['light']);                      // sem a lista do servidor: Claro
assert.equal(effectiveStyle(only, null), 'light'); assert.equal(effectiveStyle(only, 'dark'), 'light');
assert.deepEqual(draftErrors({ style: effectiveStyle(only, null), file: { name: 'a.png' } }), []);
// com o Escuro ligado no servidor volta o seletor, e a escolha vale
const both = { settings: { fal_styles: [{ id: 'dark', label: 'Escuro' }, { id: 'light', label: 'Claro' }] } };
assert.deepEqual(availableStyles(both).map((s) => s.id), ['dark', 'light']);
assert.equal(effectiveStyle(both, 'dark'), 'dark'); assert.equal(effectiveStyle(both, null), null);

// id do cliente: UUID por envio; sem crypto, cai para um id aleatório de tamanho aceito pelo servidor (8 a 64)
assert.equal(newRequestId(() => 'u-1'), 'u-1');
assert.match(newRequestId(() => null), /^[A-Za-z0-9_-]{8,64}$/);

// o fluxo só aparece com o motor fal.ai; produção Gemini continua no fluxo antigo
const S = { settings: { video_engine: 'fal' } };
assert.equal(falActive(S, null, true), true);
assert.equal(falActive({ settings: { video_engine: 'gemini' } }, null, true), false);
assert.equal(falActive(S, { engine: 'gemini' }, false), false);
assert.equal(falActive({ settings: { video_engine: 'gemini' } }, { engine: 'fal' }, false), true);
assert.equal(falStatus({ engine: 'gemini' }), null);

// status SEMPRE do servidor: nada de "Preparando"/"Criando" antes do /run aceito
const P = (o) => ({ engine: 'fal', status: 'producing', running: true, fal: {}, delivery: {}, ...o });
const T0 = Date.parse('2026-11-14T12:00:00Z');
const at = (s) => T0 + s * 1000;
const sent = { submitted_at: '2026-11-14T12:00:00+00:00', remote_status: 'IN_PROGRESS' };
const waiting = falStatus(P({ status: 'received', running: false }));
assert.equal(waiting.kind, 'waiting'); assert.equal(waiting.label, 'Aguardando você'); assert.equal(waiting.action, 'start');
assert.ok(!/Preparando|Criando/.test(JSON.stringify(waiting)));
assert.equal(falStatus(P({ status: 'validated', running: false })).label, 'Aguardando você');          // criada, sem /run
assert.equal(falStepIndex(P({ status: 'validated', running: false })), null);
assert.equal(falStatus(P({ status: 'received', running: true })).kind, 'running');                      // /run aceito
assert.equal(falStatus(P({ status: 'awaiting_references', running: false, reason: 'Envie outra foto.' })).text, 'Envie outra foto.');
// pausas: limite mensal com motivo claro; entrega em finalização sem detalhe técnico
const cap = falStatus(P({ status: 'paused', pause_code: 'monthly_cap', running: false }));
assert.equal(cap.label, 'Pausada: limite mensal atingido'); assert.match(cap.text, /Nada foi cobrado/);
assert.equal(falStatus(P({ status: 'paused', pause_code: 'paid_gate:platform_cap', running: false, reason: 'Limite do Kiroo.' })).text, 'Limite do Kiroo.');
assert.equal(falStatus(P({ status: 'paused', pause_code: 'credits_insufficient', running: false })).label, 'Pausada: saldo insuficiente');
const fin = falStatus(P({ status: 'paused', pause_code: 'delivery_incomplete', running: false, fal: { finalizing: true } }));
assert.equal(fin.label, 'Em finalização'); assert.ok(!JSON.stringify(fin).includes('delivery_incomplete'));
assert.equal(falStatus(P({ status: 'failed', ended: 'failed' })).text, 'Não deu certo. Nada foi cobrado.');
assert.equal(falStatus(P({ status: 'awaiting_final_review' })).label, 'Pronto');
assert.equal(falStatus(P({ status: 'completed' })).label, 'Pronto');
assert.equal(falStatus(P({ status: 'cancelled', ended: 'cancelled' })).kind, 'cancelled');
const part = falStatus(P({ status: 'cancelled', ended: 'cancelled', fal: { delivery_status: 'incomplete' } }));
assert.equal(part.kind, 'partial'); assert.equal(part.label, 'Entrega parcial');

// esteira: 6 etapas, ESTIMADAS pelo tempo desde o envio; EDIÇÃO só conclui com a entrega validada
const belt = (o, s) => falStations(P(o), at(s)).stations;
assert.deepEqual(belt({ fal: sent }, 0).map((x) => x.title), ['PLANEJAMENTO', 'ROTEIRO', 'IMAGENS', 'VÍDEOS', 'REVISÃO', 'EDIÇÃO']);
assert.deepEqual(belt({ fal: sent }, 0).map((x) => x.agent), ['nina', 'theo', 'iris', 'lia', 'rui', 'beto']);
assert.equal(belt({ fal: { submitted_at: sent.submitted_at, remote_status: 'IN_QUEUE' } }, 10).find((x) => x.current).id, 'planejamento');
assert.equal(belt({ fal: {} }, 0).find((x) => x.current).id, 'planejamento');                        // rodando, ainda sem envio
assert.equal(belt({ fal: sent }, 10).find((x) => x.current).id, 'roteiro');
assert.equal(belt({ fal: sent }, EST_WORKFLOW_S * 0.2).find((x) => x.current).id, 'imagens');
assert.equal(belt({ fal: sent }, EST_WORKFLOW_S * 0.5).find((x) => x.current).id, 'videos');
assert.equal(belt({ fal: sent }, EST_WORKFLOW_S * 0.9).find((x) => x.current).id, 'revisao');
const late = falStations(P({ fal: sent }), at(EST_WORKFLOW_S * 50));                                  // demorou muito mais
assert.equal(late.current, 'revisao'); assert.equal(late.stations[5].state, 'pending'); assert.ok(late.progress <= 90);
assert.equal(falStatus(P({ fal: sent }), at(10)).estimated, true);
const edit = falStations(P({ status: 'editing', fal: sent }), at(60));
assert.equal(edit.current, 'edicao'); assert.equal(edit.stations[5].state, 'active'); assert.ok(edit.progress < 100);
const ready = falStations(P({ status: 'awaiting_final_review', fal: sent }), at(60));
assert.ok(ready.stations.every((x) => x.state === 'done')); assert.equal(ready.progress, 100);
const wait2 = falStations(P({ status: 'validated', running: false }), at(0));
assert.equal(wait2.stations[0].state, 'need'); assert.ok(wait2.stations.slice(1).every((x) => x.state === 'pending'));
assert.equal(falStations(P({ status: 'paused', pause_code: 'monthly_cap', running: false, fal: sent }), at(10)).stations[1].state, 'problem');
const failed = falStations(P({ status: 'failed', ended: 'failed', running: false, fal: sent }), at(EST_WORKFLOW_S * 0.5));
assert.equal(failed.stations[3].state, 'problem'); assert.equal(failed.stations[3].label, 'Falhou');
// Escritório: só o agente da etapa atual trabalha
assert.deepEqual(Object.entries(falAgentStatus(P({ fal: sent }), at(EST_WORKFLOW_S * 0.5))).filter(([, v]) => v !== 'idle'), [['lia', 'work']]);
assert.equal(falAgentStatus(P({ status: 'validated', running: false }), at(0)).nina, 'need');

assert.equal(endedLabel(P({ status: 'cancelled', ended: 'cancelled', fal: { delivery_status: 'incomplete' } })), 'Entrega parcial');
assert.equal(endedLabel(P({ status: 'cancelled', ended: 'cancelled' })), null);                        // cancelada sem entrega: segue "Missão cancelada"
assert.equal(endedLabel(P({ status: 'failed', ended: 'failed', fal: { delivery_status: 'incomplete' } })), null);
assert.equal(endedLabel({ engine: 'gemini', ended: 'cancelled', delivery_status: 'incomplete' }), null);

// a esteira existente entende a produção fal (sem cenas): mesmas etapas de entrega
assert.equal(deriveStage(P({ status: 'producing' })), 'img_gerando');
assert.equal(deriveStage(P({ status: 'editing' })), 'montando');
assert.equal(deriveStage(P({ status: 'awaiting_final_review' })), 'entrega');
assert.equal(deriveStage(P({ status: 'completed' })), 'exportado');
assert.equal(deriveStage(P({ status: 'paused', fal: { finalizing: true } })), 'img_gerando');
assert.equal(deriveStage(P({ status: 'cancelled', ended: 'cancelled' })), 'cancelada');

// entrega: vídeo + 1 foto (hero) + título e legenda, com download individual (?download=1)
const done = P({ status: 'awaiting_final_review', delivery: { 'final.mp4': '/media/p/delivery/final.mp4', 'cover.jpg': '/media/p/delivery/cover.jpg', 'caption.txt': '/media/p/delivery/caption.txt' },
  fal: { delivery_status: 'complete', title: 'Copo azul', caption: 'Mantém gelado.',
    image: { role: 'hero', label: 'Hero Shot', file: 'product_image_01.jpg', url: '/media/p/delivery/product_image_01.jpg' } } });
const g = gallery(done);
assert.equal(g.image.label, 'Hero Shot'); assert.ok(!('images' in g));                                  // sem galeria de 3 fotos
assert.equal(g.image.download, '/media/p/delivery/product_image_01.jpg?download=1');
assert.equal(g.video.download, '/media/p/delivery/final.mp4?download=1');
assert.equal(g.captionFile.download, '/media/p/delivery/caption.txt?download=1');
assert.equal(g.title, 'Copo azul'); assert.equal(g.caption, 'Mantém gelado.'); assert.equal(g.textMissing, false); assert.equal(g.partial, false);
// sem título e legenda (o fluxo entrega com aviso): a tela avisa, nunca inventa texto
const notext = gallery(P({ status: 'awaiting_final_review', delivery: { 'final.mp4': '/m/final.mp4' }, fal: { delivery_status: 'complete', title: '', caption: '' } }));
assert.equal(notext.textMissing, true); assert.equal(notext.title, ''); assert.equal(notext.caption, '');
assert.equal(downloadUrl('/m?x=1'), '/m?x=1&download=1'); assert.equal(downloadUrl(null), null);
assert.equal(gallery({ engine: 'gemini' }), null);
// entrega incompleta não publica nada: sem links
const inc = gallery(P({ status: 'paused', fal: { finalizing: true, missing_images: ['hero'], delivery_status: 'incomplete', image: { role: 'hero', label: 'Hero Shot', file: 'x', url: null } } }));
assert.equal(inc.video, null); assert.equal(inc.image.download, null);

// "Seu próximo vídeo" no motor fal.ai: estilo e o que vem no pacote, sem cenas nem ajustes
const sm = { engine: 'fal', style: 'light', product: '', total_credits: '32,4', total_brl: null, balance: '500', balance_after: '467,6', exempt: false };
const rows = Object.fromEntries(falSummaryRows(sm, credits));
assert.equal(rows['Estilo'], 'Claro'); assert.ok(!('Cenas' in rows) && !('Ajustes incluídos por cena' in rows));
assert.match(rows['O que você recebe'], /1 foto publicitária/); assert.ok(!/trilha|3 fotos/i.test(rows['O que você recebe']));
assert.equal(rows['Custo total autorizado'], '32,4 créditos');
assert.ok(Object.fromEntries(summaryRows({ ...sm, format: '9:16', scenes: 3, included_adjustments_per_scene: 1, product: 'X' }))['Estilo'] === 'Claro');

// o cliente nunca vê modelo, fila técnica ou "fal.ai" nas telas do fluxo
const read = (f) => readFileSync(new URL('../src/' + f, import.meta.url), 'utf8');
const ui = read('ui/FalWindow.jsx');
assert.ok(!/galeria|Lifestyle|Detalhes|trilha|Texto da narração/i.test(ui.replace(/\/\/.*$/gm, '')), 'a tela ainda cita o escopo antigo');
assert.ok(!/fal\.ai|workflow|queue\.fal/i.test(ui.replace(/\/\/.*$/gm, '')), 'a tela do fluxo cita o fornecedor');

// ---------------------------------------------------------------- "Criar vídeo": create → confirm → run
const fakePost = (fail = {}) => {
  const calls = [];
  const fn = async (path, body) => {
    calls.push([path, body]);
    for (const [k, err] of Object.entries(fail)) if (path.endsWith(k)) throw Object.assign(new Error(err.message || ''), { code: err.code });
    return path === '/api/productions' ? { ok: true, pid: 'prod_abc' } : { ok: true, started: true };
  };
  return { fn, calls };
};
const okRun = fakePost();
const r1 = await startFal(okRun.fn, { body: { style: 'light' }, cc: 972 });
assert.deepEqual(r1, { ok: true, pid: 'prod_abc' });
assert.deepEqual(okRun.calls.map((c) => c[0]), ['/api/productions', '/api/productions/prod_abc/confirm', '/api/productions/prod_abc/run']);   // nessa ordem
assert.deepEqual(okRun.calls[1][1], { total_cc: 972 });                       // o custo que o botão mostrou
const demo = fakePost(); await startFal(demo.fn, { body: {}, cc: 0 }); assert.deepEqual(demo.calls[1][1], {});
// falha em qualquer passo: para ali, devolve a mensagem do servidor (o modal continua aberto)
const noCredit = fakePost({ '/api/productions': { message: 'Saldo insuficiente para este vídeo.' } });
assert.deepEqual(await startFal(noCredit.fn, { body: {}, cc: 972 }), { ok: false, pid: null, step: 'create', error: 'Saldo insuficiente para este vídeo.' });
assert.equal(noCredit.calls.length, 1);
const limit = fakePost({ '/run': { message: 'Seu limite mensal foi atingido. Nada foi cobrado.', code: 'spend_limit' } });
const r2 = await startFal(limit.fn, { body: {}, cc: 972 });
assert.equal(r2.ok, false); assert.equal(r2.step, 'run'); assert.equal(r2.error, 'Seu limite mensal foi atingido. Nada foi cobrado.'); assert.equal(r2.pid, 'prod_abc');
const conf = fakePost({ '/confirm': { message: 'o custo mudou desde que você viu o resumo; revise e confirme de novo' } });
const r3 = await startFal(conf.fn, { body: {}, cc: 972 });
assert.equal(r3.step, 'confirm'); assert.equal(conf.calls.length, 2);           // não chega a /run
assert.equal((await startFal(fakePost({ '/run': { message: 'HTTP 502' } }).fn, { body: {}, cc: 0 })).error, FRIENDLY_FALLBACK);
// reenvio depois de uma resposta perdida: o servidor diz que já começou → sucesso, sem segundo envio
const again = fakePost({ '/confirm': { message: 'Este vídeo já foi enviado para criação.', code: 'already_started' } });
const r4 = await startFal(again.fn, { body: {}, cc: 972 });
assert.equal(r4.ok, true); assert.equal(r4.already, true); assert.ok(!again.calls.some((c) => c[0].endsWith('/run')));
const again2 = fakePost({ '/run': { message: 'Este vídeo já está sendo criado.', code: 'already_started' } });
assert.equal((await continueFal(again2.fn, 'prod_x', 0)).ok, true);
// botão e linha de baixo
const Soffer = { settings: { fal_styles: [{ id: 'light', label: 'Claro', cc: 972, credits: '9,72' }] } };
assert.deepEqual(offerFor(Soffer, 'light'), { cc: 972, credits: '9,72' });
assert.equal(createLabel(offerFor(Soffer, 'light'), false), 'Criar vídeo · 9,72 créditos');
assert.equal(createLabel(offerFor(Soffer, 'light'), true), 'Criar vídeo');
assert.equal(RECEIVE_LINE, 'Você recebe: vídeo ~15 s com narração, 1 foto, título e legenda. Se falhar por erro técnico, não é cobrado.');
// as telas do fluxo novo não têm mais as abas Criar/Acompanhar/Entrega nem o cartão "Seu próximo vídeo"
const ui2 = read('ui/FalWindow.jsx') + read('ui/FalMission.jsx');
assert.ok(!/Acompanhar|Seu próximo vídeo|Confirmar e criar|Preparando a foto|role="tab"/.test(ui2), 'sobrou o fluxo antigo');
assert.ok(!/fal\.ai|workflow|queue\.fal/i.test(ui2.replace(/\/\/.*$/gm, '')), 'a tela cita o fornecedor');
console.log('falflow.test ok');
