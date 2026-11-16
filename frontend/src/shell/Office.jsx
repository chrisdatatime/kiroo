import React from 'react';
import { Bell, MessageCircle, Play, Plus, X } from 'lucide-react';
import { Avatar } from './Central.jsx';
import { usePhone } from '../hooks/use-phone.js';
import { sideNav } from './accountMenu.js';
import { agentPanel, agentState, officeHint, officeStatus, pickAgent, teamLine } from './office.js';
import './office.css';

// Escritório (Fase 2 do novo layout): o mapa em pixel art (children = WorldPhaser + Hud) dentro do Shell novo.
// Desktop: mapa + faixa da equipe embaixo + painel do agente à direita (só com alguém escolhido).
// Celular (< 768 px): mapa + gaveta inferior com a equipe e o agente escolhido; a barra inferior é a do Shell.
// O mapa (.of-map) é o elemento focável: as teclas de andar só valem com ele (ou a raiz) em foco (shell/office.js).
export default function Office({ v, children }) {
  const phone = usePhone();
  const nav = sideNav(v);
  const waiting = (nav.find((x) => x.id === 'producoes') || {}).badge || 0;
  const live = !!(nav.find((x) => x.id === 'escritorio') || {}).live;
  const status = officeStatus({ statuses: v.statuses, waiting, live });
  const team = v.team.filter((a) => v.rooms.some((r) => r.agent === a.id));
  const selId = pickAgent(team, v.statuses, v.agentSel, phone);
  const sel = team.find((a) => a.id === selId);
  const panel = sel ? agentPanel({ agent: sel, status: v.statuses[sel.id], room: v.rooms.find((r) => r.agent === sel.id), hasProd: v.hasProd, prodName: v.prodName }) : null;
  const pick = (id) => v.selectAgent(v.agentSel === id && !phone ? null : id);

  return (
    <div className="of" data-phone={phone || undefined}>
      <div className="of-main">
        <div className="of-map" ref={v.setMapEl} tabIndex={0} data-tour="office-map"
          aria-label={phone ? 'Mapa do escritório. Toque numa mesa para andar.' : 'Mapa do escritório. Setas ou WASD para andar, E para falar com quem estiver perto.'}>
          {children}
          <div className="of-badges">
            <span className="of-badge" data-tone={status.team.tone}><i aria-hidden="true" /><strong>{status.team.title}</strong>{status.team.text && !phone && <span>· {status.team.text}</span>}</span>
            {status.need && !phone && <button type="button" className="of-badge of-badge-need" onClick={() => v.setView('missao')}><Bell size={15} aria-hidden="true" /><strong>{status.need}</strong></button>}
          </div>
          <p className="of-hint">{officeHint(phone)}</p>
        </div>
        {!phone && (
          <div className="of-team">
            <span className="of-team-h" id="of-team-h">Equipe</span>
            <div role="group" aria-labelledby="of-team-h" className="of-team-list">
              {team.map((a) => { const st = agentState(v.statuses[a.id]); return (
                <button key={a.id} type="button" className="of-mate" data-tone={st.tone} aria-pressed={a.id === selId} onClick={() => pick(a.id)}
                  aria-label={`${a.name}, ${a.role}: ${st.word}`}>
                  <Avatar look={a.look} size={32} />
                  <span><strong>{a.name}</strong><span className="of-mate-st"><i aria-hidden="true" />{teamLine(a, v.statuses[a.id])}</span></span>
                </button>); })}
            </div>
          </div>
        )}
      </div>
      {!phone && panel && <AgentPanel v={v} p={panel} />}
      {phone && <Drawer v={v} team={team} selId={selId} p={panel} onPick={pick} />}
    </div>
  );
}

function Actions({ v, p, compact }) {
  return (
    <div className={'of-actions' + (compact ? ' of-actions-compact' : '')}>
      {p.canOpen
        ? <button type="button" className="of-btn" data-tone={p.tone === 'need' ? 'need' : 'ink'} onClick={() => v.openAgentWork(p.id)}><Play size={16} aria-hidden="true" />{p.primary}</button>
        : <button type="button" className="of-btn" data-tone="ink" onClick={v.newProd}><Plus size={16} aria-hidden="true" />Nova produção</button>}
      <button type="button" className="of-btn" data-tone="line" onClick={() => v.talkTo(p.id)}><MessageCircle size={16} aria-hidden="true" />Conversar</button>
    </div>
  );
}

function AgentPanel({ v, p }) {
  return (
    <aside className="of-panel" aria-label="Agente selecionado">
      <div className="of-panel-top"><span className="of-cap">Agente</span>
        <button type="button" className="of-x" onClick={() => v.selectAgent(null)} aria-label="Fechar painel"><X size={16} aria-hidden="true" /></button></div>
      <div className="of-who">
        <span className="of-who-av"><Avatar look={p.look} size={64} /></span>
        <div><div className="of-who-name">{p.name}</div><div className="of-who-role">{p.role}</div>
          <span className="of-chip" data-tone={p.tone}><i aria-hidden="true" />{p.word}</span></div>
      </div>
      <section className="of-now" data-tone={p.tone} aria-label="O que está fazendo">
        <strong>{p.doing}</strong>
        <span>{p.production ? `Produção atual: ${p.production}` : 'Nenhuma produção aberta.'}</span>
      </section>
      {p.about && <div className="of-about"><span className="of-cap">Sala</span><p>{p.about}</p></div>}
      <span className="of-fill" />
      <Actions v={v} p={p} />
    </aside>
  );
}

function Drawer({ v, team, selId, p, onPick }) {
  return (
    <section className="of-drawer" aria-label="Agente selecionado">
      <div className="of-grab" aria-hidden="true" />
      <div className="of-chips" role="group" aria-label="Equipe">
        {team.map((a) => { const st = agentState(v.statuses[a.id]); return (
          <button key={a.id} type="button" className="of-chipbtn" data-tone={st.tone} aria-pressed={a.id === selId} onClick={() => onPick(a.id)} aria-label={`${a.name}: ${st.word}`}>
            <Avatar look={a.look} size={36} /><span>{a.name}</span>
          </button>); })}
      </div>
      {p ? (<>
        <div className="of-drow">
          <Avatar look={p.look} size={44} />
          <div><strong>{p.name} · {p.role}</strong><span data-tone={p.tone}>{p.tone === 'need' ? p.word : p.doing}</span></div>
        </div>
        <Actions v={v} p={p} compact />
      </>) : <p className="of-drawer-empty">Toque num agente ou numa mesa para ver o que ele está fazendo.</p>}
    </section>
  );
}
