import React from 'react';
import { ArrowRight } from 'lucide-react';
import { ART, AGENT_PINS } from './art.js';
import { ACTS, ROOMS, IMG, WIDE, clamp01, ease, mix, mixRect, fitCamera, mixCam, pan, fmtTC } from './stage.js';
import { AgentHead } from '../shell/AgentHead.jsx';
import { useMedia, go } from './util.js';

/* Abertura + bastidores em três atos, com uma única câmera contínua.
   Uma camada fixa (sticky) desenha o quadro com a sede. O quadro segue "encaixes" invisíveis no conteúdo:
   1. na abertura, o encaixe abaixo do título (sede em close, a câmera passeia pelas salas de cima);
   2. ao rolar, o quadro cresce até a tela inteira e a câmera recua até o plano geral;
   3. nos atos, encaixa no quadro fixo da coluna da esquerda (no celular, faixa no topo) e enquadra as salas do ato.
   A rolagem é nativa: nada é preso; o JS só lê posições e escreve transform. Com movimento reduzido, sem zoom nem passeio. */

const PX = Object.fromEntries(Object.entries(AGENT_PINS).map(([id, p]) => [id, { x: (p.x / 100) * IMG.w, y: (p.y / 100) * IMG.h }]));

// Produção de exemplo, com o estado de cada agente. state: done | work | need | wait.
export const CREW = {
  nina: { role: 'Planejamento', name: 'Nina', state: 'done' },
  theo: { role: 'Direção criativa', name: 'Theo', state: 'done' },
  iris: { role: 'Imagens', name: 'Iris', state: 'work' },
  lia: { role: 'Vídeos', name: 'Lia', state: 'wait' },
  rui: { role: 'Revisão', name: 'Rui', state: 'need' },
  beto: { role: 'Edição', name: 'Beto', state: 'wait' },
};
const STATE = { done: 'concluiu', work: 'trabalhando', need: 'precisa de você', wait: 'aguardando' };
const ACT_COPY = {
  pre: { d: 'A Nina lê suas fotos e a ficha. O Theo propõe ambiente, tom e roteiro.', you: 'Você aprova a direção ou ajusta.' },
  prod: { d: 'A Iris cria cada cena a partir das suas fotos. A Lia anima as imagens aprovadas.', you: 'Você libera cada etapa paga, vendo a estimativa.' },
  pos: { d: 'O Rui confere cada cena contra as fotos. O Beto monta o vídeo, com e sem música.', you: 'Cena com dúvida espera você. O download é seu.' },
};

export function Portrait({ id, size = 40 }) {
  const src = ART[id];
  return (
    <span className="lp-face" style={{ width: size, height: size }} aria-hidden="true">
      {src ? <img src={src} alt="" width={size} height={size} draggable="false" /> : <AgentHead active size={Math.round(size * 0.5)} />}
    </span>
  );
}

function Tags() {
  return (
    <div className="lp-tags" aria-hidden="true">
      {Object.entries(CREW).map(([id, c], i) => (
        <span key={id} className="lp-tag" data-id={id} data-state={c.state} style={{ left: PX[id].x, top: PX[id].y, '--d': i }}>
          <span className="lp-tag-in"><AgentHead active={c.state === 'work' || c.state === 'need'} size={12} />
            <strong>{c.role}</strong>{c.state === 'need' && <b className="lp-need">!</b>}</span>
        </span>
      ))}
    </div>
  );
}

export default function Stage({ start, startLabel, signupOpen }) {
  const reduced = useMedia('(prefers-reduced-motion: reduce)');
  const wide = useMedia('(min-width: 900px)');
  const stage = React.useRef(null), cam = React.useRef(null), frame = React.useRef(null), scene = React.useRef(null);
  const heroSlot = React.useRef(null), actsSlot = React.useRef(null), actsSec = React.useRef(null), tc = React.useRef(null);
  const actEls = React.useRef([]);
  const [k, setK] = React.useState(0);
  const [phase, setPhase] = React.useState('hero');
  const kRef = React.useRef(0); kRef.current = k;
  const redRef = React.useRef(reduced); redRef.current = reduced;

  // o ato que cruza a linha de leitura entra em cena (desktop: meio da tela; celular: abaixo da faixa da sede)
  React.useEffect(() => {
    if (!('IntersectionObserver' in window)) return undefined;
    const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) setK(+e.target.dataset.i); }),
      { rootMargin: wide ? '-45% 0px -45% 0px' : '-64% 0px -30% 0px' });
    actEls.current.forEach((el) => el && io.observe(el));
    return () => io.disconnect();
  }, [wide]);

  // câmera: um laço de rAF só enquanto a seção está na tela
  React.useEffect(() => {
    let raf = 0, on = false, last = -1;
    const t0 = performance.now();
    const cur = { s: 0, cx: 0, cy: 0 };
    let shown = '';
    const tick = (now) => {
      raf = on ? requestAnimationFrame(tick) : 0;
      const st = stage.current, cm = cam.current, fr = frame.current, sc = scene.current;
      if (!st || !cm || !fr || !sc || !heroSlot.current || !actsSlot.current) return;
      const vh = window.innerHeight;
      const c = cm.getBoundingClientRect();
      const rel = (el) => { const b = el.getBoundingClientRect(); return { x: b.left - c.left, y: b.top - c.top, w: b.width, h: b.height }; };
      const red = redRef.current;
      const stTop = st.getBoundingClientRect().top, acTop = actsSec.current.getBoundingClientRect().top;
      let t1 = clamp01(-stTop / (0.8 * vh)), t2 = clamp01((vh * 0.92 - acTop) / (0.7 * vh));
      if (red) { t1 = 0; t2 = acTop < vh * 0.5 ? 1 : 0; }
      const e1 = ease(t1), e2 = ease(t2);
      const r = mixRect(mixRect(rel(heroSlot.current), { x: 0, y: 0, w: c.width, h: c.height }, e1), rel(actsSlot.current), e2);
      const time = red ? 0 : (now - t0) / 1000;
      const dcx = 608 + 330 * Math.sin((time * 2 * Math.PI) / 26);
      const act = ACTS[kRef.current] || ACTS[0];
      // dentro do ato, a câmera corta entre as salas dos dois agentes (sem movimento: as duas salas juntas)
      const who = red ? null : act.crew[Math.floor(time / 3.4) % 2];
      const actRect = who ? ROOMS[who] : act.rect;
      const target = mixCam(mixCam(fitCamera([dcx - 280, 24, 560, 270], r.w, r.h, 'cover'), fitCamera(WIDE, r.w, r.h, 'cover'), e1),
        fitCamera(actRect, r.w, r.h), e2);
      // inércia de câmera (também suaviza a troca de ato); sem inércia com movimento reduzido ou no primeiro quadro
      const kk = red || !cur.s ? 1 : 0.11;
      cur.s = Math.exp(mix(Math.log(cur.s || target.s), Math.log(target.s), kk));
      cur.cx = mix(cur.cx || target.cx, target.cx, kk);
      cur.cy = mix(cur.cy || target.cy, target.cy, kk);
      const p = pan(cur, r.w, r.h);
      fr.style.transform = `translate3d(${r.x.toFixed(1)}px, ${r.y.toFixed(1)}px, 0)`;
      fr.style.width = r.w.toFixed(1) + 'px';
      fr.style.height = r.h.toFixed(1) + 'px';
      fr.style.borderRadius = mix(mix(10, 0, e1), 8, e2).toFixed(1) + 'px';
      sc.style.transform = `translate3d(${p.x.toFixed(1)}px, ${p.y.toFixed(1)}px, 0) scale(${cur.s.toFixed(4)})`;
      sc.style.setProperty('--inv', (1 / cur.s).toFixed(4));
      const ph = e2 > 0.5 ? act.id + (who ? ':' + who : '') : e1 > 0.5 ? 'wide' : 'hero';
      if (ph !== shown) { shown = ph; setPhase(ph); }
      const sec = Math.floor(time);
      if (sec !== last && tc.current) { last = sec; tc.current.textContent = fmtTC(sec); }
    };
    const startLoop = () => { if (!on) { on = true; raf = requestAnimationFrame(tick); } };
    const stopLoop = () => { on = false; if (raf) cancelAnimationFrame(raf); raf = 0; };
    const io = 'IntersectionObserver' in window ? new IntersectionObserver(([e]) => (e.isIntersecting && !document.hidden ? startLoop() : stopLoop())) : null;
    if (io) io.observe(stage.current); else startLoop();
    const vis = () => { if (document.hidden) stopLoop(); else if (!io) startLoop(); else { io.unobserve(stage.current); io.observe(stage.current); } };
    document.addEventListener('visibilitychange', vis);
    tick(performance.now());
    return () => { stopLoop(); if (io) io.disconnect(); document.removeEventListener('visibilitychange', vis); };
  }, []);

  const act = ACTS[k];
  const [phAct, phWho] = phase.split(':');
  const label = phAct === 'hero' ? 'Abertura · sede Kiroo' : phAct === 'wide' ? 'Plano geral · 6 agentes'
    : `Ato ${act.n} · ${phWho ? CREW[phWho].name + ', ' + CREW[phWho].role.toLowerCase() : act.name}`;
  return (
    <div className="lp-stage" ref={stage}>
      {/* câmera (decorativa): o conteúdo ao redor diz o mesmo em texto */}
      <div className="lp-cam" ref={cam} aria-hidden="true">
        <div className="lp-frame" ref={frame}>
          <div className="lp-frame-in">
            <div className="lp-scene" ref={scene} data-phase={phAct}>
              {ART.sede ? <img src={ART.sede} alt="" width={IMG.w} height={IMG.h} draggable="false" /> : <div className="lp-scene-empty" />}
              <Tags />
            </div>
            <span className="lp-vf is-tl" /><span className="lp-vf is-tr" /><span className="lp-vf is-bl" /><span className="lp-vf is-br" />
            <div className="lp-hud">
              <span className="lp-hud-rec"><span className="lp-rec" />REC</span>
              <span className="lp-hud-label" key={label}>{label}</span>
              <span className="lp-hud-tc" ref={tc}>00:00</span>
            </div>
          </div>
        </div>
      </div>

      <div className="lp-stage-flow">
        {/* ------------------------------------------------ abertura */}
        <section className="lp-open lp-pad" aria-labelledby="lp-h1">
          <p className="lp-open-k"><span className="lp-rec" aria-hidden="true" />Kiroo · estúdio criativo</p>
          <h1 id="lp-h1" className="lp-h1">
            <span className="lp-ln" style={{ '--i': 0 }}><span>Seu estúdio criativo</span></span>
            <span className="lp-ln is-r" style={{ '--i': 1 }}><span>de vídeos com&nbsp;IA.</span></span>
          </h1>
          <div className="lp-open-row">
            <p className="lp-lead">Uma equipe de agentes planeja, cria, anima, revisa e edita. Você dirige e aprova o que importa.</p>
            <div className="lp-open-cta">
              <button type="button" className="lp-btn is-ink is-lg" onClick={start}><span>{startLabel}</span><ArrowRight size={18} aria-hidden="true" /></button>
              <a className="lp-btn is-line is-lg" href="#bastidores" onClick={go('bastidores')}><span>Ver os bastidores</span></a>
            </div>
            <p className="lp-open-note">
              {signupOpen ? <>Começa no <strong>DEMO</strong>, sem custo.</> : 'Acesso por convite.'}
            </p>
          </div>
          <div className="lp-slot is-hero" ref={heroSlot} />
        </section>

        {/* ------------------------------------------------ plano geral: a sede inteira, com um intertítulo */}
        <div className="lp-inter lp-pad">
          <p className="lp-inter-card">
            <span className="lp-mono">Plano geral</span>
            <span className="lp-nobr">Seis agentes,</span> <span className="lp-nobr">uma sede.</span><br />Cada sala é uma etapa <span className="lp-nobr">da produção.</span>
          </p>
        </div>

        {/* ------------------------------------------------ três atos */}
        <section id="bastidores" className="lp-acts-sec lp-pad" ref={actsSec} aria-labelledby="lp-bk-t" tabIndex={-1}>
          <div className="lp-acts-head">
            <p className="lp-kick"><span className="lp-clap" aria-hidden="true" />Bastidores</p>
            <h2 id="lp-bk-t" className="lp-h2">Do briefing ao vídeo,<br />em três atos</h2>
          </div>
          <div className="lp-slot is-acts" ref={actsSlot} />
          <ol className="lp-acts">
            {ACTS.map((a, i) => (
              <li key={a.id} className={'lp-act' + (k === i ? ' is-on' : '')} data-i={i} ref={(el) => { actEls.current[i] = el; }}>
                <span className="lp-act-n" aria-hidden="true">{String(a.n).padStart(2, '0')}</span>
                <p className="lp-mono">Ato {a.n} · {a.name}</p>
                <h3 className="lp-h3">{a.title}</h3>
                <p className="lp-act-d">{ACT_COPY[a.id].d}</p>
                <ul className="lp-act-crew">
                  {a.crew.map((id) => (
                    <li key={id} className={k === i && phWho === id ? 'is-cam' : undefined}>
                      <Portrait id={id} size={36} />
                      <span><strong>{CREW[id].name}</strong>{CREW[id].role}</span>
                      <em className={'is-' + CREW[id].state}>{STATE[CREW[id].state]}{CREW[id].state === 'need' && <b className="lp-need" aria-hidden="true">!</b>}</em>
                    </li>
                  ))}
                </ul>
                <p className="lp-act-you"><AgentHead active size={14} />{ACT_COPY[a.id].you}</p>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}
