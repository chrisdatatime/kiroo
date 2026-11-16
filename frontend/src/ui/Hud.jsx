import React from 'react';

// Interface discreta sobre o cenário: atalhos (Setores, Jogos, ajuda), a opção Levantar e os avisos.
export default function Hud({ v }) {
  return (
    <>
      <div style={{ position: 'absolute', top: 14, left: 14, right: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap', pointerEvents: 'none', zIndex: 10 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', pointerEvents: 'auto', flexWrap: 'wrap', justifyContent: 'flex-end', marginLeft: 'auto' }}>
          {v.conn === 'erro' && <div className="g-hud" role="alert" style={{ padding: '0 12px', minHeight: 44, display: 'flex', alignItems: 'center', font: '800 13px/1.2 Instrument Sans,sans-serif', color: '#9A2E22' }}>Sem conexão com o estúdio</div>}
          {!v.shell && <div className="g-hud" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0 12px', minHeight: 44 }} title="Saldo de créditos do estúdio">
            <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8" fill="#F5C542" stroke="#0E0E10" strokeWidth="2" /><path d="M10 6v8M7.5 8.2h4a1.6 1.6 0 010 3.2h-3a1.6 1.6 0 000 3.2h4" fill="none" stroke="#0E0E10" strokeWidth="1.6" strokeLinecap="round" /></svg>
            <span style={{ font: '800 13px/1 Instrument Sans,sans-serif', fontVariantNumeric: 'tabular-nums' }}>{v.spentText}</span>
            {v.mode === 'simulated' && <span className="g-sim">DEMO</span>}
          </div>}
          <button className="g-btn g-sm g-lime" onClick={v.openSectors} style={{ minHeight: 44 }}>Setores{v.rooms.some((r) => r.need) ? ` (${v.rooms.filter((r) => r.need).length})` : ''}</button>
          {!v.shell && <button className="g-btn g-sm" onClick={v.openPilot} style={{ minHeight: 44 }} aria-label={'Piloto: ' + v.pilot.label + '. Mudar autonomia'}>Piloto: {v.pilot.label}</button>}
          <button className="g-btn g-sm" onClick={v.openGames} style={{ minHeight: 44 }}>Jogos</button>
          {!v.shell && <button className="g-btn g-sm" onClick={v.openBoard} style={{ minHeight: 44 }}>Produções</button>}
          <button className="g-btn g-sm g-icon" onClick={v.toggleHelp} aria-label="Como jogar" style={{ minHeight: 44, width: 44 }}>?</button>
          {!v.shell && <button className="g-btn g-sm" onClick={v.openAccount} style={{ minHeight: 44 }} aria-label={'Minha conta: ' + (v.account ? v.account.user.name : '')}>{v.account ? v.account.user.name.split(' ')[0] : 'Conta'}</button>}
        </div>
      </div>

      {/* a equipe fica na faixa abaixo do mapa (shell/Office.jsx) e o "E · Falar com" é um balão sobre o boneco (WorldPhaser);
          aqui sobra só a segunda opção quando você está sentado perto de algo (Levantar) */}
      {v.near && v.nearAlt && (
        <div className="popb" style={{ position: 'absolute', left: '50%', bottom: 64, transform: 'translateX(-50%)', zIndex: 11, display: 'flex', gap: 8 }}>
          <button className="g-btn" onClick={v.nearAlt.go} style={{ minHeight: 44 }}>{v.nearAlt.label}</button>
        </div>
      )}

      {v.toast && (
        <div role="status" className="g-hud popb" style={{ position: 'absolute', left: '50%', top: 84, transform: 'translateX(-50%)', zIndex: 30, padding: '10px 16px', font: '800 14px/1.3 Instrument Sans,sans-serif', display: 'flex', gap: 10, alignItems: 'center', maxWidth: 'calc(100vw - 32px)' }}>
          <span aria-hidden="true" style={{ width: 10, height: 10, borderRadius: '50%', background: '#FF5B2E', border: '1px solid #E7E7E4', flex: 'none' }} />{v.toast}
        </div>
      )}
    </>
  );
}
