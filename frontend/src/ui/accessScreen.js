// Sem sessão: qual tela o app mostra. `landing` é a URL pública da landing vinda de /api/config (STUDIO_LANDING_HOST):
// null = config ainda não chegou; '' = sem landing externa (a Landing interna do SPA continua valendo); 'https://…' = a landing
// vive só lá, então o app nunca renderiza a Landing e cai no login. O destino vem só da configuração, nunca da URL da página.
export function accessScreen({ entry, landing, resetToken }) {
  if (resetToken) return { kind: 'auth', entry, landingUrl: landing || '' };
  if (entry) return { kind: 'auth', entry, landingUrl: landing || '' };
  if (landing === null) return { kind: 'wait' };
  if (landing) return { kind: 'auth', entry: 'login', landingUrl: landing };
  return { kind: 'landing' };
}
