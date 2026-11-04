import React from 'react';
import { charSprite, CW, CH } from './game/pixel/characters.js';

// Retrato do personagem nas janelas e no HUD: o mesmo sprite em pixel art da sede, ampliado sem suavização.
// look: { shirt: cor do corpo, acc: 'nenhum'|'oculos'|'boina'|'bone'|'fones'|'faixa'|'broto', cap?: cor do chapéu }
// anim: 'idle' | 'walk' | 'type' | 'wave' | 'happy'. crop: só a parte de cima (retratos). back/turn: de costas ou de lado.
export const DEFAULT_LOOK = { shirt: '#D5F45B', acc: 'broto' };
const CROP_Y = 0, CROP_H = 19;

export default function Boneco({ look = DEFAULT_LOOK, anim = 'idle', size = 144, crop = false, back = false, turn = 0 }) {
  const ref = React.useRef(null);
  const dir = back ? 'up' : turn < 0 ? 'left' : turn > 0 ? 'right' : 'down';
  const pose = anim === 'happy' ? 'happy' : anim === 'wave' ? 'wave' : anim === 'walk' ? 'walk' : 'stand';
  const h = crop ? CROP_H : CH;
  React.useEffect(() => {
    const c = ref.current; if (!c) return;
    const x = c.getContext('2d'); x.clearRect(0, 0, CW, h);
    x.drawImage(charSprite(look, dir, pose, pose === 'walk' ? 1 : 0, { wide: anim === 'happy' }), 0, crop ? -CROP_Y : 0);
  });
  return <canvas ref={ref} width={CW} height={h} aria-hidden="true" style={{ display: 'block', width: (size * CW) / h, height: size, imageRendering: 'pixelated' }} />;
}
