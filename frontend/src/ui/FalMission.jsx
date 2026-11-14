import React from 'react';
import { falFacts, stepBelt } from './falBelt.js';
import { falStations } from './falFlow.js';

// Missão do fluxo foto + estilo: o cartão de status (sempre o estado REAL do servidor) e, quando pronta, a entrega
// (vídeo + 1 foto + título e legenda copiáveis). Fica na própria tela da Missão, abaixo da esteira.

function CopyField({ label, text }) {
  const [copied, setCopied] = React.useState(false);
  const ref = React.useRef(null);
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch (e) {
      const sel = window.getSelection && window.getSelection();
      if (sel && ref.current) { const r = document.createRange(); r.selectNodeContents(ref.current); sel.removeAllRanges(); sel.addRange(r); }
    }
  };
  return (
    <div className="pv-card" style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <span className="pv-meta" style={{ marginTop: 0 }}>{label}</span>
      <span ref={ref} style={{ fontSize: 14, lineHeight: 1.5, whiteSpace: 'pre-wrap', userSelect: 'text' }}>{text}</span>
      <button className="pv-btn" onClick={copy} aria-label={'Copiar ' + label.toLowerCase()} style={{ alignSelf: 'flex-start' }}>{copied ? 'Copiado!' : 'Copiar'}</button>
    </div>
  );
}

const TONE = { failed: '#FFE1DA', limit: '#FFE7C2', paused: '#FFE7C2', finalizing: '#F2F2EF', done: '#E3F5DC', partial: '#FFE7C2' };

// Estado animado da esteira. O servidor só muda a cada poll (1,5 s) e pode pular etapas (a fal termina de uma vez);
// aqui o estado exibido anda em direção ao real sem saltos (falBelt.stepBelt). É estimativa: ver falBelt.js.
export function useFalBelt(P) {
  const pid = P && P.id;
  const first = () => { const now = Date.now(); return { key: pid, st: stepBelt(null, falFacts(P, now), now) }; };
  const [view, setView] = React.useState(first);
  const pRef = React.useRef(P);
  pRef.current = P;
  React.useEffect(() => {
    const tick = () => setView((v) => {
      const p = pRef.current, now = Date.now();
      const prev = v.key === p.id ? v.st : null;
      const nx = stepBelt(prev, falFacts(p, now), now);
      return nx === prev ? v : { key: p.id, st: nx };
    });
    tick();
    const id = setInterval(tick, 120);
    return () => clearInterval(id);
  }, [pid]);
  // o poll chegou entre dois tiques: aplica o estado novo já neste desenho (sem um quadro com a esteira atrasada)
  const now = Date.now();
  const st = stepBelt(view.key === pid ? view.st : null, falFacts(P, now), now);
  return falStations(P, now, st);
}

// Tamanho fixo em todos os estados (nada muda de altura entre polls): título e texto com altura reservada e reticências,
// barra geral sempre presente e vaga reservada para o botão.
const clip = (h, lines = 1) => ({ height: h, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: lines, WebkitBoxOrient: 'vertical' });

export function FalStatusCard({ m }) {
  const st = m.status;
  if (!st) return null;
  const pct = st.kind === 'running' || st.kind === 'done' ? m.progress : 0;
  return (
    <section className="pv-card" aria-label="Status" role="status" style={{ padding: 18, height: 190, boxSizing: 'border-box', display: 'flex', flexDirection: 'column', gap: 10, background: TONE[st.kind], overflow: 'hidden' }}>
      <div className="pv-title" style={{ fontSize: 18, lineHeight: '24px', ...clip(24) }}>{st.label}</div>
      <div style={{ fontSize: 14, lineHeight: '20px', ...clip(40, 2) }}>{st.text}</div>
      <div className="pv-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={'Progresso estimado: ' + pct + '%'} style={{ flex: 'none' }}><i style={{ width: pct + '%' }} /></div>
      <div style={{ height: 40, flex: 'none', display: 'flex', alignItems: 'center' }}>
        {m.error ? <div role="alert" style={{ fontSize: 14, fontWeight: 700, ...clip(40, 2) }}>{m.error}</div>
          : st.action === 'start' ? <button className="pv-btn pv-btn-lime" onClick={m.start} disabled={m.busy}>{m.busy ? 'Começando…' : m.startLabel}</button> : null}
      </div>
    </section>
  );
}

export function FalDelivery({ m }) {
  const g = m.gallery;
  if (!g || !g.video) return null;
  const box = { width: 190, height: 338, objectFit: 'cover', borderRadius: 14 };
  return (
    <section className="pv-card" aria-label="Entrega" style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div className="pv-h2" style={{ margin: 0 }}>Entrega</div>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <figure style={{ margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <video src={g.video.url} controls muted loop playsInline preload="metadata" aria-label="Vídeo final" style={{ ...box, background: '#0F1730' }} />
          <a className="pv-btn" href={g.video.download} download>Baixar vídeo</a>
        </figure>
        {g.image && g.image.url && (
          <figure style={{ margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
            <img src={g.image.url} alt="Foto do produto" style={{ ...box, border: '1px solid #E7E7E4' }} />
            <a className="pv-btn" href={g.image.download} download>Baixar foto</a>
          </figure>
        )}
        <div style={{ flex: '1 1 260px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {g.title && <CopyField label="Título" text={g.title} />}
          {g.caption && <CopyField label="Legenda" text={g.caption} />}
          {g.textMissing && <div className="pv-card" style={{ padding: 14, fontSize: 14 }}>O vídeo veio sem título e legenda. Escreva os seus antes de publicar.</div>}
          {g.captionFile && <a className="pv-btn" href={g.captionFile.download} download style={{ alignSelf: 'flex-start' }}>Baixar legenda com aviso de publicidade</a>}
        </div>
      </div>
      {g.partial && <div className="pv-meta">Entrega parcial: a foto não ficou pronta.</div>}
      <div className="pv-meta">Ao publicar na Shopee, marque o conteúdo como publicidade. A publicação é manual.</div>
      {m.P.status === 'awaiting_final_review' && <button className="pv-btn pv-btn-lime" onClick={m.exportVideo} disabled={m.busy} style={{ alignSelf: 'flex-start' }}>Marcar como exportado</button>}
    </section>
  );
}
