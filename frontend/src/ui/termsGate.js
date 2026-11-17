// Novo aceite dos Termos: o servidor devolve em /api/me `terms: { version, accepted, needs_accept }`. Sem aceitar a versão
// vigente nada gera vídeo nem compra (o servidor recusa com code 'terms_required'); esta tela só leva a pessoa ao aceite.
export const needsTerms = (account) => !!(account && account.terms && account.terms.needs_accept);
export const termsVersion = (account) => (account && account.terms && account.terms.version) || '';
export const isTermsRequired = (err) => !!(err && err.data && err.data.code === 'terms_required');
export const TERMS_LINKS = { terms: '/termos', privacy: '/privacidade' };
