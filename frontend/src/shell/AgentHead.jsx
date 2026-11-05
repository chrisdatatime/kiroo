import React from 'react';

// Cabeça do agente (mesma geometria do símbolo da marca) como indicador de estado.
// Laranja = trabalhando ou pedindo você (agente ativo); #C9C9C4 = livre ou em pausa. O texto ao lado nunca é laranja.
const HEAD = 'M104 -48H126A12 12 0 0 1 138 -36V-22A12 12 0 0 1 126 -10H104A12 12 0 0 1 92 -22V-36A12 12 0 0 1 104 -48ZM100 -36V-22H107V-36ZM123 -36V-22H130V-36Z';

export function AgentHead({ active, size = 12, className = '' }) {
  return (
    <svg className={`kiroo-head ${className}`} viewBox="92 -48 46 38" width={size} height={Math.round(size * 38 / 46)} aria-hidden="true"
      fill={active ? 'var(--kiroo-orange, #FF5B2E)' : 'var(--idle, #C9C9C4)'} fillRule="evenodd" focusable="false">
      <path d={HEAD} />
    </svg>
  );
}

// Estado do agente: cabeça de 12 px + rótulo em Geist Mono. state: 'work' | 'need' | 'wait' (livre/pausa).
export function AgentStatus({ state, children }) {
  const active = state === 'work' || state === 'need';
  return (
    <span className="kiroo-status" data-active={active || undefined} data-need={state === 'need' || undefined}>
      <AgentHead active={active} />{children}{state === 'need' && <b className="kiroo-status-need" aria-hidden="true">!</b>}
    </span>
  );
}
