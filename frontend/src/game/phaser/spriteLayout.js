// Conferência das folhas Kiroo dos agentes (assets/characters/{nina,theo,iris,rui,lia,beto}.png).
// As folhas atuais são uma grade exata de 16 colunas x 48 linhas de quadros 32x32 (512x1536), carregada pelo Phaser como
// spritesheet normal (OfficeScene: frameWidth/frameHeight de sprites.js). Não há mais recorte por transparência.
import { KIROO_FW, KIROO_FH, KIROO_COLS } from './sprites.js';

export const KIROO_SHEET_ROWS = 48;
export const KIROO_SHEET_SIZE = { width: KIROO_FW * KIROO_COLS, height: KIROO_FH * KIROO_SHEET_ROWS };

// Lê {data, width, height} (RGBA) e devolve o mapa de quadros ocupados. Lança erro se a folha não for a grade esperada.
export function inspectKirooSheet({ data, width, height }) {
  if (width !== KIROO_SHEET_SIZE.width || height !== KIROO_SHEET_SIZE.height) {
    throw new Error(`Folha KIROO: esperado ${KIROO_SHEET_SIZE.width}x${KIROO_SHEET_SIZE.height}, recebido ${width}x${height}`);
  }
  const frames = [];
  for (let row = 0; row < KIROO_SHEET_ROWS; row++) {
    for (let col = 0; col < KIROO_COLS; col++) {
      let top = KIROO_FH, bottom = -1, opaque = 0;
      for (let y = 0; y < KIROO_FH; y++) {
        for (let x = 0; x < KIROO_FW; x++) {
          if (data[((row * KIROO_FH + y) * width + col * KIROO_FW + x) * 4 + 3] > 127) { opaque++; top = Math.min(top, y); bottom = Math.max(bottom, y); }
        }
      }
      frames.push({ index: row * KIROO_COLS + col, row, col, opaque, top: opaque ? top : null, bottom: opaque ? bottom : null });
    }
  }
  return frames;
}
