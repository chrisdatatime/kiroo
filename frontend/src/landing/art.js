// Imagens da home geradas por tools/render_home.py a partir da arte LimeZu (fora do git).
// Sem os arquivos, o glob volta vazio e a home mostra superfícies neutras no lugar.
const FILES = import.meta.glob('../assets/home/*.{png,webp}', { query: '?url', import: 'default', eager: true });

export const ART = Object.fromEntries(Object.entries(FILES).map(([path, url]) => [path.split('/').pop().replace(/\.\w+$/, ''), url]));

// Ponto acima da cabeça de cada agente na sede.webp (38x32 tiles de 32 px), em % da imagem.
// Mesma conta do Phaser: pé em (j+1)*32-4, sprite 2x com o pé na linha 29 do quadro 32x32.
const SEATS = { nina: [2, 5], theo: [16, 5], iris: [30, 5], lia: [34, 17], rui: [16, 29], beto: [30, 29] };
export const AGENT_PINS = Object.fromEntries(Object.entries(SEATS).map(([id, [i, j]]) => [id, {
  x: +(((i + 0.5) * 32) / 1216 * 100).toFixed(2),
  y: +((((j + 1) * 32 - 4 - 58) / 1024) * 100).toFixed(2),
}]));
