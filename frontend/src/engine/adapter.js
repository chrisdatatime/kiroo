// Traduz o estado REAL do motor (/api/state) para as etapas do jogo (STAGES em game/data.js).
// Nada aqui é simulado: se o motor estiver em modo DEMO, isso aparece em `mode`.

const IMG = {
  pending: 'none', generating_image: 'gerando', awaiting_image_approval: 'pronta', image_approved: 'aprovada',
  generating_video: 'aprovada', awaiting_video_approval: 'aprovada', video_approved: 'aprovada',
};
const VID = { generating_video: 'gerando', awaiting_video_approval: 'pronta', video_approved: 'aprovada' };

// Missão encerrada sem entrega (cancelada ou falhou): nada roda, nada espera por você. null nas outras.
// Usa o `ended` do servidor e, se faltar (resposta antiga), o próprio status.
export function endedOf(P) {
  if (!P) return null;
  if (P.ended) return P.ended;
  return P.status === 'cancelled' || P.status === 'failed' ? P.status : null;
}

// Onde a missão parou (para mostrar o que já existe), sem nunca dizer que algo está "gerando".
export function stoppedAt(P) {
  if (!P || !P.scenes || !P.scenes.length) return P && P.creative ? 'direcao' : 'produto';
  return deriveStage({ ...P, status: 'producing', ended: null, gate: null, awaiting_direction: false });
}

export function sceneView(sc, goAhead, ended = null) {
  let img = IMG[sc.status] || 'none';
  let vid = VID[sc.status] || 'none';
  if (ended) {   // cena parada no meio: "Interrompida", nunca "Criando…" nem "Na fila"
    if (img === 'gerando') img = 'parada';
    if (vid === 'gerando') vid = 'parada';
  }
  // Bloqueada só é "pronta" se a tentativa atual saiu; sem material (falhou/esgotou) não há o que aprovar.
  const ok = (a) => !!(a && a.status === 'succeeded' && a.url);
  if (sc.status === 'blocked') {
    if (sc.approved_image) { img = 'aprovada'; vid = ok(sc.video) ? 'pronta' : 'falhou'; }
    else img = ok(sc.image) ? 'pronta' : 'falhou';
  }
  if (!ended && img === 'none' && (goAhead === 'images' || goAhead === 'videos' || goAhead === 'all')) img = 'fila';
  if (!ended && vid === 'none' && img === 'aprovada' && (goAhead === 'videos' || goAhead === 'all')) vid = 'fila';
  return {
    idx: sc.idx, title: sc.title, motion: sc.motion, seconds: sc.target_duration_s, criteria: sc.criteria || [],
    img, vid, blocked: sc.status === 'blocked', iv: Math.max(sc.image_attempts, 1), vv: Math.max(sc.video_attempts, 1),
    imgTries: sc.image_attempts, vidTries: sc.video_attempts, image: sc.image, video: sc.video,
    status: sc.status, candidates: sc.candidates || null,
  };
}

export function deriveStage(P) {
  if (!P) return 'produto';
  const st = P.status;
  const ended = endedOf(P);
  if (ended === 'cancelled') return 'cancelada';   // antes do resto: as cenas podem ter ficado em "gerando"
  if (ended === 'failed') return 'falhou';
  if (st === 'completed') return 'exportado';
  if (P.engine === 'fal') {   // motor fal.ai: sem cenas nem Direção; um workflow gera tudo e o Kiroo monta o pacote
    if (st === 'awaiting_final_review') return 'entrega';
    if (st === 'editing') return 'montando';
    return 'img_gerando';
  }
  if (P.awaiting_direction) return 'direcao';
  if (st === 'awaiting_final_review') return 'entrega';
  if (st === 'editing') return 'montando';
  if (st === 'received' || st === 'awaiting_references') return 'produto';
  if ((st === 'validated' || st === 'scripted') && !P.creative) return 'direcao';
  if (st === 'validated' || st === 'scripted') return 'direcao';
  if (P.gate === 'images') return 'gerar_img';
  if (P.gate === 'videos') return 'gerar_vid';
  const sc = P.scenes.map((x) => sceneView(x, P.go_ahead));
  const imgsDone = sc.length && sc.every((x) => x.img === 'aprovada');
  if (!imgsDone) return sc.some((x) => (x.img === 'pronta' || x.img === 'falhou')) ? 'img_revisao' : (P.go_ahead === 'none' ? 'gerar_img' : 'img_gerando');
  if (sc.some((x) => (x.vid === 'pronta' || x.vid === 'falhou'))) return 'vid_revisao';
  if (sc.every((x) => x.vid === 'aprovada')) return 'montando';
  return 'vid_gerando';
}

// Conversão US$ → créditos usando a política informada pelo servidor (mesma fórmula do backend).
export function toCredits(usd, pol) {
  if (!pol || !usd || usd <= 0) return 0;
  return Math.ceil(usd * pol.fx * pol.margin / pol.price_brl - 1e-9);
}
export function creditsToUsd(credits, pol) {
  if (!pol) return 0;
  return credits * pol.price_brl / (pol.fx * pol.margin);  // sem arredondar: o servidor reconverte com ceil
}
