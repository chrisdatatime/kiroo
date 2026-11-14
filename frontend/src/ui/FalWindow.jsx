import React from 'react';
import { Spinner, CloseButton } from './bits.jsx';
import { CONFIRM_LABEL, needsConfirmation, summaryRows } from './nextVideo.js';
import { STYLES, FINAL_FINALIZING } from './falFlow.js';

// Janela da produção no fluxo "foto + estilo": Criar, Acompanhar e Entrega. Só aparece com o motor novo ligado
// (v.fal vem de App.viewModel). Nenhuma tela cita fornecedor, modelo ou fila técnica.
const card = { padding: 16, display: 'flex', flexDirection: 'column', gap: 10 };

function TabCriar({ f }) {
  if (f.P) {
    const P = f.P;
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div className="g-card" style={card}>
          <strong className="fred" style={{ fontSize: 18, fontWeight: 600 }}>{P.product && P.product.name ? P.product.name : 'Seu produto'}</strong>
          <span className="g-muted" style={{ fontSize: 13.5 }}>Estilo {f.view.styleLabel}. A foto foi recebida.</span>
        </div>
        {needsConfirmation(P) && (
          <section className="g-card" aria-labelledby="fal-nv" style={{ ...card, background: '#FFFFFF', border: '2px solid #0E0E10' }}>
            <span className="g-label" style={{ color: '#3F5200' }}>Antes de começar</span>
            <strong id="fal-nv" className="fred" style={{ fontSize: 20, fontWeight: 600 }}>Seu próximo vídeo</strong>
            <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', gap: '8px 16px', fontSize: 13.5 }}>
              {summaryRows(P.confirmation.summary).map(([k, val]) => <div key={k}><dt className="g-label">{k}</dt><dd style={{ margin: 0, fontWeight: 800 }}>{val}</dd></div>)}
            </dl>
            <span style={{ font: '800 13.5px/1.4 Instrument Sans,sans-serif', color: '#205C2E' }}>{P.confirmation.summary.no_extra_cost}</span>
            <span className="g-muted" style={{ fontSize: 12.5 }}>Sem confirmação, nada é gasto. Se a geração falhar por erro técnico, ela não é cobrada.</span>
            <button className="g-btn g-lime" onClick={f.confirm} disabled={f.busy}>{f.busy ? 'Confirmando…' : CONFIRM_LABEL}</button>
          </section>
        )}
        {!needsConfirmation(P) && <button className="g-btn" onClick={f.goTrack} style={{ alignSelf: 'flex-start' }}>Acompanhar</button>}
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'flex-start' }}>
      <div style={{ flex: '1 1 300px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <span className="g-label">1. Foto do produto</span>
        <label className="g-pick" style={{ padding: 16, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, cursor: 'pointer', borderStyle: 'dashed' }}>
          {f.file ? <img src={f.file.data} alt={'Sua foto: ' + f.file.name} style={{ maxWidth: 220, maxHeight: 260, borderRadius: 10, objectFit: 'contain' }} />
            : <><strong style={{ fontSize: 15 }}>Escolher a foto</strong><span className="g-muted" style={{ fontSize: 12.5 }}>JPG, PNG ou WEBP. O Kiroo cuida do resto.</span></>}
          <input type="file" accept="image/jpeg,image/png,image/webp" onChange={f.pick} style={{ position: 'absolute', opacity: 0, width: 1, height: 1 }} aria-label="Foto do produto" />
        </label>
        {f.file && <button className="g-btn g-sm g-quiet" onClick={f.clearFile} style={{ alignSelf: 'flex-start' }}>Trocar foto</button>}
        <label className="g-label" htmlFor="fal-name">Nome do produto <span className="g-muted">(opcional)</span></label>
        <input id="fal-name" className="g-field" value={f.name} onChange={f.setName} placeholder="Se ficar vazio, o Kiroo descreve pela foto" />
      </div>
      <div style={{ flex: '1 1 300px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <span className="g-label" id="fal-style-l">2. Estilo do vídeo</span>
        <div role="radiogroup" aria-labelledby="fal-style-l" style={{ display: 'grid', gap: 10 }}>
          {STYLES.map((s) => (
            <button key={s.id} type="button" role="radio" aria-checked={f.style === s.id} className="g-card" onClick={() => f.setStyle(s.id)}
              style={{ ...card, textAlign: 'left', cursor: 'pointer', minHeight: 44, border: f.style === s.id ? '2px solid #0E0E10' : '1px solid #E7E7E4', background: s.id === 'dark' ? '#0E0E10' : '#FFFFFF', color: s.id === 'dark' ? '#FFFFFF' : '#0E0E10' }}>
              <strong style={{ fontSize: 16 }}>{s.label}{f.style === s.id ? ' ✓' : ''}</strong>
              <span style={{ fontSize: 13, lineHeight: 1.4, opacity: 0.85 }}>{s.hint}</span>
            </button>
          ))}
        </div>
        <span className="g-muted" style={{ fontSize: 12.5 }}>Você recebe um vídeo de ~15 s com narração, uma foto publicitária (Hero Shot) e o título e a legenda para copiar.</span>
        {f.mode === 'simulated' && <span className="g-sim" style={{ alignSelf: 'flex-start' }}>modo DEMO: nada é cobrado</span>}
        <button className="g-btn g-lime" onClick={f.create} disabled={f.busy || f.errors.length > 0}>{f.busy ? 'Enviando…' : 'Criar meu vídeo'}</button>
        {f.errors.length > 0 && <span className="g-muted" style={{ fontSize: 12.5 }}>Falta: {f.errors.join(', ')}.</span>}
      </div>
    </div>
  );
}

function TabAcompanhar({ f }) {
  const w = f.view;
  if (!w) return <div className="g-card" style={card}>Nada em andamento. Crie um vídeo na aba Criar.</div>;
  const msg = {
    creating: 'Preparando a sua foto.', queued: 'Sua missão está na fila' + (w.queuePosition ? ` (posição ${w.queuePosition + 1})` : '') + '.',
    working: 'Estamos criando o vídeo com narração, a foto, o título e a legenda. Pode circular pelo estúdio: avisamos quando terminar.',
    composing: 'Tudo recebido. Conferindo o vídeo final.', ready: 'Seu pacote está pronto. Veja na aba Entrega.',
    done: 'Pacote exportado.', finalizing: FINAL_FINALIZING, paused: 'A missão está pausada.',
    failed: f.P.reason || 'Não foi possível gerar o seu vídeo desta vez. Nada foi cobrado.', cancelled: 'Missão cancelada. Nada mais é gerado nem cobrado.',
    partial: 'Entrega parcial: a foto não ficou pronta e a missão foi encerrada. Nada mais é gerado nem cobrado.',
  }[w.phase];
  return (
    <div role="status" className="g-card" style={{ ...card, flexDirection: 'row', alignItems: 'center', gap: 14 }}>
      {w.busy && <Spinner size={26} />}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <strong style={{ fontSize: 16 }}>{w.label}</strong>
        <span style={{ fontSize: 14, lineHeight: 1.45 }}>{msg}</span>
        {f.P.mode === 'simulated' && <span className="g-sim" style={{ alignSelf: 'flex-start' }}>modo DEMO</span>}
      </div>
    </div>
  );
}

function Item({ label, children }) {
  return <figure style={{ margin: 0, display: 'flex', flexDirection: 'column', gap: 6, width: 190 }}><div style={{ position: 'relative' }}>{children}</div><figcaption className="g-label">{label}</figcaption></figure>;
}

// Campo de texto com botão "Copiar" (área de transferência; sem ela, seleciona o texto para copiar à mão).
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
    <div className="g-card" style={card}>
      <span className="g-label">{label}</span>
      <span ref={ref} style={{ fontSize: 14, lineHeight: 1.5, whiteSpace: 'pre-wrap', userSelect: 'text' }}>{text}</span>
      <button className="g-btn g-sm" onClick={copy} aria-label={'Copiar ' + label.toLowerCase()} style={{ alignSelf: 'flex-start' }}>{copied ? 'Copiado!' : 'Copiar'}</button>
    </div>
  );
}

function TabEntrega({ f }) {
  const g = f.gallery;
  if (!g || !g.video) {
    return <div className="g-card" style={card}>{f.view && f.view.finalizing ? FINAL_FINALIZING : 'O pacote aparece aqui quando estiver pronto.'}</div>;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <Item label="Vídeo final">
          <video src={g.video.url} controls muted loop playsInline preload="metadata" aria-label="Vídeo final" style={{ width: 190, height: 338, objectFit: 'cover', borderRadius: 14, background: '#0F1730' }} />
          <a className="g-btn g-sm" href={g.video.download} download style={{ marginTop: 6 }}>Baixar vídeo (MP4)</a>
        </Item>
        {g.image && (
          <Item label={g.image.label}>
            {g.image.url ? <><img src={g.image.url} alt={g.image.label} style={{ width: 190, height: 338, objectFit: 'cover', borderRadius: 14, border: '1px solid #E7E7E4' }} />
              <a className="g-btn g-sm" href={g.image.download} download style={{ marginTop: 6 }}>Baixar {g.image.label}</a></>
              : <div className="g-card" style={{ width: 190, height: 338, display: 'grid', placeItems: 'center', textAlign: 'center', padding: 12, fontSize: 13 }}>Em finalização</div>}
          </Item>
        )}
        <div style={{ flex: '1 1 280px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {g.title && <CopyField label="Título" text={g.title} />}
          {g.caption && <CopyField label="Legenda" text={g.caption} />}
          {g.textMissing && <div role="status" className="g-card" style={{ ...card, fontSize: 13.5 }}>O vídeo não trouxe título nem legenda. Escreva os seus antes de publicar.</div>}
        </div>
      </div>
      {g.partial && <div role="status" className="g-card" style={{ ...card, background: '#FFE7C2', border: '2px solid #7A4300', fontSize: 13.5 }}>Entrega parcial: a foto ainda não ficou pronta. O que já está aqui pode ser baixado.</div>}
      <div className="g-card" style={{ ...card, fontSize: 13, lineHeight: 1.45 }}>
        O vídeo não leva aviso na tela: a identificação de publicidade e de imagens geradas por IA está no arquivo da legenda. Ao publicar, marque também o conteúdo como publicidade na Shopee e confira as regras atuais.
        {g.captionFile && <a className="g-btn g-sm" href={g.captionFile.download} download style={{ alignSelf: 'flex-start' }}>Baixar legenda completa (TXT)</a>}
      </div>
      {f.P && f.P.status === 'awaiting_final_review' && <div><button className="g-btn g-lime" onClick={f.exportVideo} disabled={f.busy}>Exportar</button></div>}
      {f.P && f.P.status === 'completed' && <div role="status" style={{ padding: 12, borderRadius: 12, background: '#E3F5DC', border: '2px solid #2D7A3E', fontSize: 13.5 }}><strong style={{ color: '#205C2E' }}>Exportado.</strong> A publicação na Shopee Vídeo é manual: baixe os arquivos e envie pelo app.</div>}
    </div>
  );
}

export default function FalWindow({ v }) {
  const f = v.fal;
  const tabs = [['criar', 'Criar'], ['acompanhar', 'Acompanhar'], ['entrega', 'Entrega']];
  return (
    <section role="dialog" aria-labelledby="fal-h" className="g-panel pop" style={{ position: 'fixed', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', zIndex: 60, width: 'min(1000px,calc(100vw - 24px))', height: 'min(680px,calc(100vh - 24px))', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: '12px 14px 0', background: '#F2F2EF', borderBottom: '1px solid #E7E7E4', display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <h2 id="fal-h" className="fred" style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>{f.P && f.P.product && f.P.product.name ? f.P.product.name : (f.P ? 'Seu vídeo' : 'Novo vídeo')}</h2>
          {f.view && <span style={{ font: '800 12px/1 Instrument Sans,sans-serif', padding: '5px 9px', borderRadius: 999, background: '#0E0E10', color: '#fff' }}>{f.view.label}</span>}
          <span style={{ flex: 1 }} />
          <span className="g-muted" style={{ font: '800 13px/1 Instrument Sans,sans-serif' }}>{v.spentText}</span>
          <CloseButton onClick={v.closeWin} label="Fechar" />
        </div>
        <div role="tablist" aria-label="Etapas" style={{ display: 'flex', gap: 2, paddingBottom: 8 }}>
          {tabs.map(([id, label]) => <button key={id} role="tab" className="g-tab" aria-selected={f.tab === id} onClick={() => f.setTab(id)}><span>{label}</span></button>)}
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 18 }}>
        {f.tab === 'criar' && <TabCriar f={f} />}
        {f.tab === 'acompanhar' && <TabAcompanhar f={f} />}
        {f.tab === 'entrega' && <TabEntrega f={f} />}
        {f.P && f.canCancel && <div style={{ marginTop: 16 }}><button className="g-btn g-sm g-quiet" onClick={f.cancel}>{f.confirmCancel ? 'Confirmar: cancelar missão' : 'Cancelar missão'}</button></div>}
      </div>
    </section>
  );
}
