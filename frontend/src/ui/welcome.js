// Bônus de boas-vindas e convites para comprar: lógica pura (tests/welcome.test.mjs). Sem React.
// O servidor decide e concede o bônus (src/studio/welcome.py); `account.welcome` = {credits, granted_at} quando houve.

export const VIDEO_CC = 2000;   // 1 vídeo = 20 créditos (catálogo); em centésimos, como o livro
const READY = new Set(['awaiting_final_review', 'completed']);

export const NO_BALANCE_CREATE = 'Você já sabe o resultado. Escolha quantos vídeos quer fazer este mês.';
export const SEE_PACKS = 'Ver pacotes';

// Missões vazias depois do bônus: "Seus 20 créditos estão esperando..."
export function emptyMissionsCopy(account, productions) {
  const w = account && account.welcome;
  if (!w || (productions || []).length) return null;
  return { title: `Seus ${w.credits} créditos estão esperando.`,
    text: 'Solte a foto do seu produto e veja o vídeo pronto em 3 minutos.', cta: 'Criar meu primeiro vídeo' };
}

// Primeiro vídeo pronto e saldo abaixo de um vídeo: convite para os pacotes.
export function firstVideoCopy({ P, productions, wallet }) {
  if (!P || !READY.has(P.status) || !wallet || wallet.exempt) return null;
  if ((Number(wallet.balance_cc) || 0) >= VIDEO_CC) return null;
  const ready = (productions || []).filter((p) => READY.has(p.status)).length;
  if (ready !== 1) return null;
  return { text: 'Esse é o seu produto vendendo sozinho. Continue criando: no Pro, cada vídeo sai por R$ 6,66.', cta: SEE_PACKS };
}

// Erro ao criar: saldo insuficiente (402 com insufficient_credits) vira o convite para os pacotes.
export const isNoFunds = (e) => !!(e && (e.status === 402 || (e.data && e.data.insufficient_credits)));
