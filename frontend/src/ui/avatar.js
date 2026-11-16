// Avatar da conta: sempre um kiroo (o boneco em pixel art do escritório). O servidor guarda só o id (`user.avatar_kiroo`,
// sorteado na criação; ver ../../src/studio/avatars.py). A aparência de cada id mora aqui. Lógica pura
// (tests/avatar.test.mjs). Ids estáveis: só acrescente no fim.
export const KIROO_LOOKS = {
  k01: { shirt: '#D5F45B', acc: 'broto' },
  k02: { shirt: '#FF8FC0', acc: 'bone' },
  k03: { shirt: '#FF9A3D', acc: 'oculos' },
  k04: { shirt: '#B6E84A', acc: 'fones' },
  k05: { shirt: '#4FD0BF', acc: 'nenhum' },
  k06: { shirt: '#A88BF0', acc: 'faixa' },
  k07: { shirt: '#4A7BF0', acc: 'boina' },
  k08: { shirt: '#FFD23F', acc: 'broto' },
  k09: { shirt: '#FF6B6B', acc: 'fones' },
  k10: { shirt: '#7ED957', acc: 'oculos' },
  k11: { shirt: '#5BC0F8', acc: 'bone' },
  k12: { shirt: '#F49AC1', acc: 'faixa' },
};
export const KIROO_IDS = Object.keys(KIROO_LOOKS);
const FALLBACK = 'k01';

// Look do kiroo da conta. Sem id (servidor antigo) ou id desconhecido: o kiroo padrão, sem quebrar.
export function kirooLook(user) {
  const id = user && user.avatar_kiroo;
  return KIROO_LOOKS[id] || KIROO_LOOKS[FALLBACK];
}

// Fundo do círculo: a cor do kiroo bem clara (mesma ideia do Avatar dos agentes).
export function kirooTint(look) {
  return /^#[0-9a-f]{6}$/i.test(look && look.shirt) ? `${look.shirt}33` : '#FFE8E0';
}
