import React from 'react';
import Icon from './icons.jsx';
import { Avatar, Pill, PROD_LABEL } from './Central.jsx';
import CancelMission from './CancelMission.jsx';

const ICON = { objetivo: 'chat', orquestrador: 'brain', roteiro: 'edit', criativo: 'image', video: 'video', revisao: 'shield', entrega: 'box' };
const SUB = { objetivo: 'Defina o produto', orquestrador: 'Interpreta, planeja, delega e acompanha', revisao: 'Valida qualidade e solicita decisões necessárias', entrega: 'Arquivos, histórico, custos e resultado' };

function Node({ n, v, children }) {
  const body = (<>
    <span className="pv-nicon"><Icon name={ICON[n.id]} size={20} /></span>
    <span className="pv-grow"><div className="pv-title">{n.title}</div><div className="pv-meta">{n.detail || SUB[n.id] || ''}</div></span>
    {n.agents.length > 0 && <span style={{ display: 'flex', gap: 4 }}>{n.agents.map((id) => { const a = v.team.find((t) => t.id === id); return a ? <Avatar key={id} look={a.look} size={30} /> : null; })}</span>}
    <Pill s={n.state}>{n.label}</Pill>
  </>);
  return n.tab
    ? <button className="pv-node" data-s={n.state} onClick={() => v.openStep(n.tab)} aria-label={n.title + ': ' + n.label + '. Abrir'}>{body}</button>
    : <div className="pv-node" data-s={n.state} style={{ cursor: 'default' }}>{body}{children}</div>;
}
const Link = ({ on }) => <div className="pv-link" data-on={on ? '1' : '0'} aria-hidden="true" />;

// Missão: o fluxo ao vivo (objetivo → orquestrador → frentes → revisão → entrega) com o estado REAL de cada parte.
export default function MissionView({ v }) {
  const p = v.pipeline;
  if (!v.hasProd) {
    return (
      <div className="pv-scroll"><div className="pv-wrap" style={{ maxWidth: 560 }}>
        <div className="pv-card pv-empty" style={{ padding: 40 }}><strong style={{ fontSize: 20 }}>Nenhuma missão aberta</strong>
          Descreva o produto e a equipe monta o roteiro, as imagens, os vídeos e a edição, pedindo sua decisão nos pontos certos.
          <div style={{ marginTop: 18 }}><button className="pv-btn pv-btn-lime" onClick={v.newProd}><Icon name="plus" size={16} />Começar missão</button></div>
          {v.productions.length > 0 && <div style={{ marginTop: 14 }}><button className="pv-btn pv-btn-quiet" onClick={() => v.setView('central')}>Ver missões anteriores</button></div>}
        </div>
      </div></div>
    );
  }
  return (
    <div className="pv-scroll"><div className="pv-wrap">
      <div className="pv-two">
        <section aria-label="Fluxo da missão" className="pv-card pv-flow">
          <Node n={p.goal} v={v} />
          <Link on={p.orchestrator.state === 'work'} />
          <Node n={p.orchestrator} v={v} />
          <Link on={p.orchestrator.busy} />
          <div className="pv-fronts">
            {p.fronts.map((f) => (
              <button key={f.id} className="pv-front" data-s={f.state} onClick={() => v.openStep(f.tab)} aria-label={f.title + ': ' + f.label + '. Abrir'}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span className="pv-nicon"><Icon name={ICON[f.id]} size={20} /></span>
                  <span className="pv-grow"><div className="pv-title">{f.title}</div></span>
                </span>
                <span className="pv-meta" style={{ minHeight: 34 }}>{f.detail}</span>
                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                  <Pill s={f.state}>{f.label}</Pill>
                  <span style={{ display: 'flex' }}>{f.agents.map((id, k) => { const a = v.team.find((t) => t.id === id); return a ? <span key={id} style={{ marginLeft: k ? -8 : 0 }}><Avatar look={a.look} size={28} /></span> : null; })}</span>
                </span>
              </button>
            ))}
          </div>
          <Link on={p.review.state === 'work' || p.fronts.some((f) => f.state === 'work')} />
          <Node n={p.review} v={v} />
          <Link on={p.delivery.state === 'work'} />
          <Node n={p.delivery} v={v} />
        </section>

        <aside style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <section className="pv-card" style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 12 }} aria-label="Próxima ação">
            <div className="pv-h2" style={{ margin: 0 }}>Próxima ação</div>
            <div className="pv-title" style={{ fontSize: 16 }}>{v.nextLong}</div>
            {v.nextLabel ? <button className="pv-btn pv-btn-lime" onClick={v.goNext}>{v.nextLabel}<Icon name="arrow" size={15} /></button> : <span className="pv-meta">Nada pendente agora.</span>}
            <div className="pv-bar" role="img" aria-label={'Progresso: ' + p.progress + '%'}><i style={{ width: p.progress + '%' }} /></div>
            <div className="pv-meta">{v.stageLabel} · {p.progress}% do fluxo</div>
            {v.active && <div className="pv-meta" data-testid="mission-format">Apresentação: <strong>{v.active.label}</strong>{v.active.format && !v.active.provisional ? <> · formato <code>{v.active.format}</code></> : null}</div>}
            <CancelMission v={v} />
          </section>
          <section className="pv-card" style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 8 }} aria-label="Custo">
            <div className="pv-h2" style={{ margin: 0 }}>Usado neste vídeo</div>
            <div className="pv-title" style={{ fontSize: 22 }}>{v.credits.spent} <span className="pv-meta" style={{ fontSize: 14 }}>créditos</span></div>
            <div className="pv-meta">{v.balanceText ? v.balanceText + ' · ' : ''}Estimativa até a confirmação. Nenhum custo adicional é aplicado sem sua autorização.</div>
            <button className="pv-btn" onClick={v.openPilot} style={{ alignSelf: 'flex-start' }}><Icon name="pilot" size={15} />Piloto: {v.pilot.label}</button>
          </section>
          {v.productions.length > 1 && (
            <section className="pv-card" aria-label="Outras missões">
              {v.productions.map((x) => (
                <div key={x.id} className="pv-row" style={{ padding: '10px 14px' }}>
                  <div className="pv-grow"><div className="pv-title" style={{ fontSize: 14 }}>{x.name || x.id}</div><div className="pv-meta" style={{ marginTop: 0 }}>{PROD_LABEL[x.status] || x.label}</div></div>
                  {x.status === 'cancelled' && <Pill s="ended">Cancelada</Pill>}
                  {x.current ? <Pill s="done">Aberta</Pill> : <button className="pv-btn" onClick={x.open}>Abrir</button>}
                </div>
              ))}
            </section>
          )}
        </aside>
      </div>
    </div></div>
  );
}
