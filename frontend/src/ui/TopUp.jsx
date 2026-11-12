import React from 'react';
import { getJSON } from '../engine/api.js';
import { safeHref } from './credits.js';

// "Adicionar créditos". Hoje é contato/instrução manual (ainda não há pagamento pelo site). Ponto de integração do
// Mercado Pago: quando `topup.online` vier verdadeiro com uma `checkout_url`, é aqui que o botão de pagar entra.
// Sem `topup` pronto (ex.: abertura pela tela de Créditos), busca em /api/credits/topup.
export function TopUp({ topup, missingCc = 0, onClose }) {
  const [t, setT] = React.useState(topup || null);
  const [err, setErr] = React.useState(null);
  React.useEffect(() => {
    if (topup) return;
    getJSON('/api/credits/topup?missing_cc=' + (missingCc || 0)).then(setT).catch((e) => setErr(e.message));
  }, [topup, missingCc]);
  if (err) return <div role="alert" style={{ color: '#7A2218', fontSize: 13 }}>{err}</div>;
  if (!t) return null;
  const href = t.contact && safeHref(t.contact.href);
  return (
    <section aria-label="Adicionar créditos" className="g-card" style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 8, background: '#fff' }}>
      <strong style={{ fontSize: 14 }}>{t.title || 'Adicionar créditos'}</strong>
      <span style={{ fontSize: 13.5, lineHeight: 1.45 }}>{t.message}</span>
      <ol style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.5 }}>{(t.steps || []).map((s, k) => <li key={k}>{s}</li>)}</ol>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        {href && <a className="g-btn g-sm g-lime" href={href} target="_blank" rel="noreferrer noopener">{t.contact.label}</a>}
        {!href && t.contact && <span style={{ font: '800 13px/1.3 Instrument Sans,sans-serif' }}>{t.contact.label}</span>}
        {onClose && <button className="g-btn g-sm" onClick={onClose}>Fechar</button>}
      </div>
    </section>
  );
}
