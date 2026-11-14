import React from 'react';
import { Mail, MessageCircle } from 'lucide-react';

// Suporte conforme o plano (servidor: plans.view → account.plan.support). Pro e Escala: "Falar no WhatsApp" (link wa.me de
// STUDIO_SUPPORT_WHATSAPP; sem a variável, o servidor não manda o link e o botão não aparece). Demais: e-mail.
const LINK = { display: 'inline-flex', alignItems: 'center', gap: 6, textDecoration: 'none', whiteSpace: 'nowrap' };

export function SupportLinks({ plan, bare = false }) {
  const sup = plan && plan.support;
  if (!sup || (!sup.whatsapp && !sup.email)) return null;
  const links = sup.whatsapp
    ? <a className="pw-btn" style={LINK} href={sup.whatsapp} target="_blank" rel="noopener noreferrer"><MessageCircle size={15} aria-hidden="true" />Falar no WhatsApp</a>
    : <a className="pw-btn" style={LINK} href={`mailto:${sup.email}?subject=${encodeURIComponent('Suporte Kiroo')}`}><Mail size={15} aria-hidden="true" />Suporte por e-mail</a>;
  if (bare) return links;
  return <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}><span className="g-label">Ajuda</span>{links}</div>;
}
