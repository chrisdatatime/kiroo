// Configuração do app (novo layout). Tudo que o design marcou como [confirmar] ou [PREÇO] mora aqui, nunca no JSX.
// Flags desligadas escondem a opção na interface; ligar só quando o recurso existir de verdade.

// Aparência: o tema escuro não está desenhado. Com a flag desligada, o menu mostra só "Claro".
export const DARK_THEME_ENABLED = false;

// Preço do vídeo: fixo (regra do produto). O servidor também manda `settings.fal_offer`; a tela usa este número
// para "Cada vídeo usa N créditos" e "≈ N vídeos".
export const VIDEO_CREDITS = 20;

// Faixa no fim da tela do vídeo pronto (primeiro vídeo). Sem valores em reais. Ajuste os textos aqui.
export const NEXT_VIDEO_COPY = {
  text: 'Seu produto já tem um vídeo pronto para vender. Que tal dar o mesmo impulso ao próximo da sua loja?',
  cta: 'Criar outro vídeo',
};

// Página de planos (Fase 6). Até lá, /pricing abre a tela de compra que já existe.
export const PRICING_PATH = '/pricing';

// Recursos que ainda não têm backend: aparecem desabilitados com "em breve".
export const FEATURES = {
  receipts: false,          // Recibos (virá pelo portal do cliente da Stripe, Fase 6)
  emailNotifications: false, // preferências de e-mail
  googleUnlink: false,      // desconectar o login com Google
};

// Textos marcados [confirmar] no design (Configurações › Créditos, barras por origem).
export const ORIGIN_NOTES = {
  bonus: 'Usado antes dos outros créditos',   // [confirmar]
  granted: 'Liberados pela equipe Kiroo',       // [confirmar]
  purchased: 'Não expiram',                     // [confirmar]
};

// Páginas legais: ficam na landing (`landing_url` do /api/config); sem ela, no próprio app.
export const LEGAL_PATHS = { terms: '/termos', privacy: '/privacidade', cookies: '/privacidade#p7-t' };

// Contato de suporte quando o servidor não informa nenhum.
export const SUPPORT_EMAIL_FALLBACK = 'suporte@kiroo.io';
export const PRIVACY_EMAIL = 'privacidade@kiroo.io';   // [confirmar]
