// Paleta clara do mundo Phaser com os tokens Kiroo. Espelha --pw-* de styles.css: o Phaser desenha em canvas e não lê CSS.
// Fundo fora do mapa: #E9E8E4 (--kiroo-canvas). Para comparar com o menta antigo, abra o mundo com ?fundo=menta.
const MINT = '#D7F3DC', CANVAS = '#E9E8E4';
const mint = () => { try { return new URLSearchParams(window.location.search).get('fundo') === 'menta'; } catch { return false; } };
export const PW = {
  bg: mint() ? MINT : CANVAS, // fundo do mundo fora do mapa
  surface: 0xFFFFFF,
  border: 0xE7E7E4,
  text: '#0E0E10',          // tinta
  primary: 0x0E0E10,        // destaque da pill (você / perto): tinta
  primaryText: '#FAFAF8',
  shadow: 0x0E0E10,
};
