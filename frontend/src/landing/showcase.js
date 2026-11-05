// Vitrine da home: os vídeos de exemplo, um por apresentação que o estúdio oferece de verdade
// (src/studio/creative_options.py → PRESENTATIONS). Cada item procura em src/assets/showcase/:
//   <id>.mp4 ou <id>.webm  → o vídeo (vertical 9:16, sem áudio obrigatório)
//   <id>.jpg ou <id>.webp  → o pôster (primeiro quadro); sem ele o navegador mostra o vídeo só ao carregar
// Sem arquivo, a home mostra o espaço reservado com o roteiro das três cenas, marcado como "Espaço para vídeo".
// Ao colocar um vídeo, marque `demo: true` se ele for material demonstrativo (não gerado numa produção real) e
// ajuste `made` com o que de fato foi escolhido naquela produção. Nada de produto, cliente ou número inventado.

const FILES = import.meta.glob('../assets/showcase/*.{mp4,webm,jpg,jpeg,webp,png}', { query: '?url', import: 'default', eager: true });
const byName = {};
for (const [path, url] of Object.entries(FILES)) {
  const file = path.split('/').pop();
  const id = file.replace(/\.\w+$/, '');
  const ext = file.split('.').pop().toLowerCase();
  byName[id] = byName[id] || {};
  if (ext === 'mp4' || ext === 'webm') byName[id].video = url;
  else byName[id].poster = url;
}

const BASE = [
  {
    id: 'produto',
    label: 'Produto em destaque',
    short: 'Produto',
    purpose: 'Para apresentar o produto sozinho, com o movimento vindo da câmera.',
    desc: 'Só o produto em cena, sem pessoas. Bom para catálogo, anúncio e vitrine de loja.',
    scenes: ['Apresentação do produto inteiro', 'Planos próximos dos detalhes', 'Fechamento para capa'],
    made: [['Proposta', 'Apresentar detalhes'], ['Ambiente', 'Mesa de trabalho organizada'], ['Tom', 'Leve e luminoso'], ['Edição', 'Limpo']],
  },
  {
    id: 'maos',
    label: 'Somente mãos',
    short: 'Mãos',
    purpose: 'Para mostrar o produto sendo usado, sem rosto e sem fala.',
    desc: 'Mãos seguram, giram e apoiam o produto em gestos do dia a dia. É a sugestão padrão do estúdio.',
    scenes: ['Mãos apresentam o produto', 'Detalhes nas mãos', 'Produto apoiado no ambiente'],
    made: [['Proposta', 'Mostrar na prática'], ['Ambiente', 'Cozinha com luz natural'], ['Tom', 'Natural e próximo'], ['Edição', 'Dinâmico']],
  },
  {
    id: 'apresentadora',
    label: 'Com apresentadora',
    short: 'Apresentadora',
    tag: 'Experimental',
    purpose: 'Para dar um rosto ao produto, sem fala.',
    desc: 'Uma apresentadora virtual segura o produto e olha para a câmera. Experimental: o rosto pode variar entre as cenas.',
    scenes: ['Apresentadora com o produto', 'Detalhes nas mãos', 'Fechamento com sorriso'],
    made: [['Proposta', 'Mostrar em uma rotina'], ['Ambiente', 'Sala de estar clara'], ['Tom', 'Sofisticado e calmo'], ['Edição', 'Suave']],
  },
];

export const SHOWCASE = BASE.map((it) => ({ ...it, demo: true, ...byName[it.id] }));
export const HAS_VIDEO = SHOWCASE.some((it) => it.video);
