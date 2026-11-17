import React from 'react';
import { falFacts, stepBelt } from './falBelt.js';
import { falStations, FAL_STEPS, sceneThumb, platformLogo, splitCaption, titleCount, charsLabel, narrationMeta, doneSubtitle, copyWithFeedback } from './falFlow.js';
import { Avatar } from '../shell/Central.jsx';
import { canShareFile, shareSupported, shareName } from './mobile.js';
import './falDone.css';

// Missão do fluxo foto + estilo: o cartão de status (sempre o estado REAL do servidor) e, quando pronta, a entrega
// (vídeo + 1 foto + título e legenda copiáveis). Fica na própria tela da Missão, abaixo da esteira.

const TONE = { failed: '#FFE1DA', limit: '#FFE7C2', paused: '#FFE7C2', finalizing: '#F2F2EF', partial: '#FFE7C2' };

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
  if (!st || st.kind === 'done') return null;   // concluída: banner + resultado (FalDone), nunca o cartão "Pronto"
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

// ================================================================ "Missão concluída" (desktop e celular: mesma marcação, CSS em falDone.css)
// Banner (check + "Seu vídeo está pronto" + duração e créditos reais) com a esteira compacta; depois o player e o que copiar e colar.
// Só aparece quando a esteira terminou de encher e a produção está entregue (falFlow.isDone).

// Imagem opcional (miniatura de cenário, logo): some em vez de mostrar o ícone de imagem quebrada.
export function FalImg({ src, ...rest }) {
  const [bad, setBad] = React.useState(false);
  React.useEffect(() => { setBad(false); }, [src]);
  if (!src || bad) return null;
  return <img src={src} alt="" onError={() => setBad(true)} {...rest} />;
}

// Chips do cenário (miniatura + nome) e da plataforma (logo + nome). `chips` vem de falMission (rótulos do servidor).
export function FalChips({ chips, className = '' }) {
  if (!chips) return null;
  return (
    <span className={'fd-chips ' + className}>
      {chips.scene && chips.scene.label && <span className="fd-chip"><FalImg src={sceneThumb(chips.scene.id)} className="fd-chip-scene" />{chips.scene.label}</span>}
      {chips.platform && chips.platform.label && <span className="fd-chip"><FalImg src={platformLogo(chips.platform.id)} className="fd-chip-logo" />{chips.platform.label}</span>}
    </span>
  );
}

function Check({ size = 14, sw = 3 }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>;
}

// Ícones só de contorno (sem dependência): decorativos, o botão sempre tem texto ou aria-label.
function Icon({ name }) {
  const p = { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true };
  if (name === 'download') return <svg {...p}><path d="M12 4v11M7 10.5l5 5 5-5M5 20h14" /></svg>;
  if (name === 'share') return <svg {...p}><circle cx="18" cy="5" r="2.5" /><circle cx="6" cy="12" r="2.5" /><circle cx="18" cy="19" r="2.5" /><path d="M8.2 10.8l7.6-4.4M8.2 13.2l7.6 4.4" /></svg>;
  if (name === 'flag') return <svg {...p}><path d="M5 21V4M5 4h11l-2 4 2 4H5" /></svg>;
  return <svg {...p}><rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h10" /></svg>;
}

// Esteira compacta: avatar com check verde, linha de ligação verde-clara e o nome da etapa (no celular, sem nome: CSS).
export function CompactBelt({ stations, team }) {
  const list = (stations || []).filter((s) => s);
  return (
    <ol className="fd-belt" aria-label="Etapas concluídas">
      {list.map((s, i) => {
        const a = (team || []).find((t) => t.id === s.agent);
        const step = FAL_STEPS.find((x) => x.id === s.id);
        const label = step ? step.label : s.title;
        return (
          <React.Fragment key={s.id}>
            {i > 0 && <li className="fd-link" aria-hidden="true" />}
            <li className="fd-step" aria-label={`${label}${a ? ', ' + a.name : ''}, concluída`}>
              <span className="fd-av">{a ? <Avatar look={a.look} size={40} /> : null}<span className="fd-ok"><Check size={10} sw={3.4} /></span></span>
              <span className="fd-step-name" aria-hidden="true">{label}</span>
            </li>
          </React.Fragment>
        );
      })}
    </ol>
  );
}

export function DoneBanner({ g, stations, team, chips, phone }) {
  const sub = doneSubtitle(g);
  return (
    <section className="fd-banner" aria-labelledby="fd-done-h">
      <div className="fd-banner-head">
        <span className="fd-bigcheck"><Check size={22} sw={2.6} /></span>
        <div className="fd-banner-txt">
          <h1 id="fd-done-h">Seu vídeo está pronto</h1>
          {sub && <span>{sub}</span>}
        </div>
      </div>
      {phone && <FalChips chips={chips} />}
      <CompactBelt stations={stations} team={team} />
    </section>
  );
}

// Compartilhar o ARQUIVO (Web Share com files). Sem suporte, o botão nem aparece: o link de /media exige login.
export function useShareFile(url, name, mime) {
  const [file, setFile] = React.useState(null);
  React.useEffect(() => {
    setFile(null);
    const nav = typeof navigator !== 'undefined' ? navigator : null;
    if (!url || !shareSupported(nav) || typeof File === 'undefined') return undefined;
    let on = true;
    fetch(url, { credentials: 'same-origin' }).then((r) => (r.ok ? r.blob() : null)).then((b) => {
      if (!on || !b) return;
      const f = new File([b], name, { type: b.type || mime });
      if (canShareFile(nav, f)) setFile(f);
    }).catch(() => {});
    return () => { on = false; };
  }, [url, name, mime]);
  return file;
}

function CopyBtn({ text, label }) {
  const [ok, setOk] = React.useState(false);
  const timer = React.useRef(null);
  React.useEffect(() => () => clearTimeout(timer.current), []);
  const copy = () => copyWithFeedback(typeof navigator !== 'undefined' ? navigator.clipboard : null, text, setOk,
    (fn, ms) => { clearTimeout(timer.current); timer.current = setTimeout(fn, ms); });
  return (
    <button type="button" className="fd-btn fd-copy" data-ok={ok || undefined} onClick={copy} disabled={!text} aria-live="polite">
      {ok ? <Check size={15} sw={2.4} /> : <Icon name="copy" />}{ok ? 'Copiado' : label}
    </button>
  );
}

function Report({ support }) {
  const href = support && (support.whatsapp || (support.email ? `mailto:${support.email}?subject=${encodeURIComponent('Problema na minha missão')}` : null));
  const ext = !!(support && support.whatsapp);
  return (
    <p className="fd-report"><Icon name="flag" /><span>Algo saiu errado?{' '}
      {href ? <a href={href} {...(ext ? { target: '_blank', rel: 'noopener noreferrer' } : {})}>Reportar problema</a> : <strong>Reportar problema</strong>}
      . Se for erro técnico, os créditos voltam.</span></p>
  );
}

export function FalResult({ m, product }) {
  const g = m.gallery;
  const plat = (m.chips && m.chips.platform && m.chips.platform.label) || 'a plataforma';
  const cap = splitCaption(g.caption);
  const vName = shareName(product, 'video', '.mp4');
  const shareFile = useShareFile(g.video.url, vName, 'video/mp4');
  const share = () => { navigator.share({ files: [shareFile], title: vName }).catch(() => {}); };
  const credits = m.variantCredits && m.variantCredits !== '0' ? m.variantCredits : null;
  const nar = g.narration;
  const approved = m.P.status === 'completed';
  return (
    <div className="fd-grid">
      <div className="fd-left">
        {approved && <span className="fd-approved" role="status"><Check size={15} sw={2.6} />Aprovado</span>}
        <div className="fd-player">
          <video src={g.video.url} poster={g.cover || undefined} controls playsInline preload="metadata" aria-label={'Vídeo final' + (product ? ': ' + product : '')} />
          <span className="fd-badge">15 s · 9:16</span>
        </div>
        {shareFile && <div className="fd-acts"><button type="button" className="fd-btn fd-secondary" onClick={share}><Icon name="share" />Compartilhar</button></div>}
      </div>
      <div className="fd-right">
        <div className="fd-rhead"><h2>Pronto pra postar no {plat}</h2><span>Copie e cole na hora de publicar</span></div>
        {g.title && (
          <section className="fd-card" aria-labelledby="fd-t-titulo">
            <h3 id="fd-t-titulo" className="fd-label">Título</h3>
            <p className="fd-title">{g.title}</p>
            <div className="fd-row"><span className="fd-count">{charsLabel(titleCount(g.title))}</span><CopyBtn text={g.title} label="Copiar título" /></div>
          </section>
        )}
        {g.caption && (
          <section className="fd-card" aria-labelledby="fd-t-legenda">
            <h3 id="fd-t-legenda" className="fd-label">Legenda</h3>
            <p className="fd-caption">{cap.body}</p>
            {cap.tags.length > 0 && <ul className="fd-tags" aria-label="Hashtags">{cap.tags.map((t) => <li key={t}>{t}</li>)}</ul>}
            <div className="fd-row"><span className="fd-count">{charsLabel(cap.count, cap.tags.length > 0)}</span><CopyBtn text={cap.full} label="Copiar legenda" /></div>
            {g.captionFile && <a className="fd-link-sm" href={g.captionFile.download} download>Baixar legenda com aviso de publicidade</a>}
          </section>
        )}
        {g.textMissing && <div className="fd-card fd-note" role="note">O vídeo veio sem título e legenda. Escreva os seus antes de publicar.</div>}
        <div className={'fd-pair' + (nar && g.image && g.image.url ? ' fd-pair-2' : '')}>
          {nar && (
            <section className="fd-card" aria-labelledby="fd-t-nar">
              <div className="fd-rowtop"><h3 id="fd-t-nar" className="fd-label">Narração</h3><span className="fd-count">{narrationMeta(nar)}</span></div>
              <p className="fd-nar">“{nar.text}”</p>
            </section>
          )}
          {g.image && g.image.url && (
            <section className="fd-card fd-photo" aria-labelledby="fd-t-foto">
              <img src={g.image.url} alt="Foto do produto gerada" />
              <div>
                <h3 id="fd-t-foto" className="fd-label">Foto do produto</h3>
                <span className="fd-count">9:16, boa para capa ou anúncio</span>
                <a className="fd-btn" href={g.image.download} download><Icon name="download" />Baixar foto</a>
              </div>
            </section>
          )}
        </div>
        <section className="fd-variants" aria-labelledby="fd-t-var">
          <div><h3 id="fd-t-var">Quer testar outra versão?</h3><span>Mesma foto e produto.{credits ? ` Cada vídeo usa ${credits} créditos.` : ''}</span></div>
          <div className="fd-variant-btns">
            <button type="button" className="fd-btn" onClick={() => m.reuse('platform')} disabled={m.busy}>Outra plataforma</button>
            <button type="button" className="fd-btn" onClick={() => m.reuse('scene')} disabled={m.busy}>Outro cenário</button>
          </div>
        </section>
        {g.partial && <div className="fd-note fd-card" role="note">Entrega parcial: a foto não ficou pronta.</div>}
        <p className="fd-pubnote">Ao publicar no {plat}, marque o conteúdo como publicidade. A publicação é manual.</p>
        <Report support={m.support} />
      </div>
    </div>
  );
}

// "Seus arquivos ficam guardados até 15/01/2027." (60 dias; o servidor manda a data prevista em production.media_expires_at)
export function mediaKeepNote(P) {
  if (!P || P.media_purged || !P.media_expires_at) return '';
  const d = new Date(P.media_expires_at);
  if (Number.isNaN(d.getTime())) return '';
  return `Guardamos seus arquivos até ${d.toLocaleDateString('pt-BR')}. Baixe o que quiser manter.`;
}

// Barra de ação fixa no fim da área de conteúdo. Aguardando aprovação: "Aprovar vídeo" é a ação principal (o servidor aceita
// a aprovação só nesse estado) e "Baixar vídeo" fica ao lado. Aprovado: "Baixar vídeo" é a principal. "Pedir ajuste" não
// existe no motor fal (não há ajuste de vídeo pronto), então não é oferecido.
export function ActionBar({ m }) {
  const href = m.gallery.video.download;
  const waiting = m.P.status === 'awaiting_final_review';
  const keep = mediaKeepNote(m.P);   // retenção de 60 dias: data prevista em que os arquivos são apagados
  const download = (primary) => <a className={'fd-btn ' + (primary ? 'fd-primary' : 'fd-secondary')} href={href} download><Icon name="download" />Baixar vídeo</a>;
  return (
    <div className="fd-bar" role="region" aria-label="Ações do vídeo">
      {waiting ? (<>
        <p className="fd-bar-txt"><strong>Seu vídeo está pronto para aprovar.</strong><span>Aprove para concluir; você pode baixar antes.</span>{keep && <span>{keep}</span>}</p>
        <div className="fd-bar-btns">
          {download(false)}
          <button type="button" className="fd-btn fd-approve" onClick={m.approve} disabled={m.busy}><Check size={18} sw={2.6} />Aprovar vídeo</button>
        </div>
      </>) : (
        <>{keep && <p className="fd-bar-txt"><span>{keep}</span></p>}<div className="fd-bar-btns">{download(true)}</div></>
      )}
    </div>
  );
}

export function FalDone({ m, team, product, stations, phone, footer }) {
  return (
    <div className="fd" data-testid="fal-done">
      <DoneBanner g={m.gallery} stations={stations} team={team} chips={m.chips} phone={phone} />
      <FalResult m={m} product={product} />
      {footer}
      <ActionBar m={m} />
    </div>
  );
}
