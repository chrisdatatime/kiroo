// Agentes fixos nas salas (Fase 6, só no mundo Phaser): cada agente fica na cadeira da própria estação.
// Nada de passeio, BFS ou spots de corredor: só o jogador navega. O canvas antigo continua com stepAgent do App.jsx.
//
// "Vida" dentro da cadeira: quando livre, troca a direção para onde olha a cada alguns segundos (aleatório, barato),
// sem sair do tile. Trabalhando olha o monitor (costas); precisando de você vira para a tela (balão "!").
export const IDLE_LOOKS = ['down', 'down', 'left', 'right'];
export const LOOK_MIN = 5, LOOK_SPAN = 9; // em passos de agente (1 passo = AGENT_EVERY * TICK = 1 s)

export function initialAgent(seat, rand = Math.random) {
  return { i: seat ? seat[0] : -1, j: seat ? seat[1] : -1, path: [], dir: 'down', rest: LOOK_MIN + Math.floor(rand() * LOOK_SPAN), moving: false };
}

// status: 'work' | 'need' | 'idle' | 'talk' (chat aberto). Sempre devolve o agente no assento, sem caminho.
export function stepSeated(seat, st, status, rand = Math.random) {
  if (!seat) return st;
  const base = { i: seat[0], j: seat[1], path: [], moving: false };
  if (status === 'work') return { ...base, dir: 'up', rest: st.rest };
  // precisa de você ou conversando com o jogador: vira para a tela
  if (status === 'need' || status === 'talk') return { ...base, dir: 'down', rest: st.rest };
  let rest = (st.rest == null ? LOOK_MIN : st.rest) - 1, dir = st.dir === 'up' ? 'down' : st.dir;
  if (rest <= 0) {
    dir = IDLE_LOOKS[Math.floor(rand() * IDLE_LOOKS.length)] || 'down';
    rest = LOOK_MIN + Math.floor(rand() * LOOK_SPAN);
  }
  return { ...base, dir, rest };
}
