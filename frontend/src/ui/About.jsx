import React from 'react';
import wordmark from '../assets/brand/wordmark-preto-laranja.svg';

// Sobre e créditos da arte (o crédito do tileset LimeZu é exigido pela licença).
// Não confundir com ui/Credits.jsx, que é o saldo de créditos do estúdio.
export function AboutContent({ v } = {}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, font: '500 14px/1.45 var(--font-sans)' }}>
      <img src={wordmark} alt="Kiroo" height="28" style={{ display: 'block', width: 'auto', height: 28, alignSelf: 'flex-start' }} />
      <p style={{ margin: 0 }}>Seu estúdio ganha vida.</p>
      <div className="g-card" style={{ padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span className="g-label">Arte da sede</span>
        <span>
          Tileset: Modern Interiors e Modern Office por LimeZu,{' '}
          <a href="https://limezu.itch.io/moderninteriors" target="_blank" rel="noopener noreferrer">https://limezu.itch.io/moderninteriors</a>
        </span>
      </div>
      {v && v.openTour && (
        <div className="g-card" style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <span style={{ flex: 1, minWidth: 180 }}>Quer ver de novo onde fica cada coisa?</span>
          <button type="button" className="g-btn g-sm" onClick={v.openTour}>Rever tutorial</button>
        </div>
      )}
    </div>
  );
}
