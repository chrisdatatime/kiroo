import React from 'react';
import { CloseButton } from './bits.jsx';
import { WORLD, setWorld } from '../game/worldFlag.js';

// Sobre e créditos da arte (o crédito do tileset LimeZu é exigido pela licença; texto igual ao CREDITS.md).
// Não confundir com ui/Credits.jsx, que é o saldo de créditos do estúdio.
export function AboutContent() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, font: '600 14px/1.45 Nunito Sans,sans-serif' }}>
      <p style={{ margin: 0 }}>Pivoo: seu estúdio ganha vida.</p>
      <div className="g-card" style={{ padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span className="g-label">Arte da sede</span>
        <span>
          Tileset: Modern Interiors e Modern Office por LimeZu,{' '}
          <a href="https://limezu.itch.io/moderninteriors" target="_blank" rel="noopener noreferrer">https://limezu.itch.io/moderninteriors</a>
        </span>
      </div>
      <div className="g-card" style={{ padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span className="g-label">Personagens e marca</span>
        <span>Personagens desenhados pela equipe Pivoo. Fonte Nunito Sans (SIL Open Font License).</span>
      </div>
    </div>
  );
}

export default function AboutWindow({ v }) {
  return (
    <section role="dialog" aria-labelledby="about-h" className="g-panel pop" style={{ position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', zIndex: 22, width: 'min(480px,calc(100vw - 24px))', padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <h2 id="about-h" className="fred" style={{ margin: 0, fontSize: 22, fontWeight: 600, flex: 1 }}>Sobre e créditos</h2>
        <CloseButton onClick={v.closeWin} label="Fechar sobre e créditos" />
      </div>
      <AboutContent />
      {/* feature flag da Fase 2 (SPEC-VIS-001): o renderizador antigo continua o padrão até a validação */}
      <div className="g-card" style={{ padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <span className="g-label">Visual da sede (teste)</span>
        <span className="g-muted" style={{ fontSize: 13 }}>
          Agora: {WORLD === 'phaser' ? 'mapa novo em tileset (só a sala de Edição por enquanto)' : 'visual atual'}. Trocar recarrega a página.
        </span>
        <button className="g-btn g-sm" style={{ minHeight: 44, alignSelf: 'flex-start' }} onClick={() => setWorld(WORLD === 'phaser' ? 'canvas' : 'phaser')}>
          {WORLD === 'phaser' ? 'Voltar ao visual atual' : 'Testar o mapa novo'}
        </button>
      </div>
    </section>
  );
}
