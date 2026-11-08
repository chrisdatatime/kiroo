// Login com Google: para onde o botão leva e quando ele pode ser usado. Lógica pura (tests/google-start.test.mjs).
// Entrar: só /api/auth/google/start (não cria conta). Criar conta: leva a intenção, o aceite dos Termos e, com
// STUDIO_SIGNUP=invite, o código de convite; o servidor guarda tudo junto do state e confere no retorno do Google.

export const GOOGLE_START = '/api/auth/google/start';

export function googleStart({ mode, signup, invite = '', consent = false }) {
  if (mode !== 'signup') return { href: GOOGLE_START, ready: true, need: null };
  const code = String(invite || '').trim();
  if (signup === 'invite' && !code) return { href: null, ready: false, need: 'Para criar com Google, preencha o código de convite e aceite os Termos.' };
  if (!consent) return { href: null, ready: false, need: 'Para criar com Google, aceite os Termos de Uso e a Política de Privacidade.' };
  const q = new URLSearchParams({ intent: 'signup', consent: '1' });
  if (signup === 'invite') q.set('invite', code);
  return { href: `${GOOGLE_START}?${q}`, ready: true, need: null };
}

// Códigos que o servidor devolve em /?entrar&erro=<código>.
export const GOOGLE_ERRORS = {
  google_off: 'O login com Google não está ativo neste estúdio.',
  google_cancel: 'O login com Google foi cancelado.',
  google_state: 'O login com Google expirou antes de terminar. Tente de novo.',
  google_failed: 'Não conseguimos falar com o Google agora. Tente de novo em instantes.',
  google_unverified: 'O Google não confirmou este e-mail. Entre com e-mail e senha.',
  google_consent: 'Para criar a conta com Google, use Criar conta e aceite os Termos de Uso e a Política de Privacidade.',
  google_other: 'Este e-mail já está ligado a outra conta Google. Entre com ela ou com e-mail e senha.',
  google_throttled: 'Muitas tentativas de convite. Espere alguns minutos e tente de novo.',
  convite: 'Não há conta com este e-mail. O acesso é por convite: em Criar conta, informe seu código de convite.',
  convite_invalido: 'Código de convite inválido, já usado, expirado ou de outro e-mail.',
};
