// Traduz o estado REAL do motor (/api/state) para as etapas do jogo (STAGES em game/data.js).
// Nada aqui é simulado: se o motor estiver em modo DEMO, isso aparece em `mode`.

const IMG = {
  pending: 'none', generating_image: 'gerando', awaiting_image_approval: 'pronta', image_approved: 'aprovada',
  generating_video: 'aprovada', awaiting_video_approval: 'aprovada', video_approved: 'aprovada',
};
const VID = { generating_video: 'gerando', awaiting_video_approval: 'pronta', video_approved: 'aprovada' };

export function sceneView(sc, goAhead) {
  let img = IMG[sc.status] || 'none';
  let vid = VID[sc.status] || 'none';
  if (sc.status === 'blocked') { if (sc.approved_image) { img = 'aprovada'; vid = 'pronta'; } else img = 'pronta'; }
  if (img === 'none' && (goAhead === 'images' || goAhead === 'videos' || goAhead === 'all')) img = 'fila';
  if (vid === 'none' && img === 'aprovada' && (goAhead === 'videos' || goAhead === 'all')) vid = 'fila';
  return {
    idx: sc.idx, title: sc.title, motion: sc.motion, seconds: sc.target_duration_s, criteria: sc.criteria || [],
    img, vid, blocked: sc.status === 'blocked', iv: Math.max(sc.image_attempts, 1), vv: Math.max(sc.video_attempts, 1),
    imgTries: sc.image_attempts, vidTries: sc.video_attempts, image: sc.image, video: sc.video,
  };
}

export function deriveStage(P) {
  if (!P) return 'produto';
  const st = P.status;
  if (st === 'completed') return 'exportado';
  if (st === 'awaiting_final_review') return 'entrega';
  if (st === 'editing') return 'montando';
  if (st === 'received' || st === 'awaiting_references') return 'produto';
  if ((st === 'validated' || st === 'scripted') && !P.creative) return 'direcao';
  if (st === 'validated' || st === 'scripted') return 'direcao';
  if (P.gate === 'images') return 'gerar_img';
  if (P.gate === 'videos') return 'gerar_vid';
  const sc = P.scenes.map((x) => sceneView(x, P.go_ahead));
  const imgsDone = sc.length && sc.every((x) => x.img === 'aprovada');
  if (!imgsDone) return sc.some((x) => x.img === 'pronta') ? 'img_revisao' : (P.go_ahead === 'none' ? 'gerar_img' : 'img_gerando');
  if (sc.some((x) => x.vid === 'pronta')) return 'vid_revisao';
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
