import React from 'react';
import Boneco from '../Boneco.jsx';

// Interface discreta sobre o cenário: gasto, atalhos, equipe e dicas de controle.
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

      <div style={{ position: 'absolute', left: 14, bottom: 14, zIndex: 10 }} className="g-hud">
        <ul aria-label="Equipe" style={{ listStyle: 'none', margin: 0, padding: 6, display: 'flex', gap: 4 }}>
          {v.roster.map((r) => (
            <li key={r.id}>
              <button onClick={r.go} aria-label={r.aria} title={r.aria} style={{ position: 'relative', width: 48, height: 58, borderRadius: 12, border: '2px solid transparent', background: r.bg, cursor: 'pointer', padding: '3px 0 0', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3 }}>
                <span style={{ height: 30, overflow: 'hidden', display: 'block' }}><Boneco look={r.look} crop size={30} /></span>
                <span style={{ font: '800 10px/1 Instrument Sans,sans-serif', color: '#0E0E10' }}>{r.name}</span>
                <span aria-hidden="true" style={{ position: 'absolute', top: -4, right: -3, width: 16, height: 16, borderRadius: '50%', background: r.dot, border: '1px solid #E7E7E4', font: '900 10px/12px Instrument Sans,sans-serif', color: '#0E0E10', textAlign: 'center' }}>{r.sym}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      {v.near && (
        <div className="popb" style={{ position: 'absolute', left: '50%', bottom: 86, transform: 'translateX(-50%)', zIndex: 11, display: 'flex', gap: 8 }}>
          <button className="g-btn g-lime" onClick={v.useNear} style={{ minHeight: 48 }}><span className="kbd">E</span>{v.promptLabel}</button>
          {v.nearAlt && <button className="g-btn" onClick={v.nearAlt.go} style={{ minHeight: 48 }}>{v.nearAlt.label}</button>}
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
