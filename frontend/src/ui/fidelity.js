// Fidelidade ao produto na revisão: lógica pura (testada em tests/fidelity.test.mjs).
// - versões lado a lado quando as tentativas automáticas acabam (aprovar a melhor com um clique);
// - imagem-âncora do produto (referência principal das próximas cenas);
// - conferência do Rui com gravidade: produto errado bloqueia, mão/estética só avisa;
// - sugestão de "Produto em destaque" para produto assimétrico/complexo.

const lastAuto = (att) => (att && att.reviews ? att.reviews.filter((r) => String(r.reviewer || '').startsWith('auto:')).slice(-1)[0] : null) || null;

// Versões da cena para comparar. Só aparece com 2+ versões e quando há decisão a tomar (bloqueada ou aguardando).
export function sideBySide(scene, kind, running = false) {
  if (!scene || !scene.candidates) return null;
  const stage = kind === 'vid' || kind === 'video' ? 'video' : 'image';
  const list = scene.candidates[stage] || [];
  const deciding = scene.status === 'blocked' || scene.status === (stage === 'image' ? 'awaiting_image_approval' : 'awaiting_video_approval');
  if (list.length < 2 || !deciding) return null;
  return {
    stage,
    blocked: scene.status === 'blocked',
    items: list.map((a) => {
      const r = lastAuto(a);
      const critical = (r && r.critical_issues) || [];
      const warnings = (r && r.warnings) || [];
      return {
        id: a.id, no: a.no, url: a.url, video: stage === 'video',
        verdict: !r ? 'sem conferência' : r.decision === 'approved' ? (warnings.length ? 'certo, com aviso' : 'parece certo') : r.decision === 'rejected' ? 'produto com problema' : 'inconclusivo',
        critical, warnings, canChoose: !running && !!a.url,
      };
    }),
  };
}

// Pode virar âncora: imagem gerada (não vídeo) que ainda vale; mostra se já é a âncora atual.
export function anchorInfo(P, scene, kind) {
  if (!P || !scene || kind !== 'img' || !scene.image || !scene.image.url || scene.image.status !== 'succeeded') return null;
  const cur = P.anchor || null;
  return { attemptId: scene.image.id, isAnchor: !!(cur && cur.attempt_id === scene.image.id), hasAnchor: !!cur, anchorScene: cur ? cur.scene : null };
}

// Texto da conferência do Rui com a gravidade nova.
export function reviewCheck(att, mode) {
  const auto = lastAuto(att);
  if (!auto) return null;
  const crit = (auto.critical_issues || []).join(' ');
  const warn = (auto.warnings || []).join(' ');
  if (auto.decision === 'approved') {
    return warn
      ? { title: 'Produto certo, com um aviso', text: 'O produto bate com a referência. Aviso (não bloqueia): ' + warn, bg: '#FFF4D6', warn: true }
      : { title: 'Parece certo', text: 'Produto, cor e formato parecem bater com a referência. Confira você também: minha conferência pode errar.', bg: '#E3F5DC' };
  }
  if (auto.decision === 'rejected') {
    return { title: 'Encontrei um problema no produto', text: crit || (auto.issues || []).join(' ') || 'Algo não bate com a referência.', bg: '#FFE1DC' };
  }
  const issues = (auto.issues || []).join(' ');
  return { title: 'Inconclusivo', text: (issues ? issues + ' ' : '') + (mode === 'simulated' ? 'Modo DEMO: não houve análise visual de verdade.' : 'Não tenho certeza. Compare com a referência.'), bg: '#FFE7C2' };
}

// Aviso de formato (prévia da Direção ou ficha técnica da produção) e se dá para trocar com um clique.
export function formatAdvice({ preview, production, presentation }) {
  const text = (preview && preview.format_advice && preview.format_advice.text) || (production && production.format_advice) || '';
  if (!text) return null;
  return { text, canSwitch: presentation === 'hands_only', suggested: 'product_only' };
}
