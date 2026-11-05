import React from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeft, ArrowRight, Plus, X } from 'lucide-react';
import wordmark from '../assets/brand/wordmark-preto-laranja.svg';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { STEPS, createTour, layoutFor, placeCard, progress, text } from './tour.js';
import './onboarding.css';

// Kit de onboarding (Fase 5). Carregado com lazy import só quando o tour abre (onboarding_done_at nulo ou "Rever tutorial").
// O estado do tour vive aqui (fora do loop do Phaser e do tick do App); a posição do spotlight só muda quando o alvo
// muda de lugar ou tamanho (ResizeObserver + resize/scroll agrupados num rAF), sem re-render por frame.

const q = (id) => document.querySelector(`[data-tour="${id}"]`);
const vpNow = () => ({ w: window.innerWidth, h: window.innerHeight });
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// Recorte da máscara: o Chromium não repinta máscara SVG com x/y/width/height vindos de CSS, então a transição
// é um tween curto que escreve os atributos direto no <rect> (só durante a troca de passo; nada roda parado).
const reduced = () => typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function useCutTween(ref, hole) {
  const last = React.useRef(null);
  React.useLayoutEffect(() => {
    const el = ref.current; if (!el) return undefined;
    const set = (b) => { el.setAttribute('x', b.x); el.setAttribute('y', b.y); el.setAttribute('width', Math.max(0, b.w)); el.setAttribute('height', Math.max(0, b.h)); };
    const from = last.current; last.current = hole;
    if (!from || reduced() || document.hidden) { set(hole); return undefined; }
    let raf = 0; const t0 = performance.now(), D = 350;
    const tick = (now) => {
      const k = Math.min(1, (now - t0) / D), e = 1 - Math.pow(1 - k, 3);
      set({ x: from.x + (hole.x - from.x) * e, y: from.y + (hole.y - from.y) * e, w: from.w + (hole.w - from.w) * e, h: from.h + (hole.h - from.h) * e });
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [hole.x, hole.y, hole.w, hole.h]); // eslint-disable-line react-hooks/exhaustive-deps
}

function Dots({ i, ctx }) {
  const { n, total } = progress(i, ctx);
  return (
    <div className="ob-progress" aria-label={`Passo ${n} de ${total}`}>
      <span className="ob-dots" aria-hidden="true">{Array.from({ length: total }, (_, k) => <i key={k} data-on={k < n || undefined} />)}</span>
      <span className="ob-count" aria-hidden="true">{n} de {total}</span>
    </div>
  );
}

function SkipConfirm({ onYes, onNo }) {
  return (
    <div className="ob-confirm" role="group" aria-label="Confirmar pular tutorial">
      <p>Pular o tutorial? Dá para rever depois em Conta e preferências.</p>
      <div className="ob-actions">
        <button type="button" className="ob-btn" onClick={onNo} autoFocus>Continuar o tour</button>
        <button type="button" className="ob-btn ob-primary" onClick={onYes}>Pular</button>
      </div>
    </div>
  );
}

function Check() {
  return (
    <svg className="ob-check" viewBox="0 0 52 52" aria-hidden="true">
      <circle cx="26" cy="26" r="24" />
      <path d="M15 27 l7.5 7.5 L37 19" />
    </svg>
  );
}

function Onboarding({ start = 0, ctx, api, onClosed }) {
  const ctxRef = React.useRef(ctx); ctxRef.current = ctx;
  const tour = React.useMemo(() => createTour({ start, ctx, save: api.save }), []); // eslint-disable-line react-hooks/exhaustive-deps
  const [i, setI] = React.useState(tour.index);
  const [confirm, setConfirm] = React.useState(false);
  const [lay, setLay] = React.useState({ mode: 'pending' });
  const [card, setCard] = React.useState(null);
  const cardRef = React.useRef(null);
  const cutRef = React.useRef(null);
  const step = STEPS[i];

  const go = (fn) => { setConfirm(false); setI(fn()); };
  const next = () => (tour.isLast ? finish('explore') : go(() => tour.next()));
  const prev = () => go(() => tour.prev());
  const close = () => { tour.close(); onClosed('closed'); };
  const skip = () => { tour.skip(); onClosed('done'); };
  const finish = (how) => { tour.finish(); onClosed('done'); if (how === 'mission') api.newMission(); };

  // a primeira vez já salva o passo (conta nova que fecha a aba no passo 1 volta para ele)
  React.useEffect(() => { api.save({ step: i }); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // troca a view pedida pelo passo e mede o alvo; tenta por ~700 ms (a view nova ainda pode estar montando)
  React.useEffect(() => {
    if (step.view) api.setView(step.view);
    if (step.kind === 'dialog') { setLay({ mode: 'dialog' }); return undefined; }
    let raf = 0, tries = 0, alive = true;
    const measure = () => {
      raf = 0;
      if (!alive) return;
      const l = layoutFor(step, q, vpNow());
      if (l.mode === 'center' && tries++ < 40) { raf = requestAnimationFrame(measure); return; }
      setLay((old) => (same(old, l) ? old : l));
    };
    const schedule = () => { if (!raf) raf = requestAnimationFrame(measure); };
    setLay((old) => (old.mode === 'spot' ? old : { mode: 'pending' }));
    schedule();
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(schedule) : null;
    if (ro) { ro.observe(document.body); (step.targets || []).forEach((id) => { const el = q(id); if (el) ro.observe(el); }); }
    window.addEventListener('resize', schedule);
    window.addEventListener('scroll', schedule, true);
    const iv = setInterval(() => { tries = 99; cancelAnimationFrame(raf); measure(); }, 500); // painel recolhido, alvo que some ou aparece
    return () => { alive = false; cancelAnimationFrame(raf); if (ro) ro.disconnect(); clearInterval(iv); window.removeEventListener('resize', schedule); window.removeEventListener('scroll', schedule, true); };
  }, [i]); // eslint-disable-line react-hooks/exhaustive-deps

  // posição do card: depende do recorte e do tamanho real do card
  React.useLayoutEffect(() => {
    if (lay.mode !== 'spot' && lay.mode !== 'center') return;
    const el = cardRef.current; if (!el) return;
    const size = { w: el.offsetWidth, h: el.offsetHeight }, vp = vpNow();
    const p = lay.mode === 'spot' ? placeCard(lay.rect, size, vp, step.side)
      : { x: (vp.w - size.w) / 2, y: (vp.h - size.h) / 2, side: 'center', arrow: null };
    setCard((old) => (same(old, p) ? old : p));
  }, [lay, i, confirm]); // eslint-disable-line react-hooks/exhaustive-deps

  // foco no botão principal a cada passo
  React.useEffect(() => {
    if (lay.mode !== 'spot' && lay.mode !== 'center') return;
    const b = cardRef.current && cardRef.current.querySelector('[data-primary]');
    if (b && !cardRef.current.contains(document.activeElement)) b.focus({ preventScroll: true });
  }, [i, lay.mode]);

  // Esc fecha (salva o passo) mesmo com o foco no mundo, no passo do escritório
  React.useEffect(() => {
    if (step.kind === 'dialog') return undefined;
    const h = (e) => { if (e.key === 'Escape' && !document.querySelector('[role="dialog"][data-state="open"]')) { e.preventDefault(); close(); } };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }); // eslint-disable-line react-hooks/exhaustive-deps

  const onCardKey = (e) => {
    if (e.key === 'Tab') { // foco preso no card
      const f = Array.from(cardRef.current.querySelectorAll('button:not(:disabled)'));
      if (!f.length) return;
      const k = f.indexOf(document.activeElement);
      if (e.shiftKey && k <= 0) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && k === f.length - 1) { e.preventDefault(); f[0].focus(); }
      return;
    }
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); return; }
    if (step.interactive) return;  // no escritório as setas andam
    if (e.key === 'ArrowRight' && !confirm) { e.preventDefault(); next(); }
    else if (e.key === 'ArrowLeft' && !confirm && !tour.isFirst) { e.preventDefault(); prev(); }
    e.stopPropagation();           // fora do escritório, nada vaza para os atalhos do jogo
  };

  const r = lay.mode === 'spot' ? lay.rect : null;
  const vp = vpNow();
  const hole = r || { x: vp.w / 2, y: vp.h / 2, w: 0, h: 0 };
  useCutTween(cutRef, hole);  // antes de qualquer return: ordem fixa de hooks

  const title = text(step.title, ctx);
  const body = text(step.body, ctx);

  if (step.kind === 'dialog') {
    const final = !!step.final;
    const onKey = (e) => {
      e.stopPropagation();
      if (confirm) return;
      if (e.key === 'ArrowRight' && !final) { e.preventDefault(); next(); }
      else if (e.key === 'ArrowLeft' && !tour.isFirst) { e.preventDefault(); prev(); }
    };
    return (
      <Dialog open onOpenChange={(o) => { if (!o) close(); }}>
        <DialogContent showCloseButton={false} className="ob-dialog" onKeyDown={onKey}
          onInteractOutside={(e) => e.preventDefault()} aria-describedby="ob-body">
          <button type="button" className="ob-x" onClick={close} aria-label="Fechar tutorial (continua daqui depois)"><X size={16} aria-hidden="true" /></button>
          {final ? <Check /> : <>{step.id === 'welcome' && <img className="ob-wordmark" src={wordmark} alt="Kiroo" height="22" />}<span className="ob-badge">Tour rápido · 1 min</span></>}
          <DialogTitle className="ob-title" aria-live="polite">{title}</DialogTitle>
          <DialogDescription id="ob-body" className="ob-body">{body}</DialogDescription>
          {confirm ? <SkipConfirm onYes={skip} onNo={() => setConfirm(false)} /> : final ? (
            <div className="ob-actions ob-actions-end">
              <button type="button" className="ob-btn" onClick={() => finish('explore')}>Explorar sozinho</button>
              <button type="button" className="ob-btn ob-primary" onClick={() => finish('mission')} autoFocus><Plus size={16} aria-hidden="true" />Criar primeira missão</button>
            </div>
          ) : (<>
            <Dots i={i} ctx={ctx} />
            <div className="ob-actions">
              <button type="button" className="ob-link" onClick={() => setConfirm(true)}>Pular tutorial</button>
              <span className="ob-fill" />
              <button type="button" className="ob-btn ob-primary" onClick={next} autoFocus>Começar o tour<ArrowRight size={16} aria-hidden="true" /></button>
            </div>
          </>)}
        </DialogContent>
      </Dialog>
    );
  }

  const ready = card && (lay.mode === 'spot' || lay.mode === 'center');
  return createPortal(
    <div className="ob-layer" data-mode={lay.mode}>
      {/* escurece tudo menos o recorte arredondado (máscara SVG; o recorte anda por useCutTween, sem re-render) */}
      <svg className="ob-dim" aria-hidden="true">
        <defs><mask id="ob-mask"><rect width="100%" height="100%" fill="#fff" />
          <rect ref={cutRef} rx="14" fill="#000" /></mask></defs>
        <rect width="100%" height="100%" mask="url(#ob-mask)" />
      </svg>
      <div className="ob-hole" data-empty={!r || undefined} style={{ left: hole.x, top: hole.y, width: hole.w, height: hole.h }} aria-hidden="true" />
      {/* bloqueiam o clique fora do alvo; o alvo (e o mundo, no passo do escritório) continua usável */}
      <div className="ob-block" style={{ left: 0, top: 0, right: 0, height: hole.y }} onMouseDown={(e) => e.preventDefault()} />
      <div className="ob-block" style={{ left: 0, top: hole.y + hole.h, right: 0, bottom: 0 }} onMouseDown={(e) => e.preventDefault()} />
      <div className="ob-block" style={{ left: 0, top: hole.y, width: hole.x, height: hole.h }} onMouseDown={(e) => e.preventDefault()} />
      <div className="ob-block" style={{ left: hole.x + hole.w, top: hole.y, right: 0, height: hole.h }} onMouseDown={(e) => e.preventDefault()} />
      <section ref={cardRef} className="ob-card" role="dialog" aria-modal={step.interactive ? 'false' : 'true'} aria-labelledby="ob-card-title" aria-describedby="ob-card-body"
        data-side={card ? card.side : undefined} data-ready={ready || undefined} onKeyDown={onCardKey}
        style={{ left: card ? card.x : -9999, top: card ? card.y : -9999 }}>
        {card && card.arrow != null && <span className="ob-arrow" aria-hidden="true"
          style={card.side === 'top' || card.side === 'bottom' ? { left: card.arrow } : { top: card.arrow }} />}
        <header className="ob-card-head">
          <h2 id="ob-card-title" className="ob-title" aria-live="polite">{title}</h2>
          <button type="button" className="ob-x ob-x-card" onClick={close} aria-label="Fechar tutorial (continua daqui depois)"><X size={16} aria-hidden="true" /></button>
        </header>
        <p id="ob-card-body" className="ob-body">{body}</p>
        {confirm ? <SkipConfirm onYes={skip} onNo={() => setConfirm(false)} /> : (<>
          <Dots i={i} ctx={ctx} />
          <div className="ob-actions">
            <button type="button" className="ob-link" onClick={() => setConfirm(true)}>Pular tutorial</button>
            <span className="ob-fill" />
            {!tour.isFirst && <button type="button" className="ob-btn" onClick={prev}><ArrowLeft size={16} aria-hidden="true" />Voltar</button>}
            <button type="button" className="ob-btn ob-primary" data-primary onClick={next}>Próximo<ArrowRight size={16} aria-hidden="true" /></button>
          </div>
        </>)}
      </section>
    </div>,
    document.body,
  );
}

// O App re-renderiza a cada tick do jogo; o tour só re-renderiza quando o que ele mostra muda.
const sameProps = (a, b) => a.start === b.start && a.api === b.api && a.onClosed === b.onClosed
  && a.ctx.world === b.ctx.world && a.ctx.walletExempt === b.ctx.walletExempt && a.ctx.pilotLabel === b.ctx.pilotLabel;
export default React.memo(Onboarding, sameProps);
