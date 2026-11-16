import React from 'react';
import { AlertCircle, Check, ChevronRight, Plus } from 'lucide-react';
import { Avatar } from './Central.jsx';
import CancelMission from './CancelMission.jsx';
import { useReducedMotion } from './Conveyor.jsx';
import { stationAria } from './conveyor.js';
import { useFalBelt, FalDone } from '../ui/FalMission.jsx';
import { isDone } from '../ui/falFlow.js';
import { missionWord } from '../ui/mobile.js';
import { UpsellNote } from '../ui/UpsellNote.jsx';

// Celular (<= 640 px): telas pensadas para o polegar, uma ação principal por tela (fixa no rodapé, acima da barra
// inferior). Os dados são os mesmos do desktop (viewModel do App); só a forma muda. CSS em shell.css (.pv-ph-*).

// Ação principal fixa no rodapé da área rolável (sticky): fica na zona do polegar e não cobre o conteúdo.
export function Dock({ children, error }) {
  return (
    <div className="pv-dock">
      {error && <div role="alert" className="pv-dock-err"><AlertCircle size={18} aria-hidden="true" />{error}</div>}
      {children}
    </div>
  );
}

const sinceLabel = (iso) => { const d = iso ? new Date(iso) : null; return d && !Number.isNaN(d.getTime()) ? d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' }) : ''; };

// ---------------------------------------------------------------- lista de missões
export function PhoneMissions({ v }) {
  const open = (p) => { p.open(); v.setView('missao'); };
  return (
    <div className="pv-scroll"><div className="pv-wrap pv-ph">
      {v.attn.length > 0 && (
        <section aria-label="Precisa de você" className="pv-ph-attn">
          {v.attn.map((a) => (
            <button key={a.id} type="button" className="pv-ph-attn-item" onClick={a.room ? a.room.work : v.goNext}>
              <span className="pv-ph-attn-ic" aria-hidden="true">!</span>
              <span className="pv-grow"><strong>{a.kind === 'pause' ? a.title : `${a.who} precisa de você`}</strong><span>{a.text}</span></span>
              <ChevronRight size={20} aria-hidden="true" />
            </button>
          ))}
        </section>
      )}
      <section aria-labelledby="ph-missions-h" className="pv-ph-list">
        <h2 id="ph-missions-h" className="pv-ph-h">Suas missões{v.productions.length ? <span> · {v.productions.length}</span> : null}</h2>
        {v.productions.length === 0 && (
          v.welcomeEmpty ? (
            <div className="pv-ph-empty"><strong>{v.welcomeEmpty.title}</strong>{v.welcomeEmpty.text}</div>
          ) : <div className="pv-ph-empty"><strong>Nenhuma missão ainda</strong>Envie a foto de um produto e a equipe cria o vídeo, a foto, o título e a legenda.</div>
        )}
        <ul>
          {v.productions.map((p) => { const w = missionWord(p, p.current && v.falMission && v.falMission.status ? v.falMission.status.kind : null); return (
            <li key={p.id}>
              <button type="button" className="pv-mcard" onClick={() => open(p)} aria-label={`${p.name || 'Missão sem nome'}: ${w.word}. Abrir`}>
                <span className="pv-grow">
                  <strong className="pv-mcard-name">{p.name || 'Missão sem nome'}</strong>
                  <span className="pv-mcard-meta">{sinceLabel(p.created_at)}{p.mode === 'simulated' ? ' · DEMO' : ''}{p.current ? ' · aberta' : ''}</span>
                </span>
                <span className="pv-word" data-tone={w.tone}>{w.word}</span>
                <ChevronRight size={20} aria-hidden="true" className="pv-mcard-go" />
              </button>
            </li>); })}
        </ul>
      </section>
      <Dock><button type="button" className="pv-dock-btn" onClick={v.newProd}><Plus size={20} aria-hidden="true" />{v.welcomeEmpty ? v.welcomeEmpty.cta : 'Nova produção'}</button></Dock>
    </div></div>
  );
}

// ---------------------------------------------------------------- esteira vertical
const titleCase = (t) => (t ? t.charAt(0) + t.slice(1).toLowerCase() : '');

// Uma linha por etapa: nome da etapa em destaque, agente pequeno e a barra na largura toda. Altura fixa por linha
// (textos numa linha só, barra sempre presente): nada pula de lugar entre um poll e outro. A barra de cada etapa é o
// `level` da estação (falBelt.js, a mesma fonte da esteira do desktop).
const fillOf = (s) => (s.state === 'need' && s.current ? 100 : typeof s.level === 'number' ? s.level : s.state === 'done' ? 100 : 0);   // aguardando você: barra cheia na cor de atenção
export function BeltVertical({ stations, team, ended = null, missionKey = null, autoScroll = true }) {
  const rm = useReducedMotion();
  const refs = React.useRef({});
  const scrolled = React.useRef({});
  const current = stations.find((s) => s.current);
  const curId = current ? current.id : null;
  const nameOf = (s) => { const a = team.find((t) => t.id === s.agent); return a ? a.name : s.agent; };

  // a tela rola até a etapa atual só na primeira vez (por missão); depois o usuário manda na rolagem
  React.useEffect(() => {
    if (!autoScroll || !curId || scrolled.current[missionKey]) return;
    const el = refs.current[curId];
    scrolled.current[missionKey] = true;
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'center', behavior: rm ? 'auto' : 'smooth' });
  }, [curId, missionKey, autoScroll, rm]);

  const allDone = stations.every((s) => s.state === 'done');
  const announce = current ? stationAria(current, nameOf(current)) : allDone ? 'Missão concluída: todas as etapas entregues.' : '';
  return (
    <section className="pv-vbelt pv-card" aria-label="Esteira de agentes" data-ended={ended || undefined} data-motion={rm ? 'reduced' : undefined} data-testid="belt-vertical">
      <ol>
        {stations.map((s) => {
          const a = team.find((t) => t.id === s.agent);
          return (
            <li key={s.id} ref={(el) => { refs.current[s.id] = el; }} className="pv-vrow" data-s={s.state} data-fail={s.fail || undefined} data-current={s.current || undefined}
              aria-current={s.current ? 'step' : undefined} aria-label={stationAria(s, nameOf(s))}>
              <span className="pv-vrow-top">
                <strong className="pv-vstep">{titleCase(s.title)}</strong>
                <span className="pv-vstate">{s.state === 'done' ? <Check size={15} strokeWidth={2.6} aria-hidden="true" /> : null}{s.label}</span>
              </span>
              <span className="pv-vagent">{a ? <Avatar look={a.look} size={24} /> : null}<span>{nameOf(s)}{s.detail ? ` · ${s.detail}` : ''}</span></span>
              <span className="pv-vbar" aria-hidden="true"><i style={{ transform: `scaleX(${fillOf(s) / 100})` }} /></span>
            </li>
          );
        })}
      </ol>
      <p className="pv-sr" aria-live="polite">{announce}</p>
    </section>
  );
}

// ---------------------------------------------------------------- missão (fluxo foto + estilo)
export function PhoneFalMission({ v, m: m0 }) {
  const belt = useFalBelt(m0.P);       // esteira animada: mesma fonte (falBelt) e mesmo estado do desktop
  const m = { ...m0, status: belt.status, stations: belt.stations, progress: belt.progress };
  const st = m.status || {};
  const done = !!(m.gallery && m.gallery.video) && belt.allDone && isDone(m.P);   // o resultado sobe só depois das 6 etapas cheias
  const ended = ['failed', 'cancelled', 'partial'].includes(st.kind);
  return (
    <div className="pv-scroll"><div className="pv-wrap pv-ph">
      {done && <FalDone m={m} team={v.team} product={v.prodName} stations={belt.stations} phone />}
      {done && v.firstVideo && <UpsellNote copy={v.firstVideo} onClick={v.openBuy} />}
      {!done && (
        <section className="pv-ph-status" role="status" data-kind={st.kind}>
          <strong>{st.label}</strong>
          <p>{st.text}</p>
          {st.kind === 'running' && <span className="pv-ph-pct">{m.progress}%</span>}
        </section>
      )}
      {!done && <BeltVertical stations={m.stations} team={v.team} ended={v.ended} missionKey={v.prodId} autoScroll />}
      {!done && v.canCancel && <section className="pv-ph-foot" aria-label="Cancelar"><CancelMission v={v} /></section>}
      {st.action === 'start' && <Dock error={m.error}><button type="button" className="pv-dock-btn" onClick={m.start} disabled={m.busy}>{m.busy ? 'Começando…' : m.startLabel}</button></Dock>}
      {st.action !== 'start' && !done && ended && <Dock><button type="button" className="pv-dock-btn pv-dock-quiet" onClick={v.newProd}><Plus size={20} aria-hidden="true" />Nova produção</button></Dock>}
    </div></div>
  );
}

// O Escritório no celular deixou de ser uma lista: é o mesmo mapa do desktop com a gaveta inferior (shell/Office.jsx, Fase 2).
