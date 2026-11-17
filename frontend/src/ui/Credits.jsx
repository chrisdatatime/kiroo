import React from 'react';
import { Download } from 'lucide-react';
import { Spinner } from './bits.jsx';
import { getJSON } from '../engine/api.js';
import { ADD_LABEL } from './credits.js';
import { TopUp } from './TopUp.jsx';
import { amountTone, planName, reservedText, statusStyle } from './prefs.js';
import './prefs.css';

// Créditos e extrato (Preferências). Saldo sempre inteiro (o livro guarda centésimos; o servidor já manda o texto).
// O cliente vê só extrato e "Por vídeo"; o detalhe por chamada/etapa é do admin.
const when = (iso) => {
  try { return new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' }); }
  catch { return iso; }
};

export function Badge({ code, label }) {
  const st = statusStyle(code);
  return <span className="pf-badge" style={{ color: st.fg, background: st.bg }}>{label}</span>;
}

export function StatementTable({ rows }) {
  if (!rows.length) return <p className="pf-empty">Sem lançamentos ainda.</p>;
  return (
    <>
      <table className="pf-table">
        <thead><tr><th scope="col">Data</th><th scope="col">Descrição</th><th scope="col">Status</th><th scope="col">Créditos</th></tr></thead>
        <tbody>
          {rows.map((e) => (
            <tr key={e.id}>
              <td className="pf-date">{when(e.at)}</td>
              <td><div className="pf-t1">{e.title}</div>{e.subtitle && <div className="pf-t2">{e.subtitle}</div>}</td>
              <td><Badge code={e.status} label={e.status_label} /></td>
              <td className="pf-amt" style={{ color: amountTone(e.credits) }}>{e.credits}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="pf-list pf-cards">
        {rows.map((e) => (
          <li key={e.id}>
            <div><div className="pf-t1">{e.title}</div>{e.subtitle && <div className="pf-t2">{e.subtitle}</div>}</div>
            <div className="pf-amt" style={{ color: amountTone(e.credits) }}>{e.credits}</div>
            <div className="pf-meta"><span>{when(e.at)}</span><Badge code={e.status} label={e.status_label} /></div>
          </li>
        ))}
      </ul>
    </>
  );
}

export function VideosTable({ rows }) {
  if (!rows.length) return <p className="pf-empty">Nenhum vídeo pronto ainda. Vídeos em DEMO não usam créditos.</p>;
  return (
    <>
      <table className="pf-table">
        <thead><tr><th scope="col">Data</th><th scope="col">Vídeo</th><th scope="col">Status</th><th scope="col">Créditos</th></tr></thead>
        <tbody>
          {rows.map((e) => (
            <tr key={e.production_id}>
              <td className="pf-date">{when(e.at)}</td>
              <td><div className="pf-t1">{e.product || 'Vídeo'}</div>{e.style && <div className="pf-t2">{e.style}</div>}</td>
              <td><Badge code={e.status} label={e.status_label} /></td>
              <td className="pf-amt">{e.credits}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="pf-list pf-cards">
        {rows.map((e) => (
          <li key={e.production_id}>
            <div><div className="pf-t1">{e.product || 'Vídeo'}</div>{e.style && <div className="pf-t2">{e.style}</div>}</div>
            <div className="pf-amt">{e.credits}</div>
            <div className="pf-meta"><span>{when(e.at)}</span><Badge code={e.status} label={e.status_label} /></div>
          </li>
        ))}
      </ul>
    </>
  );
}

// Apresentação pura (testada por renderização).
export function CreditsView({ d, plan, tab, setTab, onBuy, onPackages, adding }) {
  return (
    <div className="pf">
      <div className="pf-top">
        <section className="pf-card is-bg" aria-label="Saldo disponível">
          <div className="pf-k">Saldo disponível</div>
          {d.exempt
            ? <div className="pf-big"><strong>Isento</strong></div>
            : <div className="pf-big"><strong>{d.balance}</strong><span>créditos</span></div>}
          <p className="pf-muted">{d.exempt ? 'Conta do dono: o consumo é registrado, mas não precisa de saldo.' : reservedText(d)}</p>
          {!d.exempt && <div><button type="button" className="pf-btn is-dark" onClick={onBuy} aria-expanded={adding === undefined ? undefined : adding}>{d.topup && d.topup.online ? 'Comprar créditos' : ADD_LABEL}</button></div>}
        </section>
        <section className="pf-card" aria-label="Seu plano">
          <div className="pf-k">Seu plano</div>
          <div className="pf-plan">{planName(plan)}</div>
          <div><button type="button" className="pf-link" onClick={onPackages}>Ver pacotes</button></div>
        </section>
      </div>
      <div className="pf-bar">
        <div className="pf-tabs" role="tablist" aria-label="Detalhes dos créditos">
          <button type="button" role="tab" className="pf-tab" aria-selected={tab === 'extrato'} onClick={() => setTab('extrato')}>Extrato</button>
          <button type="button" role="tab" className="pf-tab" aria-selected={tab === 'video'} onClick={() => setTab('video')}>Por vídeo</button>
        </div>
        <a className="pf-btn" href="/api/credits/statement.csv" download><Download size={16} aria-hidden="true" />Baixar extrato</a>
      </div>
      <div role="tabpanel">
        {tab === 'extrato' ? <StatementTable rows={d.statement || []} /> : <VideosTable rows={d.videos || []} />}
      </div>
      <p className="pf-note">Falhas técnicas não são cobradas. Ao criar um vídeo, os créditos ficam reservados e só são descontados quando ele fica pronto.</p>
    </div>
  );
}

export function CreditsContent({ v }) {
  const [d, setD] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [tab, setTab] = React.useState('extrato');
  const [adding, setAdding] = React.useState(false);
  React.useEffect(() => { getJSON('/api/credits').then(setD).catch((e) => setErr(e.message)); }, []);
  const online = !!(d && d.topup && d.topup.online);
  return (
    <>
      {err && <div role="alert" className="pf pf-err">{err}</div>}
      {!d && !err && <div className="pf-load pf"><Spinner /></div>}
      {d && (
        <>
          <CreditsView d={d} plan={v.account && v.account.plan} tab={tab} setTab={setTab} adding={online ? undefined : adding}
            onBuy={() => (online ? v.openPricing() : setAdding((a) => !a))} onPackages={() => (online ? v.openPricing() : setAdding(true))} />
          {adding && !online && <div className="pf"><TopUp topup={d.topup} onClose={() => setAdding(false)} /></div>}
        </>
      )}
    </>
  );
}
