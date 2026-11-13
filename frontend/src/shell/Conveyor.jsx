import React from 'react';
import { Ban } from 'lucide-react';
import Boneco from '../Boneco.jsx';
import Icon from './icons.jsx';
import { HOP_MS, TASK_ICON, hopGeometry, shouldHop, stationAria } from './conveyor.js';

// Esteira de agentes: visão principal do progresso da missão. Seis estações (um agente cada) numa faixa horizontal;
// o estado de cada uma vem de buildPipeline (pipeline.js, `stations`). Quando uma estação passa a bola, o ícone da
// tarefa salta em arco até a próxima (só transform/opacity em CSS; com movimento reduzido, só troca de cor).
// Abrir a tela depois mostra o estado final: o salto só acontece entre dois snapshots da MESMA missão.

const ANIM = { active: 'type', need: 'wave', done: 'happy', problem: 'idle', pending: 'idle', ended: 'idle', cancelled: 'idle' };

// prefers-reduced-motion ao vivo (muda sem recarregar). `forced` fixa o valor (testes e SSR).
export function useReducedMotion(forced) {
  const [rm, setRm] = React.useState(() => (typeof forced === 'boolean' ? forced
    : typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches));
  React.useEffect(() => {
    if (typeof forced === 'boolean' || typeof window === 'undefined' || !window.matchMedia) return undefined;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const on = () => setRm(mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, [forced]);
  return typeof forced === 'boolean' ? forced : rm;
}

function Badge({ state }) {
  if (state === 'done') return <span className="pv-station-badge" data-k="done"><Icon name="check" size={13} /></span>;
  if (state === 'need') return <span className="pv-station-badge" data-k="need">!</span>;
  if (state === 'problem') return <span className="pv-station-badge" data-k="problem"><Icon name="alert" size={13} /></span>;
  if (state === 'cancelled' || state === 'ended') return <span className="pv-station-badge" data-k="ended"><Ban size={12} strokeWidth={2.4} /></span>;
  if (state === 'active') return <span className="pv-station-badge" data-k="active"><i /></span>;
  return null;
}

function TaskIcon({ station, thumb }) {
  if (thumb && thumb.url && !thumb.video) return <img src={thumb.url} alt="" />;
  if (thumb && thumb.url && thumb.video) return <video src={thumb.url} muted playsInline preload="metadata" />;
  return <Icon name={TASK_ICON[station] || 'spark'} size={18} />;
}

export default function Conveyor({ stations, team, ended = null, missionKey = null, thumbs = {}, credits = {}, onOpen, reduced }) {
  const rm = useReducedMotion(reduced);
  const prev = React.useRef({ key: missionKey, stations: null });
  const refs = React.useRef({});
  const trackRef = React.useRef(null);
  const [hop, setHop] = React.useState(null);

  // transição: compara com o snapshot anterior (mesma missão) e posiciona o salto pelas medidas reais das estações
  React.useEffect(() => {
    const p = prev.current;
    const h = shouldHop({ reduced: rm, prevKey: p.key, key: missionKey, prev: p.stations, next: stations });
    prev.current = { key: missionKey, stations };
    if (!h) return undefined;
    const a = refs.current[h.from], b = refs.current[h.to];
    const g = a && b ? hopGeometry({ left: a.offsetLeft, width: a.offsetWidth }, { left: b.offsetLeft, width: b.offsetWidth }) : null;
    if (!g) return undefined;
    setHop({ ...h, ...g, key: Date.now() });
    const t = setTimeout(() => setHop(null), HOP_MS + 250);   // garantia caso animationend não dispare
    return () => clearTimeout(t);
  }, [stations, missionKey, rm]);

  // estação atual sempre visível na faixa rolável (celular), sem mexer na rolagem da página
  const current = stations.find((s) => s.current);
  const curId = current ? current.id : null;
  React.useEffect(() => {
    const track = trackRef.current, el = curId ? refs.current[curId] : null;
    if (!track || !el || track.scrollWidth <= track.clientWidth + 1) return;
    const left = el.offsetLeft - (track.clientWidth - el.offsetWidth) / 2;
    if (typeof track.scrollTo === 'function') track.scrollTo({ left: Math.max(0, left), behavior: rm ? 'auto' : 'smooth' });
  }, [curId, rm]);

  const nameOf = (s) => { const a = team.find((t) => t.id === s.agent); return a ? a.name : s.agent; };
  const allDone = stations.every((s) => s.state === 'done');
  const announce = current ? stationAria(current, nameOf(current)) : allDone ? 'Missão concluída: todas as etapas entregues.' : '';

  return (
    <section className="pv-belt pv-card" aria-label="Esteira de agentes" data-ended={ended || undefined} data-motion={rm ? 'reduced' : undefined}
      data-inflight={hop ? '1' : undefined} data-testid="belt">
      <ol className="pv-belt-track" ref={trackRef}>
        {stations.map((s, i) => {
          const a = team.find((t) => t.id === s.agent);
          const showNow = (s.state === 'active' || s.state === 'need' || s.state === 'problem') && s.detail && s.detail !== s.label;
          const tipId = credits[s.id] ? `pv-belt-cr-${s.id}` : undefined;
          return (
            <li key={s.id} ref={(el) => { refs.current[s.id] = el; }} className="pv-station" data-s={s.state} data-current={s.current || undefined}
              data-landing={hop && hop.to === s.id ? '1' : undefined}>
              <button type="button" className="pv-station-btn" aria-current={s.current ? 'step' : undefined} aria-label={stationAria(s, nameOf(s))}
                aria-describedby={tipId} onClick={() => onOpen && onOpen(s.tab)}>
                <Badge state={s.state} />
                <span className="pv-station-sprite" aria-hidden="true">{a ? <Boneco look={a.look} anim={ended || rm ? 'idle' : ANIM[s.state]} size={52} /> : null}</span>
                <span className="pv-station-name">{nameOf(s)}</span>
                <span className="pv-station-step">{s.title}</span>
                <span className="pv-station-state">{s.label}</span>
                {showNow ? <span className="pv-station-now">{s.detail}</span> : null}
                {s.state === 'cancelled' ? <span className="pv-station-seal" aria-hidden="true">Cancelada</span> : null}
              </button>
              {tipId ? <span className="pv-station-tip" role="tooltip" id={tipId}>Créditos usados nesta etapa: <strong>{credits[s.id]}</strong></span> : null}
              {i < stations.length - 1 ? <span className="pv-station-link" aria-hidden="true" data-on={s.state === 'done' ? '1' : '0'} /> : null}
            </li>
          );
        })}
        {hop ? (
          <span key={hop.key} className="pv-belt-hop" aria-hidden="true" data-testid="belt-hop" data-from={hop.from} data-to={hop.to}
            style={{ '--x0': hop.x0 + 'px', '--x1': hop.x1 + 'px', '--hop-ms': HOP_MS + 'ms' }}
            onAnimationEnd={(e) => { if (e.target === e.currentTarget) setHop(null); }}>
            <span className="pv-belt-hop-y"><TaskIcon station={hop.from} thumb={thumbs[hop.from]} /></span>
          </span>
        ) : null}
      </ol>
      <p className="pv-sr" aria-live="polite">{announce}</p>
    </section>
  );
}
