// Preferências (Créditos e extrato, Minha conta, Sobre): regras puras das telas (tests/prefs.test.mjs).
// Os números e os selos já chegam prontos do servidor; aqui só a escolha do que mostrar.

// Selos do extrato: cor do texto / fundo (contraste AA sobre o fundo claro de cada selo).
export const STATUS_STYLE = {
  paid: { fg: '#166534', bg: '#DCFCE7' },          // Pago
  done: { fg: '#3A3935', bg: '#F1F0EC' },          // Concluído
  not_charged: { fg: '#9A3412', bg: '#FFEDD5' },   // Não cobrado
  gift: { fg: '#1E40AF', bg: '#DBEAFE' },          // Presente
  reversed: { fg: '#991B1B', bg: '#FEE2E2' },      // Estornado
};
export const STATUS_LABEL = { paid: 'Pago', done: 'Concluído', not_charged: 'Não cobrado', gift: 'Presente', reversed: 'Estornado' };

export function statusStyle(code) { return STATUS_STYLE[code] || STATUS_STYLE.done; }

// Cor do valor: entrada em verde, saída em preto, "0" (não cobrado) em cinza escuro.
export function amountTone(credits) {
  const t = String(credits || '0');
  if (t.startsWith('+')) return '#166534';
  if (t.startsWith('−') || t.startsWith('-')) return '#141414';
  return '#5F5E5A';
}

// "Nada reservado no momento" ou "N reservados para vídeos em andamento" (N inteiro, como o saldo).
export function reservedText(d) {
  const n = Number(String(d && d.held || '0').replace(/\./g, '')) || 0;
  if (!d || d.held_cc <= 0 || n <= 0) return 'Nada reservado no momento';
  return n === 1 ? '1 reservado para um vídeo em andamento' : `${d.held} reservados para vídeos em andamento`;
}

// Nome do plano em destaque, MAIÚSCULO: FREE, BÁSICO, PRO, ESTÚDIO.
export function planName(plan) {
  return String((plan && (plan.plan_label || plan.plan)) || 'Free').toUpperCase();
}

// Vantagens reais do plano (Free e Básico: nenhuma na lista).
export function planPerks(plan) {
  if (!plan || !plan.priority_queue) return [];
  const perks = ['Fila prioritária', 'Suporte por WhatsApp'];
  if (plan.early_access) perks.push('Acesso antecipado a novidades');
  return perks;
}

// "Precisa de ajuda?": Pro/Estúdio com WhatsApp configurado → WhatsApp; senão e-mail/contato (STUDIO_SUPPORT_CONTACT);
// sem nenhum dos dois → null (o card some).
export function helpCard(plan, site) {
  const wa = plan && plan.support && plan.support.whatsapp;
  if (planPerks(plan).length && wa) {
    return { kind: 'whatsapp', text: 'Fale com a gente direto pelo WhatsApp. Respondemos em horário comercial.', cta: 'Falar no WhatsApp', href: wa };
  }
  const c = site && site.contact;
  if (c) return { kind: 'email', text: 'Fale com a gente por e-mail', cta: c.href ? c.label : null, href: c.href || null, label: c.label };
  return null;
}

// CPF/CNPJ na lista: mascarado vem do servidor ("•••.•••.•••-25"); vazio → "Não informado" + "Adicionar".
export function taxDocRow(masked) {
  return masked ? { value: masked, action: 'Alterar' } : { value: 'Não informado', action: 'Adicionar' };
}

// Excluir conta: só libera digitando o e-mail da conta (sem diferenciar maiúsculas nem espaços nas pontas).
export function canDelete(typed, email) {
  const a = String(typed || '').trim().toLowerCase(), b = String(email || '').trim().toLowerCase();
  return !!b && a === b;
}

// Inicial do avatar: primeira letra do nome (ou do e-mail), maiúscula.
export function initialOf(user) {
  const s = String((user && (user.name || user.email)) || '?').trim();
  return (s[0] || '?').toLocaleUpperCase('pt-BR');
}

// Sobre: o que aparece conforme o ambiente. Item sem env some; o grid de atalhos se ajusta ao número de cards.
export function aboutCards(site, hasTour) {
  const s = site || {};
  const cards = [];
  if (s.help_url) cards.push({ id: 'help', title: 'Central de ajuda', desc: 'Guias e respostas', href: s.help_url });
  if (s.contact) cards.push({ id: 'contact', title: 'Fale com a gente', desc: s.contact.href ? 'Resposta em horário comercial' : s.contact.label, href: s.contact.href || null });
  if (hasTour) cards.push({ id: 'tour', title: 'Rever tutorial', desc: 'O tour pelo estúdio, do começo', action: 'tour' });
  return cards;
}

export function aboutLinks(site) {
  const s = site || {};
  const out = [];
  if (s.terms_url) out.push({ id: 'terms', title: 'Termos de uso', href: s.terms_url });
  if (s.privacy_url) out.push({ id: 'privacy', title: 'Política de privacidade', href: s.privacy_url });
  return out;
}

// "© 2026 Kiroo · {razão social} · CNPJ {cnpj}"; sem as envs, só "© 2026 Kiroo".
export function footerText(site, year = 2026) {
  const s = site || {};
  return [`© ${year} Kiroo`, s.legal_name || null, s.legal_cnpj ? `CNPJ ${s.legal_cnpj}` : null].filter(Boolean).join(' · ');
}
