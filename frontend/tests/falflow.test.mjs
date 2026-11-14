import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { SCENES, PLATFORMS, DEFAULT_SCENE, DEFAULT_PLATFORM, NAME_MAX, availableScenes, availablePlatforms, effectiveScene, effectivePlatform, lockText, cleanName, sceneImage, sceneThumb, platformLogo, receiveLine, draftErrors, createPayload, falActive, falStatus, falStations, falStepIndex, falAgentStatus, startFal, continueFal, offerFor, createLabel, FRIENDLY_FALLBACK, EST_WORKFLOW_S, endedLabel, gallery, newRequestId, downloadUrl, falSummaryRows } from '../src/ui/falFlow.js';
import { deriveStage } from '../src/engine/adapter.js';
import { summaryRows, credits } from '../src/ui/nextVideo.js';

// cenário + plataforma + validação: foto obrigatória; nome e descrição NÃO são obrigatórios
assert.deepEqual(SCENES.map((s) => s.id), ['home_light', 'studio', 'natural', 'dark_premium']);
assert.deepEqual(PLATFORMS.map((s) => s.id), ['shopee_video', 'tiktok_shop', 'mercado_livre']);
assert.equal(DEFAULT_SCENE, 'home_light'); assert.equal(DEFAULT_PLATFORM, 'shopee_video');
assert.deepEqual(SCENES.map((s) => s.label), ['Casa Clara', 'Estúdio', 'Natural', 'Escuro Premium']);
assert.deepEqual(PLATFORMS.map((s) => s.label), ['Shopee Vídeo', 'TikTok Shop', 'Mercado Livre']);
assert.deepEqual(draftErrors({ scene: 'studio', platform: 'tiktok_shop', file: { name: 'a.PNG' } }), []);
assert.deepEqual(draftErrors({ scene: null, platform: null, file: null }), ['a foto do produto', 'o cenário', 'a plataforma']);
assert.deepEqual(draftErrors({ scene: 'studio', platform: 'shopee_video', file: { name: 'v.mp4' } }), ['uma foto JPG, PNG ou WEBP']);
// o corpo leva SÓ ids (nunca texto de prompt) + id do cliente + foto, e o nome só se houver
const body = createPayload({ scene: 'dark_premium', platform: 'mercado_livre', file: { name: 'a.png', data: 'data:x' }, requestId: 'abc12345' });
assert.deepEqual(body, { scene: 'dark_premium', platform: 'mercado_livre', client_request_id: 'abc12345', files: [{ name: 'a.png', data: 'data:x' }] });
assert.equal(createPayload({ scene: 'studio', platform: 'shopee_video', file: { name: 'a.png', data: 'd' }, requestId: 'abc12345', name: ' Copo ' }).name, 'Copo');
assert.ok(!Object.keys(body).some((k) => /prompt|strategy|context/i.test(k)));
// nome: sem quebras de linha nem controles, até 80 caracteres
assert.equal(NAME_MAX, 80);
assert.equal(cleanName('  Copo \n  Azul\t500ml\u0000 '), 'Copo Azul 500ml');
assert.equal(cleanName('x'.repeat(200)).length, 80); assert.equal(cleanName(null), '');
assert.equal(createPayload({ scene: 'studio', platform: 'shopee_video', file: { name: 'a.png', data: 'd' }, requestId: 'abc12345', name: 'a\nb' }).name, 'a b');
assert.equal('name' in createPayload({ scene: 'studio', platform: 'shopee_video', file: { name: 'a.png', data: 'd' }, requestId: 'abc12345', name: '  \n ' }), false);

// listas do servidor (settings.fal_scenes / fal_platforms); sem elas, a reserva local; padrão Casa Clara + Shopee Vídeo
assert.deepEqual(availableScenes({}).map((s) => s.id), ['home_light', 'studio', 'natural', 'dark_premium']);
assert.ok(availableScenes({}).every((s) => s.locked === false));
assert.deepEqual(availablePlatforms({}).map((s) => s.id), ['shopee_video', 'tiktok_shop', 'mercado_livre']);
assert.equal(effectiveScene({}, null), 'home_light'); assert.equal(effectiveScene({}, 'natural'), 'natural'); assert.equal(effectiveScene({}, 'neon'), 'home_light');
assert.equal(effectivePlatform({}, null), 'shopee_video'); assert.equal(effectivePlatform({}, 'tiktok_shop'), 'tiktok_shop'); assert.equal(effectivePlatform({}, 'orkut'), 'shopee_video');
// acesso antecipado: cenário bloqueado mostra o cadeado ("Disponível no plano Escala") e não pode ser escolhido
const Slock = { settings: { fal_scenes: [
  { id: 'home_light', label: 'Casa Clara', subtitle: 'Sala iluminada, tons neutros', locked: false },
  { id: 'studio', label: 'Estúdio', subtitle: 'Cinza pérola, luz editorial', locked: true, required_plan: 'escala', required_plan_label: 'Escala' },
] } };
const sc = availableScenes(Slock);
assert.equal(sc[1].locked, true); assert.equal(lockText(sc[1]), 'Disponível no plano Escala'); assert.equal(lockText(sc[0]), null);
assert.equal(effectiveScene(Slock, 'studio'), 'home_light');                       // escolha bloqueada cai no padrão
assert.equal(effectiveScene(Slock, 'home_light'), 'home_light');
const Slock2 = { settings: { fal_scenes: [{ id: 'home_light', label: 'Casa Clara', locked: true, required_plan_label: 'Escala' }, { id: 'natural', label: 'Natural', locked: false }] } };
assert.equal(effectiveScene(Slock2, null), 'natural');                              // padrão bloqueado: o primeiro liberado
// assets
assert.equal(sceneImage('studio'), '/assets/scenes/studio.jpg'); assert.equal(sceneThumb('studio'), '/assets/scenes/studio-thumb.jpg');
assert.equal(platformLogo('tiktok_shop'), '/assets/platforms/tiktok_shop.png');
// texto do rodapé com a plataforma escolhida
assert.equal(receiveLine('TikTok Shop'), 'Você recebe vídeo de ~15 s com narração, 1 foto, título e legenda para TikTok Shop. Se falhar por erro técnico, não é cobrado.');

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
assert.equal(belt({ fal: sent }, 20).find((x) => x.current).id, 'roteiro');
assert.equal(belt({ fal: sent }, 50).find((x) => x.current).id, 'imagens');
assert.equal(belt({ fal: sent }, EST_WORKFLOW_S * 0.5).find((x) => x.current).id, 'videos');
assert.equal(belt({ fal: sent }, EST_WORKFLOW_S * 0.9).find((x) => x.current).id, 'videos');
// etapas que a estimativa já passou: "Concluída", 100%; só UMA em andamento
const mid = belt({ fal: sent }, 50);
assert.deepEqual(mid.map((x) => x.state), ['done', 'done', 'active', 'pending', 'pending', 'pending']);
assert.deepEqual(mid.slice(0, 2).map((x) => [x.label, x.level]), [['Concluída', 100], ['Concluída', 100]]);
assert.ok(mid[2].level > 0 && mid[2].level <= 95); assert.equal(mid[2].label, 'Em andamento');
for (let s = 0; s <= EST_WORKFLOW_S * 2; s += 3) {
  const b = belt({ fal: sent }, s);
  assert.equal(b.filter((x) => x.state === 'active').length, 1, 'uma em andamento em ' + s + 's');
  b.filter((x) => x.state !== 'done').forEach((x) => assert.ok(x.level <= 95, 'acima de 95 por estimativa em ' + s + 's'));
}
const late = falStations(P({ fal: sent }), at(EST_WORKFLOW_S * 50));                                  // demorou muito mais: VÍDEOS em 95% "Finalizando…"
assert.equal(late.current, 'videos'); assert.deepEqual(late.stations.map((x) => x.level), [100, 100, 100, 95, 0, 0]);
assert.deepEqual(late.stations.map((x) => x.state), ['done', 'done', 'done', 'active', 'pending', 'pending']);
assert.equal(late.stations[3].label, 'Finalizando…'); assert.equal(late.status.text, 'Finalizando…'); assert.equal(late.stations[4].state, 'pending');
assert.ok(belt({ fal: sent }, 10).every((x) => typeof x.level === 'number'));                           // toda estação tem barra
const edit = falStations(P({ status: 'editing', fal: sent }), at(60));
assert.equal(edit.current, 'edicao'); assert.equal(edit.stations[5].state, 'active'); assert.ok(edit.progress < 100);
const rev = falStations(P({ fal: { ...sent, stage: 'ingesting' } }), at(60));                          // REVISÃO é etapa real do servidor
assert.equal(rev.current, 'revisao'); assert.deepEqual(rev.stations.slice(0, 4).map((x) => x.state), ['done', 'done', 'done', 'done']);
const ready = falStations(P({ status: 'awaiting_final_review', fal: sent }), at(60));
assert.ok(ready.stations.every((x) => x.state === 'done' && x.level === 100)); assert.equal(ready.progress, 100);
const wait2 = falStations(P({ status: 'validated', running: false }), at(0));
assert.equal(wait2.stations[0].state, 'need'); assert.ok(wait2.stations.slice(1).every((x) => x.state === 'pending'));
assert.equal(falStations(P({ status: 'paused', pause_code: 'monthly_cap', running: false, fal: sent }), at(20)).stations[1].state, 'problem');
const failed = falStations(P({ status: 'failed', ended: 'failed', running: false, fal: sent }), at(EST_WORKFLOW_S * 0.5));
assert.equal(failed.stations[3].state, 'problem'); assert.equal(failed.stations[3].label, 'Não deu certo'); assert.equal(failed.stations[3].fail, true);
assert.deepEqual(failed.stations.map((x) => x.state), ['done', 'done', 'done', 'problem', 'pending', 'pending']);   // falha: atual vermelha, seguintes pendentes
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

// "Seu próximo vídeo" no motor fal.ai: cenário, plataforma e o que vem no pacote, sem cenas nem ajustes
const sm = { engine: 'fal', scene: 'natural', platform: 'tiktok_shop', product: '', total_credits: '32,4', total_brl: null, balance: '500', balance_after: '467,6', exempt: false };
const rows = Object.fromEntries(falSummaryRows(sm, credits));
assert.equal(rows['Cenário'], 'Natural'); assert.equal(rows['Plataforma'], 'TikTok Shop'); assert.ok(!('Estilo' in rows) && !('Cenas' in rows) && !('Ajustes incluídos por cena' in rows));
assert.match(rows['O que você recebe'], /1 foto publicitária/); assert.ok(!/trilha|3 fotos/i.test(rows['O que você recebe']));
assert.equal(rows['Custo total autorizado'], '32,4 créditos');
assert.ok(Object.fromEntries(summaryRows({ ...sm, format: '9:16', scenes: 3, included_adjustments_per_scene: 1, product: 'X' }))['Cenário'] === 'Natural');

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
const r1 = await startFal(okRun.fn, { body: { scene: 'home_light', platform: 'shopee_video' }, cc: 972 });
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
const Soffer = { settings: { fal_offer: { cc: 2000, credits: '20' } } };
assert.deepEqual(offerFor(Soffer), { cc: 2000, credits: '20' });                    // preço único, igual para qualquer cenário/plataforma
assert.equal(createLabel(offerFor(Soffer), false), 'Criar vídeo · 20 créditos');
assert.equal(createLabel(offerFor(Soffer), true), 'Criar vídeo');
assert.deepEqual(offerFor({}), { cc: 0, credits: '0' });
// as telas do fluxo novo não têm mais as abas Criar/Acompanhar/Entrega nem o cartão "Seu próximo vídeo"
const ui2 = read('ui/FalWindow.jsx') + read('ui/FalMission.jsx');
assert.ok(!/Acompanhar|Seu próximo vídeo|Confirmar e criar|Preparando a foto|role="tab"/.test(ui2), 'sobrou o fluxo antigo');
assert.ok(!/fal\.ai|workflow|queue\.fal/i.test(ui2.replace(/\/\/.*$/gm, '')), 'a tela cita o fornecedor');
// modal novo: cartões são <button aria-pressed>, logos com alt vazio, foco visível e nenhum texto de prompt no front
const modal = read('ui/FalWindow.jsx').replace(/\/\/.*$/gm, '');
const css = read('ui/falModal.css');
assert.match(modal, /aria-pressed=\{on\}/); assert.match(modal, /alt=""/); assert.match(modal, /aria-label="Fechar"/);
assert.match(css, /--accent: #5b5bd6/); assert.match(css, /:focus-visible \{ outline: 2px solid var\(--accent\)/);
assert.match(css, /\.fm-x \{ width: 44px; height: 44px/);
assert.ok(!/scene_prompt|platform_strategy|CRITICAL OBJECT|copywriting/.test(modal + read('App.jsx') + read('ui/falFlow.js')), 'texto de prompt no front');

// ---------------------------------------------------------------- tela "Missão concluída" (lógica pura)
import { isDone, canCancelFal, splitCaption, titleCount, charsLabel, wordCount, fmtDuration, doneSubtitle, narrationMeta, copyWithFeedback, reuseDraft, reuseBlocked, reuseFileName, REUSE_LABEL, IMAGE_EXT } from '../src/ui/falFlow.js';
const mk = (status, over = {}) => ({ engine: 'fal', status, ended: null, ...over });
// concluída = entregue e não encerrada; "Cancelar missão" só em andamento
for (const st of ['received', 'validated', 'scripted', 'producing', 'editing', 'paused']) { assert.equal(canCancelFal(mk(st)), true, st); assert.equal(isDone(mk(st)), false, st); }
for (const st of ['awaiting_final_review', 'completed', 'failed', 'cancelled']) assert.equal(canCancelFal(mk(st)), false, st);
assert.equal(canCancelFal(mk('producing', { ended: 'cancelled' })), false); assert.equal(canCancelFal(mk('producing', { ended: 'failed' })), false);
assert.equal(isDone(mk('awaiting_final_review')), true); assert.equal(isDone(mk('completed')), true);
assert.equal(isDone(mk('awaiting_final_review', { ended: 'cancelled' })), false); assert.equal(isDone({ engine: 'gemini', status: 'completed' }), false);
assert.equal(canCancelFal({ engine: 'gemini', status: 'producing' }), false);
// hashtags viram chips; o texto exibido não as repete; a contagem é do texto completo
const capt = splitCaption('Descubra o fone! 🎧 Clica no carrinho. #FoneDeOuvido #TikTokAchados #FoneDeOuvido');
assert.deepEqual(capt.tags, ['#FoneDeOuvido', '#TikTokAchados']); assert.equal(capt.body, 'Descubra o fone! 🎧 Clica no carrinho.');
assert.equal(capt.full, 'Descubra o fone! 🎧 Clica no carrinho. #FoneDeOuvido #TikTokAchados #FoneDeOuvido'); assert.equal(capt.count, [...capt.full].length);
assert.deepEqual(splitCaption('Sem tags.').tags, []); assert.deepEqual(splitCaption(null).tags, []); assert.equal(splitCaption(null).count, 0);
assert.deepEqual(splitCaption('Olá #promoção_2026 e #Café').tags, ['#promoção_2026', '#Café']);          // acentos e números
assert.equal(titleCount('Fone 🎧'), 6); assert.equal(charsLabel(1), '1 caractere'); assert.equal(charsLabel(57), '57 caracteres'); assert.equal(charsLabel(312, true), '312 caracteres com hashtags');
// duração e créditos reais no banner; narração só com o que existe
assert.equal(fmtDuration(45), '45 s'); assert.equal(fmtDuration(0.2), '1 s'); assert.equal(fmtDuration(60), '1 min'); assert.equal(fmtDuration(178), '3 min'); assert.equal(fmtDuration(null), ''); assert.equal(fmtDuration(-5), '');
assert.equal(doneSubtitle({ elapsedS: 180, creditsUsed: 20 }), 'Feito pela equipe em 3 min · 20 créditos usados');
assert.equal(doneSubtitle({ elapsedS: null, creditsUsed: 20 }), '20 créditos usados'); assert.equal(doneSubtitle({ elapsedS: 40, creditsUsed: 0 }), 'Feito pela equipe em 40 s'); assert.equal(doneSubtitle({}), '');
assert.equal(narrationMeta({ text: 'a b c', seconds: 12.4, words: 27 }), '12 s · 27 palavras'); assert.equal(narrationMeta({ text: 'um dois', seconds: null }), '2 palavras');
assert.equal(narrationMeta({ text: 'oi', seconds: 3 }), '3 s · 1 palavra'); assert.equal(narrationMeta(null), ''); assert.equal(narrationMeta({ text: '' }), '');
assert.equal(wordCount('Clica no carrinho e garante o seu!'), 7);
const withNar = (n) => gallery({ engine: 'fal', status: 'awaiting_final_review', delivery: {}, fal: { narration: n } }).narration;
assert.equal(withNar({ text: ' Fala. ', seconds: 5 }).text, 'Fala.'); assert.equal(withNar({ text: '  ' }), null); assert.equal(withNar(null), null); assert.equal(withNar(undefined), null);
const gx = gallery({ engine: 'fal', status: 'awaiting_final_review', delivery: {}, credits: { spent: 20 }, fal: { elapsed_s: 180, scene: 'natural', platform: 'tiktok_shop' } });
assert.equal(gx.elapsedS, 180); assert.equal(gx.creditsUsed, 20); assert.equal(gallery({ engine: 'fal', mode: 'simulated', status: 'completed', delivery: {}, credits: { spent: 10 }, fal: {} }).creditsUsed, null); assert.equal(gx.sceneId, 'natural'); assert.equal(gx.platformId, 'tiktok_shop');

// copiar (clipboard simulado): grava o texto completo, liga "Copiado" e desliga depois de ~2 s; sem clipboard ou com recusa, não liga
{
  const writes = []; const states = []; const timers = [];
  const clip = { writeText: async (t) => { writes.push(t); } };
  const ok = await copyWithFeedback(clip, 'Fone de Ouvido Azul', (v) => states.push(v), (fn, ms) => timers.push([fn, ms]));
  assert.equal(ok, true); assert.deepEqual(writes, ['Fone de Ouvido Azul']); assert.deepEqual(states, [true]); assert.equal(timers.length, 1); assert.equal(timers[0][1], 2000);
  timers[0][0](); assert.deepEqual(states, [true, false]);
  const full = splitCaption('Texto. #A #B').full;                                   // "Copiar legenda" copia o texto COMPLETO, com hashtags
  await copyWithFeedback(clip, full, () => {}, () => {}); assert.equal(writes[1], 'Texto. #A #B');
  const st2 = []; assert.equal(await copyWithFeedback({ writeText: async () => { throw new Error('negado'); } }, 'x', (v) => st2.push(v), () => {}), false); assert.deepEqual(st2, []);
  assert.equal(await copyWithFeedback(null, 'x', () => {}), false); assert.equal(await copyWithFeedback(clip, '', () => {}), false);
  // clipboard negado (navegador embutido): cai no plano B, que também liga "Copiado"; sem plano B, nada liga
  const denied = { writeText: async () => { throw new Error('NotAllowedError'); } }; const st3 = []; const copied = [];
  assert.equal(await copyWithFeedback(denied, 'Texto', (v) => st3.push(v), () => {}, 2000, (t) => { copied.push(t); return true; }), true); assert.deepEqual(copied, ['Texto']); assert.deepEqual(st3, [true]);
  assert.equal(await copyWithFeedback(denied, 'Texto', () => {}, () => {}, 2000, () => false), false);
  assert.equal(await copyWithFeedback(null, 'Texto', () => {}, () => {}, 2000, () => true), true);
}

// "Outra plataforma" / "Outro cenário": mesma foto, nome, cenário e plataforma; botão travado até a escolha pedida mudar
const Pdone = { engine: 'fal', status: 'awaiting_final_review', scene: 'natural', platform: 'tiktok_shop', product: { name: ' Fone \n azul ' },
  sheet: { references: [{ url: null }, { url: '/media/p1/references/ref_01.PNG' }] }, fal: { scene: 'natural', platform: 'tiktok_shop' } };
const dp = reuseDraft(Pdone, 'platform');
assert.deepEqual(dp, { kind: 'platform', scene: 'natural', platform: 'tiktok_shop', name: 'Fone azul', photoUrl: '/media/p1/references/ref_01.PNG', original: { scene: 'natural', platform: 'tiktok_shop' } });
assert.equal(reuseDraft(Pdone, 'scene').kind, 'scene'); assert.equal(reuseDraft(Pdone, 'tudo'), null); assert.equal(reuseDraft({ engine: 'gemini' }, 'scene'), null);
assert.equal(reuseDraft({ ...Pdone, sheet: { references: [] } }, 'scene').photoUrl, null);
assert.deepEqual(REUSE_LABEL, { platform: 'Escolha outra plataforma', scene: 'Escolha outro cenário' });
const rp = { kind: 'platform', original: { scene: 'natural', platform: 'tiktok_shop' } }, rs = { kind: 'scene', original: { scene: 'natural', platform: 'tiktok_shop' } };
assert.equal(reuseBlocked(rp, 'natural', 'tiktok_shop'), true);        // ainda é a plataforma original
assert.equal(reuseBlocked(rp, 'studio', 'tiktok_shop'), true);         // mudar só o cenário não destrava "outra plataforma"
assert.equal(reuseBlocked(rp, 'natural', 'shopee_video'), false);
assert.equal(reuseBlocked(rs, 'natural', 'shopee_video'), true); assert.equal(reuseBlocked(rs, 'studio', 'tiktok_shop'), false);
assert.equal(reuseBlocked(null, 'natural', 'tiktok_shop'), false);     // fluxo normal (Nova produção): nunca trava
assert.equal(reuseFileName('/media/p1/ref_01.PNG'), 'foto.png'); assert.equal(reuseFileName('/media/p1/x.jpeg?v=2'), 'foto.jpeg'); assert.equal(reuseFileName('/media/p1/x', 'image/webp'), 'foto.webp'); assert.equal(reuseFileName('/x', ''), 'foto.jpg');
assert.ok(IMAGE_EXT.test(reuseFileName('/media/p1/ref_01.PNG')));      // o nome passa na validação do envio

// telas: sem "SEU VÍDEO"/saldo/cartão Pronto no código novo; nada de copiar link de /media; Nova missão em accent; modal com foco e botão travado
const missionSrc = read('ui/FalMission.jsx').replace(/\/\/.*$/gm, '') + read('shell/MissionView.jsx').replace(/\/\/.*$/gm, '').split('export function FalMissionView')[1].split('export default function MissionView')[0] + read('shell/Phone.jsx').replace(/\/\/.*$/gm, '');
assert.ok(!/Usado neste vídeo|FalDelivery|PhoneDelivery|Entrega<\/div>/.test(missionSrc), 'sobrou o cartão de saldo ou a entrega antiga');
assert.ok(!/writeText\([^)]*(url|href)/i.test(missionSrc), 'não copie link de /media');
assert.match(read('shell/shell.css'), /\.pv-cta\.pv-cta-accent \{ background: #5b5bd6/);
const dcss = read('ui/falDone.css');
assert.match(dcss, /--accent: #5b5bd6/); assert.match(dcss, /--fd-line: #ececef/); assert.match(dcss, /border: 1px solid var\(--fd-line\)/); assert.match(dcss, /border-radius: 16px/);
assert.match(dcss, /\.fd-btn \{ min-height: 44px/); assert.match(dcss, /\.fd :focus-visible \{ outline: 2px solid var\(--accent\)/);
assert.match(read('ui/falModal.css'), /\.fm-hl \{ outline: 2px solid var\(--accent\)/);
const win = read('ui/FalWindow.jsx').replace(/\/\/.*$/gm, '');
assert.match(win, /f\.reuseBlocked \? f\.reuseLabel/); assert.match(win, /disabled=\{f\.busy \|\| f\.reuseBlocked/); assert.match(win, /scrollIntoView/);

console.log('falflow.test ok');
