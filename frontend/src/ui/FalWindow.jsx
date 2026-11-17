import React from 'react';
import { AlertCircle, Camera, Check, Lock, X } from 'lucide-react';
import { NAME_MAX, RECEIVE_SHORT, lockText, platformLogo, sceneImage, sceneThumb } from './falFlow.js';
import { usePhone } from '../hooks/use-phone.js';
import { SEE_PACKS } from './welcome.js';
import './falModal.css';

// "Nova produção" no fluxo foto + cenário + plataforma: SÓ o envio. Desktop (> 640 px): modal horizontal (prévia à esquerda,
// escolhas à direita, rodapé com o botão). Celular (<= 640 px): bottom sheet. Clicar em "Criar vídeo" = consentimento: o App faz
// create → confirm → run; se algo falhar, esta janela continua aberta com a mensagem do servidor. O front manda SÓ os ids
// `scene` e `platform`. A prévia é ilustrativa (composição em CSS, nenhuma geração). Nenhuma tela cita fornecedor, modelo ou fila.

// Imagem que pode não existir ainda (assets opcionais): some em vez de mostrar o ícone de imagem quebrada.
function Img({ src, className, ...rest }) {
  const [bad, setBad] = React.useState(false);
  React.useEffect(() => { setBad(false); }, [src]);
  if (bad) return null;
  return <img src={src} className={className} alt="" onError={() => setBad(true)} {...rest} />;
}

function Preview({ f, sceneName, phone, pickRef }) {
  const [over, setOver] = React.useState(false);
  const drop = (e) => { e.preventDefault(); setOver(false); const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]; if (file && !f.busy) f.pickFile(file); };
  return (
    <div className="fm-prev" onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={drop}
      style={over ? { outline: '2px dashed #5b5bd6', outlineOffset: -4 } : undefined}>
      <Img src={sceneImage(f.scene)} className="fm-prev-bg" />
      {f.file ? (
        <>
          <span className="fm-prev-shadow" aria-hidden="true" />
          <img className="fm-prev-prod" src={f.file.data} alt={'Sua foto: ' + f.file.name} />
        </>
      ) : (
        <button type="button" className="fm-prev-empty" onClick={() => pickRef.current && pickRef.current.click()} disabled={f.busy}>
          <Camera size={28} aria-hidden="true" />
          <strong>Adicionar foto do produto</strong>
          <small>{phone ? 'Use a câmera ou escolha uma foto salva' : 'Solte aqui ou clique · JPG, PNG ou WEBP'}</small>
        </button>
      )}
      <span className="fm-prev-badge">Prévia · {sceneName}</span>
      {phone && f.file && (
        <button type="button" className="fm-prev-swap" onClick={() => pickRef.current && pickRef.current.click()} disabled={f.busy}>
          <Camera size={18} aria-hidden="true" />Trocar foto
        </button>
      )}
    </div>
  );
}

function SceneCard({ s, on, f }) {
  const locked = !!s.locked;
  const lt = lockText(s);
  return (
    <button type="button" className="fm-card" aria-pressed={on} aria-disabled={locked || undefined} disabled={f.busy}
      onClick={() => { if (!locked) f.setScene(s.id); }} title={lt || undefined}>
      <span className="fm-scene-thumb">
        <Img src={sceneThumb(s.id)} />
        {on && <span className="fm-check" aria-hidden="true"><Check size={14} strokeWidth={3} /></span>}
        {locked && <span className="fm-lock"><Lock size={16} aria-hidden="true" />{lt}</span>}
      </span>
      <span className="fm-scene-body">
        <span className="fm-scene-name">{s.label}</span>
        <span className="fm-scene-sub">{s.sub}</span>
      </span>
    </button>
  );
}

function PlatformCard({ p, on, f, list }) {
  return (
    <button type="button" className="fm-card fm-plat" aria-pressed={on} disabled={f.busy} onClick={() => f.setPlatform(p.id)}>
      <span className="fm-logo"><Img src={platformLogo(p.id)} /></span>
      {list ? (
        <>
          <span className="fm-plat-name">{p.label}</span>
          <span className="fm-plat-sub">{p.sub}</span>
        </>
      ) : (
        <span className="fm-plat-txt"><span className="fm-plat-name">{p.label}</span><span className="fm-plat-sub">{p.sub}</span></span>
      )}
    </button>
  );
}

function NameField({ f, id }) {
  return (
    <div>
      <label className="fm-label" htmlFor={id}>Nome do produto <span>(opcional)</span></label>
      <input id={id} className="fm-field" value={f.name} onChange={f.setName} disabled={f.busy} maxLength={NAME_MAX} autoComplete="off" enterKeyHint="done"
        placeholder="Se ficar vazio, o Kiroo descreve pela foto" />
    </div>
  );
}

function Problems({ f }) {
  return (
    <>
      {f.error && <div role="alert" className="fm-err"><AlertCircle size={18} aria-hidden="true" style={{ flex: 'none', marginTop: 1 }} />{f.error}</div>}
      {(f.noFunds || f.missing > 0) && (f.quickBuy
        ? <button type="button" className="fm-btn2" onClick={f.buyNow} disabled={f.buying} aria-busy={f.buying || undefined}>{f.buying ? 'Abrindo o pagamento…' : f.quickBuy.label}</button>
        : f.noFunds && <button type="button" className="fm-btn2" onClick={f.openBuy}>{SEE_PACKS}</button>)}
    </>
  );
}

function useEscape(f) {
  React.useEffect(() => {
    const on = (e) => { if (e.key === 'Escape') f.close(); };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  });
}

// "Outra plataforma" / "Outro cenário" (tela Missão concluída): rola e foca a seção pedida; o contorno accent vem de .fm-hl.
function useReuseFocus(f, platRef, sceneRef) {
  const kind = f.reuse ? f.reuse.kind : null;
  React.useEffect(() => {
    const el = kind === 'platform' ? platRef.current : kind === 'scene' ? sceneRef.current : null;
    if (!el) return;
    if (typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'center' });
    const target = el.querySelector("button[aria-pressed='true']:not(:disabled)") || el.querySelector('button:not(:disabled)');
    if (target) target.focus({ preventScroll: true });
  }, [kind]);   // eslint-disable-line react-hooks/exhaustive-deps
}
const hl = (f, kind) => (f.reuse && f.reuse.kind === kind ? 'fm-hl' : undefined);
const ctaLabel = (f, text) => (f.reuseBlocked ? f.reuseLabel : text);

function PhoneSheet({ f }) {
  const pickRef = React.useRef(null);
  const platRef = React.useRef(null), sceneRef = React.useRef(null);
  useReuseFocus(f, platRef, sceneRef);
  useEscape(f);
  const create = f.file ? f.create : () => pickRef.current && pickRef.current.click();
  return (
    <div className="fm fm-sheet-wrap" onMouseDown={(e) => { if (e.target === e.currentTarget) f.close(); }}>
      <section role="dialog" aria-modal="true" aria-labelledby="fal-h" className="fm-sheet">
        <header className="fm-sheet-head">
          <h2 id="fal-h">Nova produção</h2>
          {f.demo && <span className="fm-demo">DEMO</span>}
          <button type="button" className="fm-x" onClick={f.close} aria-label="Fechar" disabled={f.busy}><X size={22} aria-hidden="true" /></button>
        </header>
        <div className="fm-sheet-body">
          <input ref={pickRef} type="file" accept="image/*" onChange={f.pick} className="fm-file" aria-label="Foto do produto" disabled={f.busy} />
          <Preview f={f} sceneName={f.sceneName} phone pickRef={pickRef} />
          <NameField f={f} id="fal-name" />
          <div ref={sceneRef} className={hl(f, 'scene')}>
            <div className="fm-sec"><span className="fm-label" id="fal-scenes-l">Cenário</span><span className="fm-hint">O produto fica igual, só o ambiente muda</span></div>
            <div className="fm-carousel" role="group" aria-labelledby="fal-scenes-l">
              {f.scenes.map((s) => <SceneCard key={s.id} s={s} on={f.scene === s.id} f={f} />)}
            </div>
          </div>
          <div ref={platRef} className={hl(f, 'platform')}>
            <div className="fm-sec"><span className="fm-label" id="fal-plats-l">Onde vai postar</span></div>
            <div className="fm-plat-list" role="group" aria-labelledby="fal-plats-l">
              {f.platforms.map((p) => <PlatformCard key={p.id} p={p} on={f.platform === p.id} f={f} list />)}
            </div>
          </div>
        </div>
        <footer className="fm-sheet-foot">
          <Problems f={f} />
          <button type="button" className="fm-primary" onClick={create} disabled={f.busy || f.reuseBlocked || (!!f.file && f.errors.length > 0)}>
            {f.busy ? 'Começando…' : f.reuseBlocked ? f.reuseLabel : f.file ? f.label : 'Escolher foto'}
          </button>
          {f.costLine && <p className="fm-cost">{f.costLine}</p>}
          <p>{RECEIVE_SHORT}</p>
        </footer>
      </section>
    </div>
  );
}

export default function FalWindow({ v }) {
  const phone = usePhone();
  const f = v.fal;
  const pickRef = React.useRef(null);
  const platRef = React.useRef(null), sceneRef = React.useRef(null);
  useReuseFocus(f, platRef, sceneRef);
  useEscape(f);
  if (phone) return <PhoneSheet f={f} />;
  const plat = (f.platforms.find((p) => p.id === f.platform) || {}).label || 'a plataforma escolhida';
  return (
    <div className="fm fm-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) f.close(); }}>
      <section role="dialog" aria-modal="true" aria-labelledby="fal-h" className="fm-modal">
        <header className="fm-head">
          <h2 id="fal-h">Nova produção</h2>
          {f.demo && <span className="fm-demo">DEMO: nada é cobrado</span>}
          <button type="button" className="fm-x" onClick={f.close} aria-label="Fechar" disabled={f.busy}><X size={22} aria-hidden="true" /></button>
        </header>
        <div className="fm-body">
          <div className="fm-left">
            <input ref={pickRef} type="file" accept="image/jpeg,image/png,image/webp" onChange={f.pick} className="fm-file" aria-label="Foto do produto" disabled={f.busy} />
            <Preview f={f} sceneName={f.sceneName} pickRef={pickRef} />
            <p className="fm-left-note">Exemplo do ambiente com o seu produto</p>
            <button type="button" className="fm-btn2" onClick={() => pickRef.current && pickRef.current.click()} disabled={f.busy}>
              <Camera size={18} aria-hidden="true" />{f.file ? 'Trocar foto' : 'Escolher foto'}
            </button>
          </div>
          <div className="fm-right">
            <NameField f={f} id="fal-name" />
            <div ref={sceneRef} className={hl(f, 'scene')}>
              <div className="fm-sec"><span className="fm-label" id="fal-scenes-l">Cenário</span><span className="fm-hint">O produto fica igual, só o ambiente muda</span></div>
              <div className="fm-scenes" role="group" aria-labelledby="fal-scenes-l">
                {f.scenes.map((s) => <SceneCard key={s.id} s={s} on={f.scene === s.id} f={f} />)}
              </div>
            </div>
            <div ref={platRef} className={hl(f, 'platform')}>
              <div className="fm-sec"><span className="fm-label" id="fal-plats-l">Onde vai postar</span><span className="fm-hint">Ajusta roteiro, título e legenda</span></div>
              <div className="fm-plats" role="group" aria-labelledby="fal-plats-l">
                {f.platforms.map((p) => <PlatformCard key={p.id} p={p} on={f.platform === p.id} f={f} />)}
              </div>
            </div>
            <Problems f={f} />
          </div>
        </div>
        <footer className="fm-foot">
          <p className="fm-foot-txt">Você recebe vídeo de ~15 s com narração, 1 foto, título e legenda para <strong>{plat}</strong>. Se falhar por erro técnico, não é cobrado.</p>
          <div className="fm-foot-act">
            {f.costLine && <span className="fm-cost">{f.costLine}</span>}
            <button type="button" className="fm-primary" onClick={f.create} disabled={f.busy || f.reuseBlocked || f.errors.length > 0}>{f.busy ? 'Começando…' : ctaLabel(f, f.label)}</button>
          </div>
        </footer>
      </section>
    </div>
  );
}
