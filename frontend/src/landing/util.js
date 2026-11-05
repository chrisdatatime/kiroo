import React from 'react';

// Rolagem até uma âncora dentro da home (o .lp rola dentro de si); suave só sem redução de movimento.
export const go = (id) => (e) => {
  e.preventDefault();
  const el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  el.focus({ preventScroll: true });
};

export function useMedia(q) {
  const get = () => typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia(q).matches;
  const [v, setV] = React.useState(get);
  React.useEffect(() => {
    if (!window.matchMedia) return undefined;
    const m = window.matchMedia(q), h = () => setV(m.matches);
    h();
    if (m.addEventListener) m.addEventListener('change', h); else m.addListener(h);
    return () => { if (m.removeEventListener) m.removeEventListener('change', h); else m.removeListener(h); };
  }, [q]);
  return v;
}

// Marca o elemento com .is-in quando entra na tela (uma vez). Para revelações coreografadas por CSS.
export function useInView(opts = { rootMargin: '0px 0px -18% 0px' }) {
  const ref = React.useRef(null);
  const [inView, setIn] = React.useState(false);
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    if (!('IntersectionObserver' in window)) { setIn(true); return undefined; }
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setIn(true); io.disconnect(); } }, opts);
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return [ref, inView];
}

// Progresso 0..1 de um elemento atravessando a tela (de `from` a `to`, em fração da altura), escrito em --p. Sem re-render.
export function useScrollVar(from = 0.9, to = 0.35) {
  const ref = React.useRef(null);
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) { el.style.setProperty('--p', 1); return undefined; }
    const box = el.closest('.lp') || window;
    let raf = 0;
    const upd = () => {
      raf = 0;
      const r = el.getBoundingClientRect(), vh = window.innerHeight;
      const p = (vh * from - r.top) / (vh * (from - to));
      el.style.setProperty('--p', Math.max(0, Math.min(1, p)).toFixed(3));
    };
    const on = () => { if (!raf) raf = requestAnimationFrame(upd); };
    box.addEventListener('scroll', on, { passive: true });
    window.addEventListener('resize', on);
    upd();
    return () => { box.removeEventListener('scroll', on); window.removeEventListener('resize', on); if (raf) cancelAnimationFrame(raf); };
  }, [from, to]);
  return ref;
}
