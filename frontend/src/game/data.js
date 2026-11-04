// Dados da Pivoo: agentes, etapas e cenas. O mapa da sede vem de game/map.js (renderizador antigo) ou do
// assets/maps/office.tmj (Phaser, SPEC-VIS-001 Fase 2), conforme a flag em game/worldFlag.js.
import * as OLD from './map.js';
import { WORLD } from './worldFlag.js';
import { buildWorld } from './world/tmjWorld.js';
import officeRaw from '../../../assets/maps/office.tmj?raw';

export const TMJ = WORLD === 'phaser' ? JSON.parse(officeRaw) : null;
const M = TMJ ? buildWorld(TMJ, OLD.ROOMS) : OLD;

export const { GRID, ROOMS, CHAIRS, FURNITURE, INTERACT, BLOCKED, SPOTS, SPAWN } = M;
export { COMMON, WALLS, DOORS, RUGS, WALL_DECOR, LOGO_WALL, MY_DESK, MY_SEAT, BOARD, COFFEE, GAMES_TILE, MUSIC_SHELF, tilesOf } from './map.js';
export { WORLD };

export const AGENTS = [
  { id: 'nina', name: 'Nina', role: 'Preparação', tab: 'produto', mug: '#FF8FC0', look: { shirt: '#FF8FC0', acc: 'bone' } },
  { id: 'theo', name: 'Theo', role: 'Direção criativa', tab: 'direcao', mug: '#FF9A3D', look: { shirt: '#FF9A3D', acc: 'oculos' } },
  { id: 'iris', name: 'Iris', role: 'Imagens', tab: 'imagens', mug: '#B6E84A', look: { shirt: '#B6E84A', acc: 'fones' } },
  { id: 'rui', name: 'Rui', role: 'Revisão', tab: 'revisao', mug: '#4FD0BF', look: { shirt: '#4FD0BF', acc: 'oculos' } },
  { id: 'lia', name: 'Lia', role: 'Vídeos', tab: 'videos', mug: '#A88BF0', look: { shirt: '#A88BF0', acc: 'fones' } },
  { id: 'beto', name: 'Beto', role: 'Edição', tab: 'entrega', mug: '#4A7BF0', look: { shirt: '#4A7BF0', acc: 'boina' } },
];

// Cada agente trabalha na própria sala: mesa e cadeira vêm do mapa. No mapa novo, quem ainda não tem sala
// (Fase 2b) fica com seat = null: não aparece no mundo, mas segue no HUD, na equipe e nas janelas.
AGENTS.forEach((a) => {
  const r = ROOMS.find((x) => x.agent === a.id);
  a.room = r ? r.id : null;
  a.seat = r && r.placed !== false && r.seat ? r.seat : null;
  a.desk = r && r.desk ? [r.desk.x + 1, r.desk.y] : null;
});

export const TABS = [
  { id: 'produto', label: 'Produto', agent: 'nina' },
  { id: 'direcao', label: 'Direção', agent: 'theo' },
  { id: 'imagens', label: 'Imagens', agent: 'iris' },
  { id: 'revisao', label: 'Revisão', agent: 'rui' },
  { id: 'videos', label: 'Vídeos', agent: 'lia' },
  { id: 'entrega', label: 'Entrega', agent: 'beto' },
];

// Máquina de estados da produção
export const STAGES = ['produto', 'direcao', 'gerar_img', 'img_gerando', 'img_revisao', 'gerar_vid', 'vid_gerando', 'vid_revisao', 'montando', 'entrega', 'exportado'];

export const STAGE_LABELS = {
  produto: 'Preparando o produto', direcao: 'Definindo a direção', gerar_img: 'Aguardando você liberar as imagens',
  img_gerando: 'Criando imagens', img_revisao: 'Revisão das imagens', gerar_vid: 'Pronto para animar',
  vid_gerando: 'Animando as cenas', vid_revisao: 'Revisão dos takes', montando: 'Montando o vídeo',
  entrega: 'Vídeo pronto para revisar', exportado: 'Exportado',
};
