import React from 'react';

// Ilustração do copo (placeholder — não é foto real do produto)
export function Cup({ fill, lid, width = 96, height = 112, sw = 3, hands = false, noHandle = false }) {
  return (
    <svg viewBox="0 0 120 140" width={width} height={height} aria-hidden="true">
      {!noHandle && <path d="M80 46 C104 46 104 98 78 100" fill="none" stroke="#17234B" strokeWidth="9" strokeLinecap="round" />}
      {!noHandle && <path d="M80 46 C104 46 104 98 78 100" fill="none" stroke={fill} strokeWidth="4" strokeLinecap="round" />}
      <path d="M32 32 L38 122 Q39 128 46 128 L66 128 Q73 128 74 122 L80 32 Z" fill={fill} stroke="#17234B" strokeWidth={sw} />
      <rect x="28" y="20" width="56" height="13" rx="4" fill={lid} stroke="#17234B" strokeWidth={sw} />
      <rect x="47" y="12" width="18" height="9" rx="2" fill="#17234B" />
      {hands && (
        <g>
          <ellipse cx="30" cy="104" rx="16" ry="10" fill="#F1C7A5" stroke="#17234B" strokeWidth="3" />
          <ellipse cx="84" cy="108" rx="15" ry="9" fill="#F1C7A5" stroke="#17234B" strokeWidth="3" />
          <path d="M20 100 l3 -2 M26 98 l3 -2" stroke="#E7A3A3" strokeWidth="3" strokeLinecap="round" />
        </g>
      )}
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
