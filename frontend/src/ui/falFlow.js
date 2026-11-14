// Fluxo do motor fal.ai: 1 foto + cenário + plataforma → vídeo (com narração) + 1 foto + título e legenda. Lógica pura (tests/falflow.test.mjs).
// Só aparece quando o servidor diz `settings.video_engine === 'fal'` ou a produção aberta é `engine === 'fal'`.
// O front manda SÓ os ids `scene` e `platform` (o servidor valida a allowlist e monta todo o texto de prompt).

export const DEFAULT_SCENE = 'home_light';
export const DEFAULT_PLATFORM = 'shopee_video';
// Reserva local (a fonte é settings.fal_scenes / fal_platforms, que traz o bloqueio por plano): mesmos ids e textos do servidor.
export const SCENES = [
  { id: 'home_light', label: 'Casa Clara', sub: 'Sala iluminada, tons neutros' },
  { id: 'studio', label: 'Estúdio', sub: 'Cinza pérola, luz editorial' },
  { id: 'natural', label: 'Natural', sub: 'Luz do dia e vegetação' },
  { id: 'dark_premium', label: 'Escuro Premium', sub: 'Grafite e luz de luxo' },
];
export const PLATFORMS = [
  { id: 'shopee_video', label: 'Shopee Vídeo', sub: 'Promocional, custo-benefício' },
  { id: 'tiktok_shop', label: 'TikTok Shop', sub: 'Gancho rápido, achadinho' },
  { id: 'mercado_livre', label: 'Mercado Livre', sub: 'Informativo e confiável' },
];
export const NAME_MAX = 80;
export const sceneImage = (id) => `/assets/scenes/${id}.jpg`;
export const sceneThumb = (id) => `/assets/scenes/${id}-thumb.jpg`;
export const platformLogo = (id) => `/assets/platforms/${id}.png`;

// Cenários exibidos: a lista do servidor (com `locked`/`required_plan_label` para acesso antecipado) manda; sem ela, a reserva.
export const availableScenes = (S) => {
  const srv = (S && S.settings && S.settings.fal_scenes) || [];
  const list = srv.length ? srv : SCENES;
  return list.map((x) => {
    const base = SCENES.find((s) => s.id === x.id) || {};
    return { id: x.id, label: x.label || base.label, sub: x.subtitle || x.sub || base.sub, locked: !!x.locked,
      requiredPlan: x.required_plan_label || null };
  });
};
export const availablePlatforms = (S) => {
  const srv = (S && S.settings && S.settings.fal_platforms) || [];
  const list = srv.length ? srv : PLATFORMS;
  return list.map((x) => {
    const base = PLATFORMS.find((s) => s.id === x.id) || {};
    return { id: x.id, label: x.label || base.label, sub: x.subtitle || x.sub || base.sub };
  });
};
// "Disponível no plano Escala" (cadeado): só para cenário de acesso antecipado que este plano ainda não vê.
export const lockText = (sc) => (sc && sc.locked ? `Disponível no plano ${sc.requiredPlan || 'Escala'}` : null);
// Escolha efetiva: a feita pelo cliente se existir e estiver liberada; senão o padrão (Casa Clara + Shopee Vídeo).
export const effectiveScene = (S, chosen) => {
  const av = availableScenes(S);
  const ok = (id) => av.some((s) => s.id === id && !s.locked);
  return ok(chosen) ? chosen : (ok(DEFAULT_SCENE) ? DEFAULT_SCENE : ((av.find((s) => !s.locked) || {}).id || DEFAULT_SCENE));
};
export const effectivePlatform = (S, chosen) => {
  const av = availablePlatforms(S);
  return av.some((p) => p.id === chosen) ? chosen : DEFAULT_PLATFORM;
};
export const sceneLabel = (S, id) => (availableScenes(S).find((s) => s.id === id) || {}).label || '';
export const platformLabel = (S, id) => (availablePlatforms(S).find((p) => p.id === id) || {}).label || '';
export const FINAL_FINALIZING = 'Estamos finalizando o seu pacote. Avisaremos quando estiver pronto.';
export const IMAGE_EXT = /\.(jpe?g|png|webp)$/i;

import { EST_WORKFLOW_S, EST_CAP, falFacts, stepBelt, currentStep, overallProgress } from './falBelt.js';
import { isNoFunds } from './welcome.js';

export const isFalProduction = (P) => !!(P && P.engine === 'fal');
const incompleteDelivery = (P) => ['incomplete', 'partial'].includes((P.fal && P.fal.delivery_status) || P.delivery_status);
// O fluxo fal.ai vale para a missão nova (motor da conta) e para qualquer produção que já seja fal.
export const falActive = (S, P, draftMode) => (draftMode || !P ? !!(S && S.settings && S.settings.video_engine === 'fal') : isFalProduction(P));

// UUID por envio: o mesmo valor é reutilizado em um reenvio, e o servidor devolve a produção que já existe (duplo clique).
export function newRequestId(rnd = () => globalThis.crypto && globalThis.crypto.randomUUID && globalThis.crypto.randomUUID()) {
  const id = rnd();
  return id || `r${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}

export function draftErrors({ scene, platform, file }) {
  const e = [];
  if (!file) e.push('a foto do produto');
  else if (!IMAGE_EXT.test(file.name || '')) e.push('uma foto JPG, PNG ou WEBP');
  if (!scene) e.push('o cenário');
  if (!platform) e.push('a plataforma');
  return e;
}

// Nome opcional: sem quebras de linha nem caracteres de controle, no máximo 80 (o servidor repete a limpeza).
export const cleanName = (name) => String(name || '').replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, NAME_MAX).trim();

// Só ids: nunca texto de prompt.
export function createPayload({ scene, platform, file, requestId, name }) {
  const body = { scene, platform, client_request_id: requestId, files: [{ name: file.name, data: file.data }] };
  const nm = cleanName(name);
  if (nm) body.name = nm;
  return body;
}

// ---------------------------------------------------------------- "Criar vídeo": create → confirm → run
// Um clique = consentimento explícito. Os três passos vão em sequência, com await; se um falhar, a tela continua aberta
// e mostra a mensagem do servidor (em português). 409 `already_started` no confirm/run = a mesma produção já começou
// (ex.: reenvio depois de uma resposta perdida): é sucesso, nunca um segundo envio.
export const FRIENDLY_FALLBACK = 'Não deu certo agora. Tente de novo em instantes.';

const noFunds = (e) => (isNoFunds(e) ? { noFunds: true } : {});   // 402 de saldo: a tela troca o texto e oferece os pacotes

const friendly = (e) => {
  const m = (e && e.message) || '';
  return !m || /^HTTP \d+/.test(m) || /failed to fetch|network/i.test(m) ? FRIENDLY_FALLBACK : m;
};

export async function continueFal(post, pid, cc) {
  try { await post(`/api/productions/${pid}/confirm`, cc > 0 ? { total_cc: cc } : {}); } catch (e) {
    if (e && e.code === 'already_started') return { ok: true, pid, already: true };
    return { ok: false, pid, step: 'confirm', error: friendly(e), ...noFunds(e) };
  }
  try { await post(`/api/productions/${pid}/run`, {}); } catch (e) {
    if (e && e.code === 'already_started') return { ok: true, pid, already: true };
    return { ok: false, pid, step: 'run', error: friendly(e), ...noFunds(e) };
  }
  return { ok: true, pid };
}

export async function startFal(post, { body, cc }) {
  let pid;
  try { pid = (await post('/api/productions', body)).pid; } catch (e) { return { ok: false, pid: null, step: 'create', error: friendly(e), ...noFunds(e) }; }
  return continueFal(post, pid, cc);
}

// Preço do botão "Criar vídeo · N créditos": o mesmo pré-orçamento que o servidor reserva e confere no /confirm.
// Preço único: igual para qualquer cenário e plataforma (settings.fal_offer).
export function offerFor(S) {
  const o = (S && S.settings && S.settings.fal_offer) || null;
  return o ? { cc: o.cc || 0, credits: o.credits || '0' } : { cc: 0, credits: '0' };
}
export const createLabel = (offer, demo) => (demo || !offer.cc ? 'Criar vídeo' : `Criar vídeo · ${offer.credits} créditos`);
export const receiveLine = (platform) => `Você recebe vídeo de ~15 s com narração, 1 foto, título e legenda para ${platform || 'a plataforma escolhida'}. Se falhar por erro técnico, não é cobrado.`;
export const RECEIVE_SHORT = 'Vídeo de ~15 s, 1 foto, título e legenda. Falhou por erro técnico? Não cobra.';

// ---------------------------------------------------------------- esteira (ESTIMATIVA por tempo + etapas reais do servidor)
// Os níveis por etapa vêm de falBelt.js (leia o comentário lá): PLANEJAMENTO..VÍDEOS são ESTIMADOS pelo tempo desde o envio
// (a fal só diz IN_QUEUE / IN_PROGRESS / COMPLETED); REVISÃO e EDIÇÃO são etapas reais do servidor. `view` (opcional) é o
// estado animado mantido pela tela (useFalBelt); sem ele, usa-se o estado "assentado" (sem animação).
export const FAL_STEPS = [
  { id: 'planejamento', title: 'PLANEJAMENTO', label: 'Planejamento', agent: 'nina' },
  { id: 'roteiro', title: 'ROTEIRO', label: 'Roteiro', agent: 'theo' },
  { id: 'imagens', title: 'IMAGENS', label: 'Imagens', agent: 'iris' },
  { id: 'videos', title: 'VÍDEOS', label: 'Vídeos', agent: 'lia' },
  { id: 'revisao', title: 'REVISÃO', label: 'Revisão', agent: 'rui' },
  { id: 'edicao', title: 'EDIÇÃO', label: 'Edição', agent: 'beto' },
];
export { EST_WORKFLOW_S };

const isRunning = (P) => !!P.running || ['producing', 'editing'].includes(P.status);
const notStarted = (P) => ['received', 'awaiting_references', 'validated', 'scripted'].includes(P.status) && !P.running;

// Estado exibido sem animação (primeiro desenho / testes).
export const settledBelt = (P, now = Date.now()) => stepBelt(null, falFacts(P, now), now);

// Níveis + etapa atual + progresso geral a partir de um estado da esteira (animado ou assentado).
export function beltLevels(st) {
  const cur = currentStep(st.levels, st.phase);
  const allDone = st.levels.every((l) => l >= 100);
  return { levels: st.levels, phase: st.phase, cur, allDone, progress: overallProgress(st.levels),
    finalizing: st.phase === 'running' && cur === 3 && st.levels[3] >= EST_CAP };   // fal passou da estimativa: VÍDEOS em 95%
}

// Índice da etapa atual (0..5), 6 = tudo pronto, null = ainda não começou.
export function falStepIndex(P, now = Date.now()) {
  if (!isFalProduction(P)) return null;
  return beltLevels(settledBelt(P, now)).cur;
}
export const falProgress = (P, now = Date.now()) => (isFalProduction(P) ? beltLevels(settledBelt(P, now)).progress : 0);

const runningStatus = (b) => {
  const step = FAL_STEPS[Math.min(b.cur === null ? 0 : b.cur, 5)];
  return { kind: 'running', label: step.label, step: step.id,
    text: b.finalizing ? 'Finalizando…' : 'Estamos criando seu vídeo. Pode sair desta tela: avisamos quando terminar.' };
};

// Estado mostrado ao cliente, SEMPRE derivado do servidor. Nada de "Preparando"/"Criando" antes do /run aceito.
// "Pronto" só aparece depois que a esteira terminou de preencher as seis etapas (quando `view` é dado).
// kind: waiting | running | limit | finalizing | paused | failed | cancelled | partial | done
export function falStatus(P, now = Date.now(), view = null) {
  if (!isFalProduction(P)) return null;
  const f = P.fal || {};
  const ended = endedOfStatus(P);
  const b = beltLevels(view || settledBelt(P, now));
  if (ended === 'failed') return { kind: 'failed', label: 'Não deu certo', text: 'Não deu certo. Nada foi cobrado.' };
  if (ended === 'cancelled') return incompleteDelivery(P)
    ? { kind: 'partial', label: 'Entrega parcial', text: 'A foto não ficou pronta e a missão foi encerrada. Nada mais é cobrado.' }
    : { kind: 'cancelled', label: 'Cancelada', text: 'Missão cancelada. Nada mais é gerado nem cobrado.' };
  if (view && ['awaiting_final_review', 'completed'].includes(P.status) && !b.allDone) return runningStatus(b);   // não pular: anima até 100%
  if (P.status === 'completed') return { kind: 'done', label: 'Pronto', text: 'Pronto e exportado.' };
  if (P.status === 'awaiting_final_review') return { kind: 'done', label: 'Pronto', text: 'Seu vídeo está pronto.' };
  if (P.status === 'paused') {
    const code = P.pause_code || '';
    if (code === 'monthly_cap') return { kind: 'limit', label: 'Pausada: limite mensal atingido', text: 'Nada foi cobrado. A missão continua quando o limite for renovado.' };
    if (code === 'credits_insufficient') return { kind: 'limit', label: 'Pausada: saldo insuficiente', text: 'Nada foi cobrado. Adicione créditos para continuar.' };
    if (code.startsWith('paid_gate')) return { kind: 'limit', label: 'Pausada', text: P.reason || 'A geração está pausada no momento. Nada foi cobrado.' };
    if (f.finalizing) return { kind: 'finalizing', label: 'Em finalização', text: FINAL_FINALIZING };
    return { kind: 'paused', label: 'Pausada', text: P.reason || 'A missão pausou.' };
  }
  if (P.status === 'awaiting_references') return { kind: 'waiting', label: 'Aguardando você', text: P.reason || 'Envie outra foto do produto.', action: null };
  if (notStarted(P)) return { kind: 'waiting', label: 'Aguardando você', text: 'O vídeo ainda não começou. Nada foi cobrado.', action: 'start' };
  if (isRunning(P)) return runningStatus(b);
  return { kind: 'waiting', label: 'Aguardando você', text: 'O vídeo ainda não começou. Nada foi cobrado.', action: 'start' };
}

// Estações da esteira (mesmo formato que o Conveyor desenha), cada uma com `level` (0..100) para a barra do cartão.
// `tab` vazio: a missão fal não tem janelas por etapa. `view`: estado animado da tela (opcional).
export function falStations(P, now = Date.now(), view = null) {
  const vw = view || settledBelt(P, now);
  const b = beltLevels(vw);
  const st = falStatus(P, now, vw);
  const where = b.cur === null ? -1 : b.cur;
  const queued = vw.phase === 'queued';
  const stations = FAL_STEPS.map((s, k) => {
    const level = vw.levels[k];
    const state = level >= 100 ? 'done' : k === where ? 'active' : 'pending';   // só UMA em andamento
    return { id: s.id, agent: s.agent, title: s.title, tab: null, state, detail: '', current: false, level };
  });
  const at = stations[Math.max(0, Math.min(where, 5))];
  if (st && (st.kind === 'failed' || st.kind === 'cancelled' || st.kind === 'partial')) {
    stations.forEach((s) => { if (s.state === 'active') s.state = 'pending'; });
    if (at.state !== 'done') { at.state = st.kind === 'failed' ? 'problem' : 'cancelled'; if (st.kind === 'failed') at.fail = true; }
  } else if (st && ['limit', 'finalizing', 'paused'].includes(st.kind) && at.state !== 'done') at.state = 'problem';
  else if (st && st.kind === 'waiting') { stations.forEach((s) => { s.state = 'pending'; s.level = 0; }); stations[0].state = 'need'; }
  const LBL = { pending: 'Pendente', active: 'Em andamento', need: 'Aguardando você', done: 'Concluída', problem: st && st.kind === 'failed' ? 'Não deu certo' : 'Pausada', cancelled: 'Cancelada', ended: 'Interrompida' };
  stations.forEach((s) => { s.label = s.state === 'active' && s === at && b.finalizing ? 'Finalizando…' : (s.state === 'active' && queued && s === at ? 'Na fila' : LBL[s.state]); });
  const cur = stations.find((s) => ['active', 'need', 'problem', 'cancelled'].includes(s.state) && s === at)
    || stations.find((s) => ['need', 'problem', 'cancelled'].includes(s.state));
  if (cur) cur.current = true;
  return { stations, progress: b.progress, current: cur ? cur.id : null, status: st, allDone: b.allDone };
}

// Status por agente para o Escritório e a equipe (o agente da etapa atual trabalha; "Aguardando você" chama a Nina).
export function falAgentStatus(P, now = Date.now()) {
  const out = {}; FAL_STEPS.forEach((s) => { out[s.agent] = 'idle'; });
  if (!isFalProduction(P)) return out;
  const b = falStations(P, now);
  const cur = b.stations.find((s) => s.current);
  if (cur && cur.state === 'active') out[cur.agent] = 'work';
  if (cur && cur.state === 'need') out[cur.agent] = 'need';
  if (b.status && b.status.kind === 'done' && P.status === 'awaiting_final_review') out.beto = 'need';
  return out;
}

// Entrega: vídeo + 1 foto (hero) + título e legenda copiáveis. Só o que existe tem link.
// Missão encerrada com a entrega incompleta (a foto não ficou pronta) mostra "Entrega parcial", não "Missão cancelada".
export const endedLabel = (P) => (isFalProduction(P) && endedOfStatus(P) === 'cancelled' && incompleteDelivery(P) ? 'Entrega parcial' : null);
const endedOfStatus = (P) => P.ended || (P.status === 'cancelled' || P.status === 'failed' ? P.status : null);
export function downloadUrl(url) { return url ? url + (url.includes('?') ? '&' : '?') + 'download=1' : null; }
export function gallery(P) {
  if (!isFalProduction(P)) return null;
  const d = P.delivery || {}, f = P.fal || {};
  return {
    video: d['final.mp4'] ? { url: d['final.mp4'], download: downloadUrl(d['final.mp4']), name: 'final.mp4' } : null,
    cover: d['cover.jpg'] || null,
    image: f.image ? { role: f.image.role, label: f.image.label, url: f.image.url, download: downloadUrl(f.image.url), name: f.image.file } : null,
    partial: f.delivery_status === 'partial', missing: f.missing_images || [],
    title: f.title || '', caption: f.caption || '', textMissing: !f.title && !f.caption, warnings: f.warnings || [],
    captionFile: d['caption.txt'] ? { download: downloadUrl(d['caption.txt']) } : null,
    narration: f.narration && typeof f.narration.text === 'string' && f.narration.text.trim() ? { ...f.narration, text: f.narration.text.trim() } : null,           // some do card quando o workflow não expõe o texto
    elapsedS: typeof f.elapsed_s === 'number' ? f.elapsed_s : null,
    creditsUsed: P.mode !== 'simulated' && P.credits && typeof P.credits.spent === 'number' ? P.credits.spent : null,   // DEMO: nada é cobrado, não mostra créditos
    sceneId: f.scene || P.scene || null, platformId: f.platform || P.platform || null,
  };
}

// ---------------------------------------------------------------- tela "Missão concluída"
// Concluída = entregue (aguardando revisão final ou exportada) e não encerrada. Falha/cancelada/parcial NÃO entram aqui.
export const isDone = (P) => isFalProduction(P) && ['awaiting_final_review', 'completed'].includes(P.status) && !endedOfStatus(P);
// "Cancelar missão" só existe enquanto a missão está em andamento: não concluída, não falhada, não cancelada.
export const canCancelFal = (P) => isFalProduction(P) && !endedOfStatus(P) && !['awaiting_final_review', 'completed', 'failed', 'cancelled'].includes(P.status);

// Hashtags da legenda como chips; o texto exibido fica sem elas. A contagem é do texto completo (com hashtags).
const TAG = /#[\p{L}\p{N}_]+/gu;
export function splitCaption(caption) {
  const full = String(caption || '');
  const tags = [...new Set(full.match(TAG) || [])];
  const body = full.replace(TAG, '').replace(/[ \t]+\n/g, '\n').replace(/[ \t]{2,}/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
  return { full, body, tags, count: [...full].length };
}
export const titleCount = (t) => [...String(t || '')].length;
export const charsLabel = (n, withTags = false) => `${n} ${n === 1 ? 'caractere' : 'caracteres'}${withTags ? ' com hashtags' : ''}`;
export const wordCount = (t) => (String(t || '').match(/[\p{L}\p{N}]+(?:['’-][\p{L}\p{N}]+)*/gu) || []).length;

// "45 s" abaixo de 1 min; a partir daí, minutos inteiros arredondados ("3 min").
export function fmtDuration(s) {
  if (typeof s !== 'number' || !Number.isFinite(s) || s < 0) return '';
  return s < 60 ? `${Math.max(1, Math.round(s))} s` : `${Math.round(s / 60)} min`;
}
// Linha do banner. Só entra o que existe de verdade (duração e créditos reais da produção).
export function doneSubtitle(g) {
  const parts = [];
  const d = fmtDuration(g && g.elapsedS);
  if (d) parts.push(`Feito pela equipe em ${d}`);
  if (g && typeof g.creditsUsed === 'number' && g.creditsUsed > 0) parts.push(`${g.creditsUsed} créditos usados`);
  return parts.join(' · ');
}
// "12 s · 27 palavras" (de usage_json.narration_seconds e do texto); sem segundos, só as palavras.
export function narrationMeta(n) {
  if (!n || !n.text) return '';
  const words = typeof n.words === 'number' ? n.words : wordCount(n.text);
  const secs = typeof n.seconds === 'number' && n.seconds > 0 ? `${Math.round(n.seconds)} s · ` : '';
  return `${secs}${words} ${words === 1 ? 'palavra' : 'palavras'}`;
}

// Plano B de cópia (navegadores que negam o clipboard assíncrono, como o embutido): textarea temporário + execCommand dentro do toque.
export function legacyCopy(text) {
  if (typeof document === 'undefined' || !document.body || typeof document.execCommand !== 'function') return false;
  const ta = document.createElement('textarea');
  ta.value = text; ta.setAttribute('readonly', ''); ta.setAttribute('aria-hidden', 'true');
  ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0;pointer-events:none';
  document.body.appendChild(ta);
  try { ta.select(); ta.setSelectionRange(0, text.length); return !!document.execCommand('copy'); } catch (e) { return false; } finally { ta.remove(); }
}
// Copiar com retorno: grava no clipboard (ou no plano B) e liga "Copiado" por ~2 s. Tudo entra por parâmetro (testável).
export async function copyWithFeedback(clip, text, setCopied, schedule = setTimeout, ms = 2000, legacy = legacyCopy) {
  if (!text) return false;
  let ok = false;
  if (clip && typeof clip.writeText === 'function') { try { await clip.writeText(text); ok = true; } catch (e) { ok = false; } }
  if (!ok && typeof legacy === 'function') ok = !!legacy(text);
  if (!ok) return false;
  setCopied(true);
  schedule(() => setCopied(false), ms);
  return true;
}

// "Outra plataforma" / "Outro cenário": reabre o modal Nova produção com a MESMA foto, nome, cenário e plataforma do vídeo atual.
// O botão "Criar vídeo" fica desligado, com o texto do pedido, até a escolha pedida ser diferente da original.
export const REUSE_LABEL = { platform: 'Escolha outra plataforma', scene: 'Escolha outro cenário' };
export function reuseDraft(P, kind) {
  if (!isFalProduction(P) || !REUSE_LABEL[kind]) return null;
  const refs = (P.sheet && P.sheet.references) || [];
  const photo = refs.find((r) => r && r.url) || null;
  const scene = (P.fal && P.fal.scene) || P.scene || null, platform = (P.fal && P.fal.platform) || P.platform || null;
  return { kind, scene, platform, name: cleanName((P.product && P.product.name) || ''), photoUrl: photo ? photo.url : null,
    original: { scene, platform } };
}
export const reuseBlocked = (reuse, scene, platform) => !!reuse && (reuse.kind === 'platform' ? platform === reuse.original.platform : scene === reuse.original.scene);
// Nome do arquivo da foto reaproveitada (precisa de extensão válida para a validação do envio).
export function reuseFileName(url, mime) {
  const m = /\.(jpe?g|png|webp)(?:$|\?)/i.exec(String(url || ''));
  if (m) return `foto.${m[1].toLowerCase()}`;
  return /png/i.test(mime || '') ? 'foto.png' : /webp/i.test(mime || '') ? 'foto.webp' : 'foto.jpg';
}

// Linhas do "Seu próximo vídeo" no motor fal.ai (o resumo do servidor traz engine/scene/platform).
export function falSummaryRows(sm, credits) {
  const rows = [['Produto', sm.product || 'A partir da sua foto'], ['Cenário', (SCENES.find((s) => s.id === sm.scene) || {}).label || '—'], ['Plataforma', (PLATFORMS.find((p) => p.id === sm.platform) || {}).label || '—'],
    ['O que você recebe', 'Vídeo de ~15 s (vertical, com narração) + 1 foto publicitária + título e legenda'],
    ['Custo total autorizado', credits(sm.total_credits) + (sm.total_brl ? ` (≈ R$ ${sm.total_brl})` : '')],
    ['Saldo atual', sm.exempt ? 'Conta isenta' : credits(sm.balance)]];
  if (!sm.exempt) rows.push(['Saldo depois de reservar', credits(sm.balance_after)]);
  return rows;
}
