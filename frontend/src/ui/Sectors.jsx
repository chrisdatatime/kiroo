import React from 'react';
import Boneco from '../Boneco.jsx';
import { CloseButton } from './bits.jsx';

// Acesso rápido: pendências e setores da sede, sem precisar caminhar.
export default function SectorsWindow({ v }) {
  const pend = v.rooms.filter((r) => r.need);
  return (
    <section role="dialog" aria-labelledby="sec-h" className="g-panel" style={{ position: 'absolute', left: 14, top: 84, bottom: 92, zIndex: 20, width: 'min(380px,calc(100vw - 28px))', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 10, borderBottom: '1px solid #E7E7E4', background: '#F2F2EF' }}>
        <h2 id="sec-h" className="fred" style={{ margin: 0, fontSize: 20, flex: 1 }}>Setores</h2>
        <CloseButton onClick={v.closeWin} label="Fechar setores" />
      </div>
      <div style={{ overflowY: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
        {pend.length > 0 && <p style={{ margin: 0, font: '800 13px/1.3 Instrument Sans,sans-serif' }}>{pend.length === 1 ? '1 pendência precisa de você' : pend.length + ' pendências precisam de você'}</p>}
        {[...pend, ...v.rooms.filter((r) => !r.need)].map((r) => (
          <article key={r.id} className="g-card" style={{ padding: 10, display: 'flex', gap: 10, alignItems: 'center', background: r.need ? '#FFFFFF' : '#fff' }}>
            {r.look && <span aria-hidden="true" style={{ width: 42, height: 42, borderRadius: 11, background: r.look.shirt, border: '1px solid #E7E7E4', overflow: 'hidden', display: 'grid', placeItems: 'end center', flex: 'none' }}><Boneco look={r.look} crop size={36} /></span>}
            <div style={{ flex: 1, minWidth: 0 }}>
              <strong className="fred" style={{ display: 'block', fontSize: 15 }}>{r.name}{r.who ? ' · ' + r.who : ''}</strong>
              <span className="g-muted" style={{ display: 'block', fontSize: 12.5, fontWeight: 700 }}>{r.status}</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <button className={r.need ? 'g-btn g-lime g-sm' : 'g-btn g-sm'} onClick={r.work}>{r.need ? 'Resolver' : 'Abrir'}</button>
              <button className="g-btn g-quiet g-sm" onClick={r.go}>Ir à sala</button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
