import React from 'react';

// Ilustração neutra de cada formato da Direção (objeto genérico, sombra suave, tokens da marca).
// Se existir assets/direcao/<formato>.webp, a foto real aparece no lugar; senão, este SVG.
export function FormatArt({ hand = false, person = false, src = null }) {
  const [broken, setBroken] = React.useState(false);
  if (src && !broken) return <img src={src} alt="" width="120" height="90" onError={() => setBroken(true)} style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: 10 }} />;
  const ink = '#0E0E10', paper = '#FAFAF8', line = '#E7E7E4', muted = '#F2F2EF';
  return (
    <svg viewBox="0 0 120 90" width="120" height="90" aria-hidden="true" style={{ maxWidth: '100%' }}>
      <defs><filter id="fa-soft" x="-30%" y="-100%" width="160%" height="300%"><feGaussianBlur stdDeviation="3" /></filter></defs>
      <rect x="0" y="62" width="120" height="28" fill={line} />
      <ellipse cx="60" cy="68" rx="26" ry="5" fill={ink} opacity="0.16" filter="url(#fa-soft)" />
      {person && <g><circle cx="92" cy="24" r="10" fill={muted} stroke={ink} strokeWidth="2" /><path d="M76 62 C76 44 83 38 92 38 C101 38 108 44 108 62 Z" fill={paper} stroke={ink} strokeWidth="2" /></g>}
      <rect x="44" y="30" width="32" height="36" rx="6" fill={paper} stroke={ink} strokeWidth="2.5" />
      <rect x="44" y="30" width="32" height="9" rx="4" fill={muted} stroke={ink} strokeWidth="2.5" />
      {hand && <g fill={muted} stroke={ink} strokeWidth="2.5"><ellipse cx="38" cy="56" rx="9" ry="6" /><ellipse cx="82" cy="56" rx="9" ry="6" /></g>}
    </svg>
  );
}

export function Spinner({ size = 22, track = '#E3E7EE', color = '#17234B' }) {
  return (
    <svg className="spin" width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke={track} strokeWidth="3" />
      <path d="M21 12a9 9 0 00-9-9" stroke={color} strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function CloseButton({ onClick, label }) {
  return (
    <button className="g-btn g-quiet g-sm g-icon" onClick={onClick} aria-label={label}>
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" /></svg>
    </button>
  );
}

export const S = { stroke: '#17234B', strokeLinejoin: 'round' };
