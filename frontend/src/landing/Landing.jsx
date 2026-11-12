import React from 'react';
import { ArrowRight, Pause, Play, Plus, Volume2, VolumeX } from 'lucide-react';
import wordmark from '../assets/brand/wordmark-preto-laranja.svg';
import wordmarkOnDark from '../assets/brand/wordmark-branco-laranja.svg';
import { ART } from './art.js';
import { SHOWCASE, HAS_VIDEO } from './showcase.js';
import { ROOMS, IMG, fmtTC, fmtFormat } from './stage.js';
import { AgentHead } from '../shell/AgentHead.jsx';
import Stage, { Portrait } from './Stage.jsx';
import { go, useMedia, useInView, useScrollVar } from './util.js';
import './landing.css';

// Home pública (antes do login). Direção de arte: "bastidor em pixel, resultado em filme".
// Uma câmera contínua (Stage.jsx) leva da abertura aos três atos; o resto da página usa a mesma linguagem
// (enquadramentos da sede, claquete, REC) com coreografias próprias por seção. Rolagem nativa; movimento reduzido respeitado.
// Nada de depoimentos, clientes, métricas ou preços inventados; formato e duração de vídeo só do próprio arquivo (frontend/CLAUDE.md).

/* ------------------------------------------------------------------ recorte de uma sala da sede (pixel art) */
function Room({ id, className = '' }) {
  const [x, y, w, h] = ROOMS[id];
  return (
    <span className={'lp-room ' + className} style={{ aspectRatio: `${w} / ${h}` }} aria-hidden="true">
      {ART.sede && (
        <img src={ART.sede} alt="" draggable="false"
          style={{ width: `${(IMG.w / w) * 100}%`, left: `${(-x / w) * 100}%`, top: `${(-y / h) * 100}%` }} />
      )}
    </span>
  );
}

/* ------------------------------------------------------------------ vídeo de exemplo (só quando existe arquivo)
   Carrega perto da tela (só metadados), começa sem som, toca sozinho só sem redução de movimento e pausa fora da tela.
   Formato e duração vêm do arquivo. */
function ShowcaseMedia({ item, autoPlay = false, onMeta }) {
  const ref = React.useRef(null);
  const reduced = useMedia('(prefers-reduced-motion: reduce)');
  const [playing, setPlaying] = React.useState(false);
  const [muted, setMuted] = React.useState(true);
  const [meta, setMeta] = React.useState(null);
  const [t, setT] = React.useState(0);
  const userPaused = React.useRef(false);
  const load = (el) => { if (item.video && !el.getAttribute('src')) { el.preload = 'metadata'; el.src = item.video; } };
  React.useEffect(() => {
    const el = ref.current;
    if (!el || !item.video) return undefined;
    if (!('IntersectionObserver' in window)) { load(el); return undefined; }
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) load(el);
      if (e.intersectionRatio >= 0.5) {
        if (autoPlay && !reduced && !userPaused.current) el.play().catch(() => {});
      } else if (!el.paused) el.pause();
    }, { threshold: [0, 0.5], rootMargin: '200px 0px' });
    io.observe(el);
    return () => io.disconnect();
  }, [item.video, autoPlay, reduced]);
  const toggle = () => {
    const el = ref.current;
    if (!el) return;
    if (el.paused) { userPaused.current = false; load(el); el.play().catch(() => {}); } else { userPaused.current = true; el.pause(); }
  };
  const gotMeta = (e) => { const v = e.currentTarget, m = { w: v.videoWidth, h: v.videoHeight, d: v.duration }; setMeta(m); if (onMeta) onMeta(m); };
  return (
    <div className="lp-media" style={meta && meta.w ? { aspectRatio: `${meta.w} / ${meta.h}` } : undefined}>
      <video ref={ref} poster={item.poster} muted={muted} playsInline loop preload="none"
        onLoadedMetadata={gotMeta} onTimeUpdate={(e) => setT(e.currentTarget.currentTime)}
        onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} aria-label={`Vídeo de exemplo: ${item.label}`} />
      {item.demo && <span className="lp-media-tag">Demonstrativo</span>}
      {meta && <span className="lp-media-tc" aria-hidden="true">{fmtTC(t)} / {fmtTC(meta.d)}</span>}
      <div className="lp-media-ctl">
        <button type="button" onClick={toggle} aria-label={playing ? 'Pausar vídeo' : 'Reproduzir vídeo'}>
          {playing ? <Pause size={16} aria-hidden="true" /> : <Play size={16} aria-hidden="true" />}
        </button>
        <button type="button" onClick={() => setMuted((m) => !m)} aria-label={muted ? 'Ativar som' : 'Desativar som'} aria-pressed={!muted}>
          {muted ? <VolumeX size={16} aria-hidden="true" /> : <Volume2 size={16} aria-hidden="true" />}
        </button>
      </div>
    </div>
  );
}

function ReelItem({ item, i }) {
  const [meta, setMeta] = React.useState(null);
  const f = meta && fmtFormat(meta.w, meta.h);
  return (
    <figure className="lp-reel-item">
      <ShowcaseMedia item={item} autoPlay={i === 0} onMeta={setMeta} />
      <figcaption><strong>{item.label}</strong>
        <span className="lp-mono">{[f, meta && Number.isFinite(meta.d) ? fmtTC(meta.d) : null].filter(Boolean).join(' · ') || 'Take ' + (i + 1)}</span>
      </figcaption>
    </figure>
  );
}

/* ------------------------------------------------------------------ hoje no estúdio */
const TODAY = [
  { id: 'video', t: 'Vídeos de produto', room: 'beto', tag: 'Disponível',
    d: 'Das fotos do seu produto a um vídeo vertical montado, em três cenas e sem fala.',
    chips: ['Produto em destaque', 'Somente mãos', 'Com apresentadora · experimental'] },
  { id: 'direcao', t: 'Direção criativa', room: 'theo', tag: 'Disponível',
    d: 'O Theo propõe ambiente, tom e roteiro. Você aprova ou ajusta antes de qualquer gasto.' },
  { id: 'treino', t: 'Equipe treinável', room: 'nina', tag: 'Disponível',
    d: 'Ensine orientações e referências da sua marca a cada agente. Cada versão é testada antes de entrar em uso.' },
  { id: 'trilhas', t: 'Edição e trilhas', room: 'lia', tag: 'Disponível',
    d: 'Ritmo Dinâmico, Suave ou Limpo; trilha da biblioteca do estúdio ou sua, com autorização. Sempre sai também sem música.' },
  { id: 'sede', t: 'Escritório ao vivo', room: 'comum', tag: 'Disponível',
    d: 'Veja quem está trabalhando, converse com os agentes e seja chamado quando a decisão for sua.' },
];

function Today() {
  const [open, setOpen] = React.useState(0);
  const [ref, inView] = useInView();
  return (
    <section id="hoje" className={'lp-today lp-pad' + (inView ? ' is-in' : '')} ref={ref} aria-labelledby="lp-td-t" tabIndex={-1}>
      <div className="lp-today-head">
        <p className="lp-kick"><span className="lp-clap" aria-hidden="true" />Hoje no estúdio</p>
        <h2 id="lp-td-t" className="lp-h2">Um estúdio inteiro, <span className="lp-soft">não uma ferramenta.</span></h2>
        <p className="lp-lead">O primeiro formato em produção é o vídeo de produto. Direção, equipe e escritório já trabalham juntos em cada um.</p>
      </div>
      <ul className="lp-rows">
        {TODAY.map((r, i) => {
          const on = open === i;
          return (
            <li key={r.id} className={'lp-row-i' + (on ? ' is-open' : '')} style={{ '--i': i }}>
              <button type="button" className="lp-row-b" aria-expanded={on} aria-controls={'lp-row-' + r.id} onClick={() => setOpen(on ? -1 : i)}>
                <span className="lp-row-n">{String(i + 1).padStart(2, '0')}</span>
                <span className="lp-row-t">{r.t}</span>
                <span className="lp-row-tag">{r.tag}</span>
                <Plus className="lp-row-ic" size={22} aria-hidden="true" />
              </button>
              <div className="lp-row-p" id={'lp-row-' + r.id} role="region" aria-label={r.t} inert={on ? undefined : ''}>
                <div className="lp-row-pw">
                  <div className="lp-row-pi">
                    <p>{r.d}</p>
                    {r.chips && <ul className="lp-chips">{r.chips.map((c) => <li key={c}>{c}</li>)}</ul>}
                  </div>
                  <Room id={r.room} className="lp-row-room" />
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/* ------------------------------------------------------------------ controle (Piloto) */
const PILOT = [
  { id: 'manual', label: 'Manual', line: 'Você aprova cada passo.' },
  { id: 'assistido', label: 'Assistido', line: 'Você decide a direção e as dúvidas.', tag: 'padrão' },
  { id: 'automatico', label: 'Automático', line: 'A equipe vai até o vídeo montado.' },
];
// quem decide em cada ponto, por modo do Piloto (frontend/CLAUDE.md → Piloto)
const DECISIONS = [
  ['Direção criativa', ['Você', 'Você', 'Equipe sugere']],
  ['Etapas pagas', ['Você', 'Equipe, no limite', 'Equipe, no limite']],
  ['Cena reprovada', ['Avisa você', 'Equipe refaz', 'Equipe refaz']],
  ['Cena com dúvida', ['Você', 'Você', 'Equipe aprova']],
  ['Revisão final', ['Você', 'Você', 'Você']],
];
const STATEMENT = 'A equipe produz. As decisões importantes continuam suas.'.split(' ');

function Control() {
  const [m, setM] = React.useState(1);
  const words = useScrollVar(0.85, 0.3);
  return (
    <section id="controle" className="lp-ctrl lp-pad" aria-labelledby="lp-ct-t" tabIndex={-1}>
      <div className="lp-ctrl-l">
        <p className="lp-kick"><span className="lp-clap" aria-hidden="true" />Controle criativo</p>
        <h2 id="lp-ct-t" className="lp-h2 lp-words" ref={words} style={{ '--n': STATEMENT.length }}>
          {STATEMENT.map((w, i) => <React.Fragment key={i}><span style={{ '--i': i }}>{w} </span>{w.endsWith('.') && i < STATEMENT.length - 1 && <br />}</React.Fragment>)}
        </h2>
        <p className="lp-lead">Refazer uma cena não refaz as outras. Trocar o ritmo da edição remonta sem gerar de novo.</p>
      </div>
      <div className="lp-pilot">
        <div className="lp-pilot-top">
          <p className="lp-mono">Piloto</p>
          <p className="lp-small">Quem decide cada ponto. Troque quando quiser.</p>
        </div>
        <fieldset className="lp-switch-f">
          <legend className="lp-sr">Modo do Piloto</legend>
          <div className="lp-switch" style={{ '--i': m }}>
            <span className="lp-switch-thumb" aria-hidden="true" />
            {PILOT.map((p, i) => (
              <label key={p.id} className={'lp-switch-opt' + (m === i ? ' is-on' : '')}>
                <input type="radio" name="lp-pilot" value={p.id} checked={m === i} onChange={() => setM(i)} />
                <span className="lp-switch-tick" aria-hidden="true" />
                <span className="lp-switch-l">{p.label}</span>
              </label>
            ))}
          </div>
          <p className="lp-switch-read" aria-live="polite">
            <strong>{PILOT[m].label}{PILOT[m].tag ? ` (${PILOT[m].tag})` : ''}</strong><span>{PILOT[m].line}</span>
          </p>
        </fieldset>
        <ol className="lp-line" aria-label={`Quem decide no modo ${PILOT[m].label}`}>
          {DECISIONS.map(([d, who], i) => {
            const you = who[m].startsWith('Você') || who[m].startsWith('Avisa');
            return (
              <li key={d} className={you ? 'is-you' : ''} style={{ '--i': i }}>
                <span className="lp-line-dot" aria-hidden="true"><AgentHead active={you} size={14} /></span>
                <span className="lp-line-d">{d}</span>
                <span className="lp-line-who" key={m + '-' + i}>{who[m]}</span>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ créditos */
const LEDGER = [
  ['Estimativa', 'Você vê o custo e libera.'],
  ['Reserva', 'O crédito fica separado.'],
  ['Débito ou estorno', 'Falhou, o crédito volta.'],
];

function Credits({ start, signupOpen }) {
  const [ref, inView] = useInView();
  return (
    <section id="planos" className={'lp-cred lp-pad' + (inView ? ' is-in' : '')} ref={ref} aria-labelledby="lp-pl-t" tabIndex={-1}>
      <div className="lp-cred-head">
        <p className="lp-kick"><span className="lp-clap" aria-hidden="true" />Créditos</p>
        <h2 id="lp-pl-t" className="lp-h2">O custo aparece antes.</h2>
      </div>
      <figure className="lp-ledger">
        <figcaption className="lp-mono">Como cada etapa paga funciona</figcaption>
        <ol>
          {LEDGER.map(([t, d], i) => (
            <li key={t} style={{ '--i': i }}>
              <span className="lp-ledger-n" aria-hidden="true">{i + 1}</span>
              <strong>{t}</strong><span>{d}</span>
            </li>
          ))}
        </ol>
      </figure>
      <div className="lp-cred-cols">
        <div>
          <p className="lp-mono">Sem créditos</p>
          <ul className="lp-chips is-quiet"><li>Todo o DEMO</li><li>Montar e remontar a edição</li><li>Baixar, com e sem música</li></ul>
        </div>
        <div>
          <p className="lp-mono">Usa créditos</p>
          <ul className="lp-chips"><li>Gerar as cenas</li><li>Animar em vídeo</li><li>Refazer uma cena</li></ul>
        </div>
        <div className="lp-cred-plan">
          <p className="lp-mono">Planos · em breve</p>
          <p>Por enquanto, os créditos são liberados pelo administrador do estúdio. O DEMO mostra tudo sem custo.</p>
          <button type="button" className="lp-btn is-line" onClick={start}><span>{signupOpen ? 'Começar no DEMO' : 'Entrar no estúdio'}</span><ArrowRight size={16} aria-hidden="true" /></button>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ dúvidas */
const FAQ = [
  ['Do que eu preciso para começar?', 'Fotos do produto feitas por você (de preferência de alguns ângulos) e o nome ou a ficha. As fotos são a referência de tudo o que a equipe cria. A importação automática pelo link do anúncio ainda não existe.'],
  ['Que vídeos o Kiroo faz hoje?', 'Vídeos verticais de produto, montados a partir de três cenas, sem fala. A duração sai do roteiro de cada produção. Você escolhe entre produto em destaque, somente mãos ou com apresentadora (experimental), além do ambiente, do tom e do ritmo da edição.'],
  ['O vídeo vai ser fiel ao meu produto?', 'A equipe trabalha a partir das suas fotos e da ficha, e o revisor confere cada cena contra elas. Mesmo assim, a conferência automática pode ser inconclusiva: quando isso acontece, a cena espera você. Não prometemos 100% de fidelidade; prometemos dizer quando há dúvida.'],
  ['Posso pedir ajustes?', 'Sim. Você ajusta a direção antes de gerar, refaz só a cena que não ficou boa (há um limite de tentativas por cena), troca o estilo da edição e a trilha. Trocar a edição remonta o vídeo sem gerar as cenas de novo.'],
  ['Como funciona a cobrança?', 'Gerações reais com IA usam créditos. Antes de começar você vê "Seu próximo vídeo": o custo total em créditos, os ajustes incluídos e o seu saldo, e só gastamos depois que você confirma. Nenhum custo adicional é aplicado sem a sua autorização, e uma geração que falha por erro técnico não é cobrada. A compra de planos e pacotes pelo site ainda não está aberta.'],
  ['O que é o modo DEMO?', 'Contas novas começam no DEMO: o fluxo inteiro funciona com imagens e vídeos de exemplo, sem gastar créditos. Serve para conhecer o estúdio. Nada do DEMO é uma geração real com IA.'],
  ['A legenda inventa características?', 'Não. A legenda sugerida usa só o que está na ficha e o que você confirmou.'],
  ['O Kiroo publica o vídeo por mim?', 'Não. Você baixa o arquivo e publica onde quiser. A versão sem música existe para você escolher um som em alta direto no editor da plataforma.'],
  ['Preciso andar pelo escritório para usar?', 'Não. O escritório é para ver a equipe trabalhando e conversar com ela quando quiser. Aprovar, liberar e baixar ficam a um clique na Central.'],
];

/* ------------------------------------------------------------------ encerramento: a sede à noite, lanterna no cursor */
function Finale({ start, startLabel, onEnter, NAV }) {
  const [ref, inView] = useInView({ rootMargin: '0px 0px -30% 0px' });
  const box = React.useRef(null);
  const raf = React.useRef(0);
  const move = (e) => {
    const el = box.current;
    if (!el || e.pointerType === 'touch') return;
    const r = el.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    if (raf.current) cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(() => { el.style.setProperty('--mx', x + 'px'); el.style.setProperty('--my', y + 'px'); el.classList.add('is-aim'); });
  };
  const leave = () => { if (box.current) box.current.classList.remove('is-aim'); };
  return (
    <footer className={'lp-end' + (inView ? ' is-in' : '')} ref={ref}>
      <div className="lp-end-stage" ref={box} onPointerMove={move} onPointerLeave={leave}>
        <div className="lp-end-night" aria-hidden="true">{ART.sede && <img src={ART.sede} alt="" draggable="false" />}</div>
        <div className="lp-end-light" aria-hidden="true">{ART.sede && <img src={ART.sede} alt="" draggable="false" />}</div>
        <div className="lp-end-shade" aria-hidden="true" />
        <div className="lp-end-in lp-pad">
          <div className="lp-board" aria-hidden="true">
            <span className="lp-board-arm" />
            <span className="lp-board-body"><span>Cena final</span><span>Take 01</span><span>Kiroo</span></span>
          </div>
          <h2 className="lp-end-t">O que vamos<br />criar hoje?</h2>
          <p className="lp-end-p">Mande as fotos de um produto e acompanhe a equipe montar o primeiro vídeo.</p>
          <button type="button" className="lp-btn is-orange is-lg" onClick={start}><span>{startLabel}</span><ArrowRight size={18} aria-hidden="true" /></button>
        </div>
      </div>
      <div className="lp-foot lp-pad">
        <img className="lp-foot-brand" src={wordmarkOnDark} alt="Kiroo" height="24" />
        <nav aria-label="Rodapé" className="lp-foot-links">
          {NAV.map(([id, l]) => <a key={id} href={'#' + id} onClick={go(id)}>{l}</a>)}
          <a href="#duvidas" onClick={go('duvidas')}>Dúvidas</a>
          <button type="button" onClick={() => onEnter('login')}>Entrar</button>
        </nav>
        <p className="lp-foot-legal">
          Arte da sede: Modern Interiors e Modern Office por LimeZu (<a href="https://limezu.itch.io/moderninteriors" target="_blank" rel="noopener noreferrer">limezu.itch.io</a>).{' '}
          Shopee é marca da Sea Limited; o Kiroo não é afiliado à Shopee.
        </p>
      </div>
    </footer>
  );
}

/* ------------------------------------------------------------------ página */
export default function Landing({ onEnter, signupOpen }) {
  const start = () => onEnter(signupOpen ? 'signup' : 'login');
  const startLabel = signupOpen ? 'Começar a criar' : 'Entrar no estúdio';
  React.useEffect(() => { document.title = 'Kiroo — Estúdio criativo de vídeos com IA'; return () => { document.title = 'Kiroo'; }; }, []);
  const NAV = [['bastidores', 'Bastidores'], ['hoje', 'Hoje no estúdio'], ['controle', 'Controle'], ['planos', 'Créditos']];
  const [faqRef, faqIn] = useInView();

  return (
    <div className="lp">
      <a className="lp-skip" href="#lp-main" onClick={go('lp-main')}>Pular para o conteúdo</a>
      <header className="lp-top lp-pad">
        <nav className="lp-nav" aria-label="Principal">
          <a href="#lp-main" className="lp-brand" onClick={go('lp-main')}><img src={wordmark} alt="Kiroo, início" height="28" /></a>
          <ul className="lp-links">
            {NAV.map(([id, l]) => <li key={id}><a href={'#' + id} onClick={go(id)}>{l}</a></li>)}
          </ul>
          <div className="lp-nav-cta">
            {signupOpen && <button type="button" className="lp-btn is-quiet" onClick={() => onEnter('login')}><span>Entrar</span></button>}
            <button type="button" className="lp-btn is-ink" onClick={signupOpen ? start : () => onEnter('login')}><span>{signupOpen ? 'Começar a criar' : 'Entrar'}</span></button>
          </div>
        </nav>
      </header>

      <main id="lp-main" tabIndex={-1}>
        <Stage start={start} startLabel={startLabel} signupOpen={signupOpen} />

        {HAS_VIDEO && (
          <section id="exemplos" className="lp-reel lp-pad" aria-labelledby="lp-rl-t" tabIndex={-1}>
            <p className="lp-kick"><span className="lp-clap" aria-hidden="true" />Resultados</p>
            <h2 id="lp-rl-t" className="lp-h2">Saído da sala de edição</h2>
            <div className="lp-reel-row">
              {SHOWCASE.filter((s) => s.video).map((it, i) => <ReelItem key={it.id} item={it} i={i} />)}
            </div>
          </section>
        )}

        <Today />
        <Control />
        <Credits start={start} signupOpen={signupOpen} />

        <section id="duvidas" className={'lp-faq lp-pad' + (faqIn ? ' is-in' : '')} ref={faqRef} aria-labelledby="lp-faq-t" tabIndex={-1}>
          <div className="lp-faq-head">
            <p className="lp-kick"><span className="lp-clap" aria-hidden="true" />Dúvidas</p>
            <h2 id="lp-faq-t" className="lp-h2">Antes de começar</h2>
            <span className="lp-faq-face" aria-hidden="true"><Portrait id="theo" size={72} /></span>
          </div>
          <div className="lp-faq-list">
            {FAQ.map(([q, a], i) => (
              <details key={q} className="lp-qa" style={{ '--i': i }}>
                <summary>{q}<span className="lp-qa-ic" aria-hidden="true" /></summary>
                <p>{a}</p>
              </details>
            ))}
          </div>
        </section>
      </main>

      <Finale start={start} startLabel={startLabel} onEnter={onEnter} NAV={NAV} />
    </div>
  );
}
