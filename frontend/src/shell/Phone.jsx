import React from 'react';
import { AlertCircle, ArrowRight, Check, ChevronRight, Plus } from 'lucide-react';
import Boneco from '../Boneco.jsx';
import { Avatar } from './Central.jsx';
import CancelMission from './CancelMission.jsx';
import { useReducedMotion } from './Conveyor.jsx';
import { stationAria } from './conveyor.js';
import { usePhone } from '../hooks/use-phone.js';
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

// ---------------------------------------------------------------- escritório (versão simples)
const ANIM = { active: 'type', need: 'wave', done: 'happy' };
const WORD_OF = { active: 'Trabalhando', need: 'Precisa de você', done: 'Concluiu', problem: 'Parado', cancelled: 'Parado', ended: 'Parado', pending: 'Livre' };

export function PhoneOffice({ v }) {
  const rm = useReducedMotion();
  const stations = v.hasProd ? v.pipeline.stations || [] : [];
  const byAgent = Object.fromEntries(stations.map((s) => [s.agent, s]));
  const current = stations.find((s) => s.current);
  // na ordem da esteira (Nina → Theo → Iris → Lia → Rui → Beto); sem missão, a equipe na ordem de sempre
  const team = stations.length ? stations.map((x) => v.team.find((t) => t.id === x.agent)).filter(Boolean) : v.team.slice(0, 6);
  const [pick, setPick] = React.useState(null);
  const last = stations.length ? stations[stations.length - 1].agent : null;
  const focusId = pick || (current ? current.agent : stations.length && stations.every((x) => x.state === 'done') ? last : team[0] && team[0].id);
  const a = v.team.find((t) => t.id === focusId) || team[0];
  const s = a ? byAgent[a.id] : null;
  const state = s ? s.state : 'pending';
  const allDone = stations.length > 0 && stations.every((x) => x.state === 'done');
  const progress = v.hasProd ? v.pipeline.progress : 0;
  const statusText = v.falMission && v.falMission.status ? v.falMission.status.text : v.nextLong;
  return (
    <div className="pv-scroll"><div className="pv-wrap pv-ph">
      {a && (
        <section className="pv-office-hero" data-s={state} aria-label={`${a.name}: ${WORD_OF[state] || ''}`}>
          <span className="pv-office-sprite" aria-hidden="true"><Boneco look={a.look} anim={v.ended || rm ? 'idle' : (ANIM[state] || 'idle')} size={112} /></span>
          <span className="pv-office-step">{s ? titleCase(s.title) : 'Equipe'}</span>
          <strong className="pv-office-name">{a.name} <span>· {a.role}</span></strong>
          <span className="pv-word" data-tone={state === 'active' ? 'work' : state === 'need' ? 'need' : state === 'done' ? 'done' : state === 'problem' ? 'warn' : 'off'}>{s ? s.label : 'Livre'}</span>
          {v.hasProd ? (<>
            <span className="pv-office-bar" role="img" aria-label={`Progresso da missão: ${progress}%`}><i style={{ transform: `scaleX(${progress / 100})` }} /></span>
            <span className="pv-office-meta">{v.prodName || 'Seu vídeo'} · {progress}%{allDone ? ' · pronto' : ''}</span>
            {statusText && <p className="pv-office-text">{statusText}</p>}
          </>) : <p className="pv-office-text">Nenhuma missão em andamento. A equipe está livre.</p>}
        </section>
      )}
      <section aria-label="Equipe" className="pv-office-team">
        <ul>
          {team.map((t) => { const ts = byAgent[t.id]; const st = ts ? ts.state : 'pending'; return (
            <li key={t.id}>
              <button type="button" className="pv-office-agent" data-s={st} aria-pressed={t.id === focusId} onClick={() => setPick(t.id)}
                aria-label={`${t.name}${ts ? ', ' + titleCase(ts.title) : ''}: ${ts ? ts.label : 'Livre'}`}>
                <Avatar look={t.look} size={44} />
                <strong>{t.name}</strong>
                <span>{ts ? titleCase(ts.title) : t.role}</span>
                <i className="pv-office-dot" data-s={st} aria-hidden="true" />
              </button>
            </li>); })}
        </ul>
      </section>
      {v.hasProd
        ? <Dock><button type="button" className="pv-dock-btn" onClick={() => v.setView('missao')}>Ver missão<ArrowRight size={20} aria-hidden="true" /></button></Dock>
        : <Dock><button type="button" className="pv-dock-btn" onClick={v.newProd}><Plus size={20} aria-hidden="true" />Nova produção</button></Dock>}
    </div></div>
  );
}

// No celular o Escritório é a versão simples (sem o mapa em pixel art, que não cabe nem se joga no polegar).
export function OfficeSwitch({ v, children }) {
  const phone = usePhone();
  return phone ? <PhoneOffice v={v} /> : children;
}
