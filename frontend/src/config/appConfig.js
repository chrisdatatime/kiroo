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

// Página de Planos (Fase 6): view `planos` com URL própria.
export const PRICING_PATH = '/pricing';

// Planos: só mensais na v1. Com true, a chave Mensal/Anual aparece (o servidor também precisa de `annual_enabled` no
// catálogo e dos preços anuais da Stripe). Valores e créditos dos planos vêm do servidor (profiles/billing/catalog.json).
export const ANNUAL_TOGGLE = false;

// Textos da tela de Planos (design `Precos`/`CelPrecos`). `show: false` = marcado [confirmar] no design: fica fora
// da tela até alguém confirmar. `phone: false` = só no desktop (o design do celular tem menos perguntas).
export const PRICING_COPY = {
  title: 'Planos para vender com vídeo todo dia',
  welcomeTitle: 'Seu primeiro vídeo é por nossa conta',
  welcomeText: (n) => `Toda conta nova ganha ${n} créditos de boas-vindas. Sem cartão.`,
  welcomeTextPhone: (n) => `${n} créditos de boas-vindas. Sem cartão.`,
  topupTitle: 'Créditos avulsos',
  topupLead: 'Pagamento único, para quando o plano do mês acabar.',
  footnote: 'Preços em reais com impostos inclusos. Cobrança processada pela Stripe.',   // [confirmar] "impostos inclusos" com a contabilidade
  offline: 'A compra pelo site ainda não está disponível. Fale com a equipe para liberar créditos.',
};
export const PRICING_FAQ = [
  { q: 'Qual a diferença entre créditos do plano e créditos avulsos?',
    a: ['Os créditos do plano vêm com a assinatura e renovam no início de cada ciclo. Os que sobram não passam para o mês seguinte.',
      'Os avulsos são comprados à parte, são usados só depois que os do plano acabam e não expiram enquanto a sua conta estiver ativa.'] },
  { q: 'Quanto custa cada vídeo?', a: ['Todo vídeo usa 20 créditos, sempre o mesmo valor. Antes de confirmar, o Kiroo mostra o custo e o seu saldo.'] },
  { q: 'Quais formas de pagamento são aceitas?', a: ['Pix e cartão de crédito. Os pagamentos são processados pela Stripe, e o Kiroo não guarda os dados do seu cartão.'] },
  { q: 'E se a produção der erro?', a: ['Se o vídeo falhar por erro técnico, os 20 créditos voltam sozinhos para o seu saldo. Você vê a devolução no extrato.'] },
  { q: 'Como cancelo minha assinatura?', a: ['A qualquer momento, em Configurações › Créditos › Gerenciar assinatura. O plano continua ativo até o fim do período já pago e não renova. Não há reembolso proporcional do período pago, ressalvados os direitos previstos em lei, e os vídeos que você fez continuam seus.'] },
  { q: 'Posso pedir reembolso?', show: false,   // [REVISAR COM O ADVOGADO] mesma regra dos Termos (seção 6); só mostrar depois da revisão
    a: ['Você pode desistir em até 7 dias da compra e receber o valor integral, mesmo que já tenha usado créditos dela. Depois disso, não há reembolso por simples desistência de créditos já consumidos, ressalvados os direitos previstos em lei. Peça em suporte@kiroo.io.'] },
  { q: 'De quem são os vídeos?', phone: false, a: ['Seus para usar comercialmente: vender, anunciar e divulgar seus produtos, respeitando direitos de terceiros. Como são gerados por IA, não garantimos exclusividade.'] },
  { q: 'Posso trocar de plano?', phone: false, a: ['Sim. Ao subir de plano, a diferença de créditos entra na hora. Ao descer, a mudança vale no próximo ciclo.'] },
  { q: 'Preciso de nota fiscal?', phone: false, show: false,   // [confirmar com a contabilidade]
    a: ['Emitimos NFS-e para as cobranças efetivamente realizadas. Informar o CPF ou CNPJ em Minha conta é opcional.'] },
];

// Recursos que ainda não têm backend: aparecem desabilitados com "em breve".
export const FEATURES = {
  receipts: true,           // Recibos e "Gerenciar assinatura": Portal do cliente da Stripe (Fase 6; some com a compra desligada)
  emailNotifications: false, // preferências de e-mail
  googleUnlink: false,      // desconectar o login com Google
};

// Notas das barras por origem (Configurações › Créditos). Ordem de consumo: bônus → plano → avulso.
export const ORIGIN_NOTES = {
  bonus: 'Usado antes dos outros créditos',
  subscription: 'Renovam a cada ciclo e não acumulam',
  topup: 'Não expiram',
};

// Páginas legais: ficam na landing (`landing_url` do /api/config); sem ela, no próprio app.
export const LEGAL_PATHS = { terms: '/termos', privacy: '/privacidade', cookies: '/privacidade#p7-t' };

// Contato de suporte quando o servidor não informa nenhum.
export const SUPPORT_EMAIL_FALLBACK = 'suporte@kiroo.io';
export const PRIVACY_EMAIL = 'privacidade@kiroo.io';
