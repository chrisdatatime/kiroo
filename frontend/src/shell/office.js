// Escritório (Fase 2 do novo layout): regras puras da tela, sem React nem DOM (tests/office.test.mjs).
// O mapa, o movimento e as poses continuam em App.jsx + game/phaser; aqui ficam só textos, estados e a regra das teclas.

// Estado do agente (v.statuses: idle | work | need) → palavra e tom mostrados no painel, na faixa da equipe e na gaveta.
export const AGENT_WORD = {
  idle: { word: 'Livre', tone: 'free' },
  work: { word: 'Trabalhando', tone: 'work' },
  need: { word: 'Precisa de você', tone: 'need' },
};
export function agentState(status) { return AGENT_WORD[status] || AGENT_WORD.idle; }

// Linha da equipe: "Preparação · livre" (o papel primeiro; quem precisa de você mostra só isso, em destaque)
export function teamLine(agent, status) {
  const st = agentState(status);
  return status === 'need' ? st.word : `${agent.role} · ${st.word.toLowerCase()}`;
}

// Selos do alto do mapa. waiting = produções esperando você (o mesmo número do menu lateral);
// live = alguma produção gerando agora (o mesmo critério do AO VIVO).
export function officeStatus({ statuses = {}, waiting = 0, live = false } = {}) {
  const busy = Object.values(statuses).filter((s) => s === 'work').length;
  const team = busy > 0
    ? { tone: 'work', title: busy === 1 ? '1 agente trabalhando' : `${busy} agentes trabalhando`, text: live ? 'produção gerando agora' : '' }
    : live ? { tone: 'work', title: 'Produção gerando', text: '' }
      : { tone: 'free', title: 'Equipe livre', text: 'nenhuma produção em andamento' };
  const need = waiting > 0 ? (waiting === 1 ? '1 vídeo espera você' : `${waiting} vídeos esperam você`) : '';
  return { team, need };
}

// Painel do agente (desktop) e gaveta (celular): o que está fazendo, a produção atual e o que dá para fazer.
// room = sala do agente (rooms do viewModel: status = o que faz agora, hint = do que a sala cuida).
export function agentPanel({ agent, status, room, hasProd, prodName }) {
  if (!agent) return null;
  const st = agentState(status);
  return {
    id: agent.id, name: agent.name, role: agent.role, look: agent.look,
    word: st.word, tone: st.tone,
    doing: (room && room.status) || (hasProd ? 'Sem tarefa agora' : 'Nenhuma produção aberta'),
    about: (room && room.hint) || '',
    production: hasProd ? (prodName || 'Produção atual') : '',
    // "Abrir produção" só existe com produção aberta; sem ela o painel oferece Nova produção
    canOpen: !!hasProd,
    primary: status === 'need' ? 'Resolver agora' : 'Abrir produção',
  };
}

// Quem o painel mostra: a escolha do usuário; senão (só na gaveta do celular) quem precisa de você.
export function pickAgent(team = [], statuses = {}, chosen = null, fallback = false) {
  if (chosen && team.some((a) => a.id === chosen)) return chosen;
  if (!fallback) return null;
  const need = team.find((a) => statuses[a.id] === 'need');
  return need ? need.id : null;
}

// Balão sobre o boneco quando há algo ao alcance: "E · Falar com Beto". Sem alvo, nada.
export function nearPrompt(label) { return label ? { key: 'E', label } : null; }

// Teclas de movimento (setas, WASD, E) só valem com o escritório focado: o próprio mapa (ou a raiz do app, que recebe o
// foco depois de um clique no mundo), nunca um campo, um menu, um diálogo aberto ou um botão da barra lateral.
export function officeKeys({ view, tag = '', editable = false, inMap = false, isRoot = false, inDialog = false } = {}) {
  if (view !== 'escritorio') return false;
  const t = String(tag).toLowerCase();
  if (editable || t === 'input' || t === 'textarea' || t === 'select') return false;
  if (inDialog) return false;
  return inMap || isRoot;
}

// Dica do rodapé do mapa: no celular é toque, no desktop teclado + clique.
export function officeHint(phone) {
  return phone ? 'Toque numa mesa para andar' : 'Ande com as setas ou WASD · clique numa mesa para ir até ela · E para falar';
}
