import React from 'react';

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

export function FalStatusCard({ m }) {
  const st = m.status;
  if (!st) return null;
  return (
    <section className="pv-card" aria-label="Status" role="status" style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 10, background: TONE[st.kind] }}>
      <div className="pv-title" style={{ fontSize: 18 }}>{st.label}{st.kind === 'running' && st.estimated ? <span className="pv-meta" style={{ fontSize: 12, marginLeft: 8 }}>etapa estimada</span> : null}</div>
      <div style={{ fontSize: 14, lineHeight: 1.45 }}>{st.text}</div>
      {st.kind === 'running' && <div className="pv-bar" role="img" aria-label={'Progresso estimado: ' + m.progress + '%'}><i style={{ width: m.progress + '%' }} /></div>}
      {st.action === 'start' && <button className="pv-btn pv-btn-lime" onClick={m.start} disabled={m.busy} style={{ alignSelf: 'flex-start' }}>{m.busy ? 'Começando…' : m.startLabel}</button>}
      {m.error && <div role="alert" style={{ fontSize: 14, fontWeight: 700 }}>{m.error}</div>}
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
