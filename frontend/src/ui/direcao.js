// Etapa Direção: lógica pura (testada em tests/direcao.test.mjs).
// O usuário escolhe só o formato e, se quiser, escreve um pedido livre. O resto é padrão fixo do servidor.

export const FORMAT_IDS = ['product_only', 'hands_only', 'presenter'];

// Fotos reais opcionais: public/assets/direcao/<formato>.webp. Sem o arquivo, a interface usa o SVG neutro.
export function formatPhotoUrl(id, base = '/') {
  if (!FORMAT_IDS.includes(id)) return null;
  const b = String(base || '/').endsWith('/') ? String(base || '/') : `${base}/`;
  return `${b}assets/direcao/${id}.webp`;
}

// Elementos que o SVG neutro desenha em cada formato.
export function formatArt(id) {
  return { hand: id === 'hands_only' || id === 'presenter', person: id === 'presenter' };
}

// Pedidos livres ficam em details_text separados por ";".
export function splitRequests(text) {
  return String(text || '').split(';').map((x) => x.trim()).filter(Boolean);
}

export function joinRequests(current, add) {
  const v = String(add || '').trim().replace(/;/g, ',');
  if (!v) return String(current || '');
  return [String(current || '').trim(), v].filter(Boolean).join('; ');
}

// Painel lateral: só o que ainda existe na tela.
export function summaryRows(presentations, creative) {
  const rows = [{ k: 'Formato', v: (presentations[creative.presentation] || {}).label || '' }];
  const reqs = splitRequests(creative.details_text);
  if (reqs.length) rows.push({ k: 'Pedidos', v: reqs.join('; ') });
  rows.push({ k: 'Áudio', v: 'Sem fala; o vídeo final sai com trilha silenciosa' });
  rows.push({ k: 'Duração', v: '~15 s · 3 cenas' });
  return rows;
}
