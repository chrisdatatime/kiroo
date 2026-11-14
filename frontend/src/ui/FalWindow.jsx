import React from 'react';
import { CloseButton } from './bits.jsx';
import { AlertCircle, Camera, RefreshCw, X } from 'lucide-react';
import { RECEIVE_LINE } from './falFlow.js';
import { usePhone } from '../hooks/use-phone.js';

// "Nova produção" no fluxo foto + estilo: SÓ o envio. Foto (solte ou escolha), nome opcional, estilo (só aparece com
// mais de um liberado) e UM botão "Criar vídeo · N créditos". Clicar = consentimento: o App faz create → confirm → run;
// se algo falhar, esta janela continua aberta com a mensagem do servidor. O acompanhamento e a entrega ficam na Missão.
// Nenhuma tela cita fornecedor, modelo ou fila técnica.
const card = { padding: 16, display: 'flex', flexDirection: 'column', gap: 10 };

function DropZone({ f }) {
  const [over, setOver] = React.useState(false);
  const drop = (e) => { e.preventDefault(); setOver(false); const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]; if (file) f.pickFile(file); };
  return (
    <label className="g-pick" onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={drop}
      style={{ position: 'relative', padding: 18, minHeight: 200, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8,
        cursor: 'pointer', borderStyle: 'dashed', background: over ? '#F2F2EF' : undefined }}>
      {f.file ? <img src={f.file.data} alt={'Sua foto: ' + f.file.name} style={{ maxWidth: 220, maxHeight: 240, borderRadius: 10, objectFit: 'contain' }} />
        : <><strong style={{ fontSize: 15 }}>Solte a foto do produto aqui</strong><span className="g-muted" style={{ fontSize: 12.5 }}>ou clique para escolher · JPG, PNG ou WEBP</span></>}
      <input type="file" accept="image/jpeg,image/png,image/webp" onChange={f.pick} style={{ position: 'absolute', opacity: 0, width: 1, height: 1 }} aria-label="Foto do produto" />
    </label>
  );
}

// Celular: tela cheia (sobe de baixo), foto grande, "Criar vídeo" fixo no rodapé e o erro logo acima dele.
// accept="image/*" sem `capture`: o celular oferece a câmera OU as fotos salvas.
function PhoneSheet({ f }) {
  const pickRef = React.useRef(null);
  return (
    <section role="dialog" aria-modal="true" aria-labelledby="fal-h" className="pv-sheet">
      <header className="pv-sheet-head">
        <h2 id="fal-h">Nova produção</h2>
        {f.demo && <span className="pv-status pv-status-demo">DEMO</span>}
        <button type="button" className="pv-sheet-x" onClick={f.close} aria-label="Fechar" disabled={f.busy}><X size={22} aria-hidden="true" /></button>
      </header>
      <div className="pv-sheet-body">
        <input ref={pickRef} id="fal-photo" type="file" accept="image/*" onChange={f.pick} className="pv-file" aria-label="Foto do produto" disabled={f.busy} />
        {f.file ? (
          <figure className="pv-photo">
            <img src={f.file.data} alt={'Sua foto: ' + f.file.name} />
            <label htmlFor="fal-photo" className="pv-photo-swap" aria-disabled={f.busy || undefined}><RefreshCw size={18} aria-hidden="true" />Trocar foto</label>
          </figure>
        ) : (
          <label htmlFor="fal-photo" className="pv-photo-empty">
            <span className="pv-photo-ic" aria-hidden="true"><Camera size={30} /></span>
            <strong>Adicionar foto do produto</strong>
            <span>Use a câmera ou escolha uma foto salva</span>
          </label>
        )}
        <label className="pv-sheet-label" htmlFor="fal-name">Nome do produto <span>(opcional)</span></label>
        <input id="fal-name" className="pv-sheet-field" value={f.name} onChange={f.setName} disabled={f.busy} placeholder="Se ficar vazio, o Kiroo descreve pela foto" autoComplete="off" enterKeyHint="done" />
        {f.styles.length > 1 ? (
          <div role="radiogroup" aria-label="Estilo do vídeo" className="pv-sheet-styles">
            {f.styles.map((s) => (
              <button key={s.id} type="button" role="radio" aria-checked={f.style === s.id} onClick={() => f.setStyle(s.id)} disabled={f.busy}>{s.label}</button>
            ))}
          </div>
        ) : <div className="pv-sheet-static">Estilo <strong>{f.styles[0].label}</strong></div>}
        <p className="pv-sheet-note">{RECEIVE_LINE}</p>
      </div>
      <footer className="pv-sheet-foot">
        {f.error && <div role="alert" className="pv-dock-err"><AlertCircle size={18} aria-hidden="true" />{f.error}</div>}
        <button type="button" className="pv-dock-btn" onClick={f.file ? f.create : () => pickRef.current && pickRef.current.click()} disabled={f.busy || (!!f.file && f.errors.length > 0)}>
          {f.busy ? 'Começando…' : f.file ? f.label : 'Escolher foto'}
        </button>
      </footer>
    </section>
  );
}

export default function FalWindow({ v }) {
  const phone = usePhone();
  if (phone) return <PhoneSheet f={v.fal} />;
  const f = v.fal;
  return (
    <section role="dialog" aria-modal="true" aria-labelledby="fal-h" className="g-panel pop" style={{ position: 'fixed', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', zIndex: 60, width: 'min(520px,calc(100vw - 24px))', maxHeight: 'calc(100vh - 24px)', display: 'flex', flexDirection: 'column', overflow: 'auto' }}>
      <div style={{ padding: '14px 16px', borderBottom: '1px solid #E7E7E4', display: 'flex', alignItems: 'center', gap: 10 }}>
        <h2 id="fal-h" className="fred" style={{ margin: 0, fontSize: 20, fontWeight: 600, flex: 1 }}>Nova produção</h2>
        {f.demo && <span className="g-sim">DEMO: nada é cobrado</span>}
        <CloseButton onClick={f.close} label="Fechar" />
      </div>
      <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
        <DropZone f={f} />
        {f.file && <button className="g-btn g-sm g-quiet" onClick={f.clearFile} disabled={f.busy} style={{ alignSelf: 'flex-start' }}>Trocar foto</button>}
        <label className="g-label" htmlFor="fal-name">Nome do produto <span className="g-muted">(opcional)</span></label>
        <input id="fal-name" className="g-field" value={f.name} onChange={f.setName} disabled={f.busy} placeholder="Se ficar vazio, o Kiroo descreve pela foto" />
        {f.styles.length > 1 ? (
          <div role="radiogroup" aria-label="Estilo do vídeo" style={{ display: 'flex', gap: 8 }}>
            {f.styles.map((s) => (
              <button key={s.id} type="button" role="radio" aria-checked={f.style === s.id} className="g-btn" onClick={() => f.setStyle(s.id)} disabled={f.busy}
                style={{ flex: 1, minHeight: 44, border: f.style === s.id ? '2px solid #0E0E10' : '1px solid #E7E7E4' }}>{s.label}{f.style === s.id ? ' ✓' : ''}</button>
            ))}
          </div>
        ) : <span className="g-muted" style={{ fontSize: 13 }}>Estilo: <strong style={{ color: '#0E0E10' }}>{f.styles[0].label}</strong></span>}
        {f.error && <div role="alert" className="g-card" style={{ ...card, padding: 12, background: '#FFE7C2', border: '2px solid #7A4300', fontSize: 14 }}>{f.error}</div>}
        <button className="g-btn g-lime" onClick={f.create} disabled={f.busy || f.errors.length > 0} style={{ minHeight: 48, fontSize: 16 }}>
          {f.busy ? 'Começando…' : f.label}
        </button>
        <span className="g-muted" style={{ fontSize: 12.5, lineHeight: 1.45 }}>{RECEIVE_LINE}</span>
      </div>
    </section>
  );
}
