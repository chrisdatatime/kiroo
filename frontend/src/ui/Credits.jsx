import React from 'react';
import { Spinner } from './bits.jsx';
import { getJSON } from '../engine/api.js';

// Créditos do estúdio: saldo, consumo por produção/etapa e extrato (livro-razão do servidor).
const when = (iso) => {
  try { return new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); }
  catch { return iso; }
};

export function CreditsContent({ v }) {
  const [d, setD] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [tab, setTab] = React.useState('uso');
  React.useEffect(() => { getJSON('/api/credits').then(setD).catch((e) => setErr(e.message)); }, []);

  return (
    <div className="pref-stack">
      {err && <div role="alert" style={{ color: '#7A2218' }}>{err}</div>}
      {!d && !err && <div style={{ display: 'grid', placeItems: 'center', padding: 30 }}><Spinner /></div>}
      {d && (
        <>
          <div className="g-card" style={{ padding: '12px 14px', display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'baseline' }}>
            <div>
              <div className="g-label">Saldo</div>
              <div className="fred" style={{ fontSize: 28, fontWeight: 600 }}>{d.exempt ? 'Isento' : d.balance + ' créditos'}</div>
            </div>
            {d.held_cc > 0 && <div><div className="g-label">Reservado agora</div><div style={{ font: '700 15px Instrument Sans,sans-serif' }}>{d.held} créditos</div></div>}
            <p className="g-muted" style={{ margin: 0, fontSize: 12.5, lineHeight: 1.45, flex: '1 1 220px' }}>
              {d.exempt
                ? 'Conta do dono: o consumo é registrado, mas não precisa de saldo.'
                : 'Antes de cada passo pago o estúdio reserva a estimativa; ao terminar, cobra o custo e devolve a diferença. Recusas sem custo são estornadas.'}
            </p>
          </div>
          <div role="tablist" aria-label="Detalhes dos créditos" style={{ display: 'flex', gap: 6 }}>
            <button role="tab" className="g-chip" aria-selected={tab === 'uso'} aria-pressed={tab === 'uso'} onClick={() => setTab('uso')}>Consumo por produção</button>
            <button role="tab" className="g-chip" aria-selected={tab === 'extrato'} aria-pressed={tab === 'extrato'} onClick={() => setTab('extrato')}>Extrato</button>
          </div>
          <div style={{ overflow: 'auto', minHeight: 80, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {tab === 'uso' && (d.usage.length === 0
              ? <p className="g-muted" style={{ margin: 0 }}>Nenhum crédito usado ainda. Produções em DEMO não consomem créditos.</p>
              : d.usage.map((u) => (
                <div key={u.production_id} className="g-card" style={{ padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <strong style={{ flex: 1, fontSize: 14 }}>{u.product || u.production_id}</strong>
                    <span style={{ font: '800 14px Instrument Sans,sans-serif' }}>{u.total} créditos</span>
                  </div>
                  <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 2 }}>
                    {u.stages.map((s) => (
                      <li key={s.stage} style={{ display: 'flex', fontSize: 13 }}>
                        <span style={{ flex: 1 }}>{s.stage} <span className="g-muted">({s.calls} {s.calls === 1 ? 'chamada' : 'chamadas'})</span></span>
                        <span>{s.credits}</span>
                      </li>
                    ))}
                  </ul>
                  <button className="g-btn g-sm" style={{ alignSelf: 'flex-start' }} onClick={() => v.openProduction(u.production_id)}>Abrir produção</button>
                </div>
              )))}
            {tab === 'extrato' && (d.statement.length === 0
              ? <p className="g-muted" style={{ margin: 0 }}>Sem lançamentos ainda.</p>
              : (
                <ul style={{ margin: 0, padding: 0, listStyle: 'none' }}>
                  {d.statement.map((e) => (
                    <li key={e.id} style={{ display: 'flex', gap: 10, padding: '8px 2px', borderBottom: '2px dotted #E7E7E4', fontSize: 13 }}>
                      <span className="g-muted" style={{ width: 82, flex: 'none' }}>{when(e.at)}</span>
                      <span style={{ flex: 1 }}>
                        <strong>{e.label}</strong>{e.stage ? ' · ' + e.stage : ''}
                        {(e.product || e.note) && <span className="g-muted"> — {[e.product, e.note].filter(Boolean).join(' · ')}</span>}
                      </span>
                      <span style={{ fontWeight: 800, color: e.amount_cc > 0 ? '#205C2E' : e.amount_cc < 0 ? '#0E0E10' : '#77777C' }}>
                        {e.amount_cc > 0 ? '+' : ''}{e.amount}
                      </span>
                    </li>
                  ))}
                </ul>
              ))}
          </div>
          {!d.exempt && <p className="g-muted" style={{ margin: 0, fontSize: 12 }}>A compra de créditos chega com os planos. Por enquanto, os créditos são liberados pelo administrador.</p>}
        </>
      )}
    </div>
  );
}
