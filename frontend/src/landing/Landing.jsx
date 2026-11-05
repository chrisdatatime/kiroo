import React from 'react';
import {
  ArrowRight, Check, CircleDot, Coins, Eye, FileVideo, Hand, Images, MessageCircle, Music2, PackageCheck,
  ReceiptText, RotateCcw, ShieldCheck, Sparkles, Undo2, Users,
} from 'lucide-react';
import wordmark from '../assets/brand/wordmark-preto-laranja.svg';
import wordmarkOnDark from '../assets/brand/wordmark-branco-laranja.svg';
import agentHead from '../assets/brand/simbolo-laranja.svg';
import { ART, AGENT_PINS } from './art.js';
import { AgentHead } from '../shell/AgentHead.jsx';
import './landing.css';

// Home pública (antes do login). Estrutura inspirada em escritórios virtuais, com o conteúdo do Kiroo:
// a sede real (tools/render_home.py), os seis agentes, o Piloto, créditos com estimativa e as regras honestas do produto.
// Nada de depoimentos, logos de clientes ou números inventados.

const TEAM = [
  { id: 'nina', name: 'Nina', role: 'Planejamento', does: 'Lê a ficha e as fotos, separa o que é fato do produto e monta o plano das cenas.' },
  { id: 'theo', name: 'Theo', role: 'Direção criativa', does: 'Propõe o estilo, o cenário e a luz. É aqui que você diz "gostei" ou "muda isso".' },
  { id: 'iris', name: 'Iris', role: 'Imagens', does: 'Cria as imagens das cenas a partir das suas fotos. A cena 1 vira referência das outras.' },
  { id: 'lia', name: 'Lia', role: 'Vídeos', does: 'Anima cada imagem em um take curto e cuida da trilha que vai no vídeo.' },
  { id: 'rui', name: 'Rui', role: 'Revisão', does: 'Compara o resultado com o produto real. Quando não tem certeza, diz que não tem.' },
  { id: 'beto', name: 'Beto', role: 'Edição', does: 'Monta os takes no ritmo escolhido e entrega o vídeo, com e sem música.' },
];

const HERO_TABS = [
  { id: 'sede', label: 'Escritório', icon: Users },
  { id: 'missao', label: 'Missão', icon: PackageCheck },
  { id: 'conversa', label: 'Conversa', icon: MessageCircle },
];

// "Acompanhe cada agente": recortes da sede (x, y, largura, em % do mapa) e o texto de cada foco.
// short = rótulo dos botões compactos no celular.
const FOCUS = [
  { id: 'todos', icon: Eye, short: 'Equipe', title: 'Acompanhe cada agente', text: 'Cada sala é uma etapa da produção. Quem está trabalhando aparece com a cabeça laranja; quem precisa de você mostra um “!”.', box: [0, 0, 100, 100] },
  { id: 'conversar', icon: MessageCircle, short: 'Conversar', title: 'Converse com um agente', text: 'Clique na Iris e pergunte sobre a luz da cena 2. Ela explica; quem decide é você.', box: [70, 0, 30, 30] },
  { id: 'aprovar', icon: Hand, short: 'Aprovar', title: 'Aprove nos pontos certos', text: 'Direção, gastos e revisão final esperam por você. O resto segue sozinho, se você quiser.', box: [0, 0, 30, 30] },
  { id: 'entrega', icon: FileVideo, short: 'Baixar', title: 'Baixe o vídeo pronto', text: 'O Beto entrega o vídeo vertical e uma versão sem música, para você usar um som em alta.', box: [70, 70, 30, 30] },
];

// Agentes na demonstração: sala = etapa. align: etiqueta presa pela ponta perto das bordas da sede. state: work | need | idle (mesma leitura do app: cabeça laranja = ativo).
const CREW = [
  { id: 'nina', name: 'Nina', step: 'Ficha', state: 'need', align: 'start' },
  { id: 'theo', name: 'Theo', step: 'Direção', state: 'idle' },
  { id: 'iris', name: 'Iris', step: 'Imagens', state: 'work' },
  { id: 'lia', name: 'Lia', step: 'Vídeos', state: 'work', align: 'end' },
  { id: 'rui', name: 'Rui', step: 'Revisão', state: 'idle' },
  { id: 'beto', name: 'Beto', step: 'Edição', state: 'idle' },
];
const STATE_LABEL = { work: 'trabalhando', need: 'precisa de você', idle: 'livre' };

const PILOT = [
  { id: 'manual', label: 'Manual', line: 'Você aprova cada passo.', text: 'Direção, cada etapa paga e cada imagem passam por você. Se o Rui achar um problema, ele avisa em vez de refazer.' },
  { id: 'assistido', label: 'Assistido', line: 'Você decide a direção e as dúvidas.', text: 'Depois da direção, a equipe gera dentro do limite de créditos e refaz o que o Rui reprovar. Cena com dúvida espera você.', tag: 'Padrão' },
  { id: 'automatico', label: 'Automático', line: 'Da ficha ao vídeo montado.', text: 'A equipe usa a direção sugerida e vai até o fim dentro do limite. Você só revisa o vídeo antes de exportar.' },
];

const FAQ = [
  ['O vídeo vai ser fiel ao meu produto?', 'A equipe trabalha a partir das suas fotos e da ficha, e o Rui confere cada cena contra elas. Mesmo assim, conferência automática pode ser inconclusiva: quando isso acontece, a cena espera você. Não prometemos 100% de fidelidade; prometemos dizer quando há dúvida.'],
  ['O Kiroo publica direto na Shopee?', 'Não. Você baixa o vídeo e publica pelo app ou pelo painel da Shopee. A legenda sugerida usa só o que está na ficha e o que você confirmou: nada de preço, variante ou característica inventada.'],
  ['Quanto custa um vídeo?', 'Depende de quantas imagens e takes a produção usa. Antes de cada etapa paga você vê a estimativa em créditos e o limite da produção. Se uma geração falha, o crédito reservado volta para o saldo.'],
  ['O que é o modo DEMO?', 'Contas novas começam no DEMO: o fluxo inteiro funciona, mas imagens e vídeos são de exemplo e não custam nada. Serve para conhecer a equipe antes de gastar créditos.'],
  ['Preciso andar pelo escritório para usar?', 'Não. O escritório é para ver a equipe trabalhando e conversar com ela quando quiser. Tudo o que importa (aprovar, liberar gasto, baixar) fica a um clique na Central.'],
  ['Posso usar uma música que está em alta?', 'Músicas virais não podem ser embutidas no vídeo. Por isso a entrega vem também sem música: você escolhe o som em alta direto no editor da Shopee.'],
];

const go = (id) => (e) => {
  e.preventDefault();
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
};

function Sprite({ id, size = 64, alt = '' }) {
  if (!ART[id]) return <span className="lp-sprite lp-sprite-empty" style={{ width: size, height: size }} aria-hidden={!alt} />;
  return <img className="lp-sprite" src={ART[id]} width={size} height={size} alt={alt} draggable="false" />;
}

function Sede({ className = '', style, children }) {
  return (
    <div className={'lp-sede ' + className} style={style}>
      {ART.sede ? <img src={ART.sede} alt="" draggable="false" /> : <div className="lp-sede-empty" />}
      {children}
    </div>
  );
}

function Pin({ id, children, need, work, quiet }) {
  const p = AGENT_PINS[id];
  return (
    <span className={'lp-pin' + (quiet ? ' is-quiet' : '')} style={{ left: p.x + '%', top: p.y + '%' }}>
      {need && <b className="lp-need" aria-label="precisa de você">!</b>}
      {work && <span className="lp-work" aria-hidden="true"><i /><i /><i /></span>}
      <span className="lp-pin-tag"><span className={'lp-dot' + (need ? ' is-need' : work ? ' is-work' : '')} />{children}</span>
    </span>
  );
}

function HeroScene() {
  const [tab, setTab] = React.useState('sede');
  return (
    <div className="lp-hero-art">
      <div className="lp-frame">
        <Sede>
          <div className={'lp-layer' + (tab === 'sede' ? ' is-on' : '')} aria-hidden={tab !== 'sede'}>
            <Pin id="nina" need>Nina</Pin>
            <Pin id="theo">Theo</Pin>
            <Pin id="iris" work>Iris</Pin>
            <Pin id="lia" work>Lia</Pin>
            <Pin id="rui">Rui</Pin>
            <Pin id="beto">Beto</Pin>
            <span className="lp-room-label" style={{ left: '50%', top: '31%' }}>Área comum</span>
          </div>
          <div className={'lp-layer' + (tab === 'missao' ? ' is-on' : '')} aria-hidden={tab !== 'missao'}>
            <Pin id="iris" work quiet>Iris</Pin>
            <div className="lp-card lp-mission">
              <div className="lp-card-kicker">Missão em curso</div>
              <div className="lp-card-title">Garrafa térmica 500 ml</div>
              <ol className="lp-steps">
                <li className="is-done"><Check size={14} />Ficha e fotos</li>
                <li className="is-done"><Check size={14} />Direção aprovada</li>
                <li className="is-now"><CircleDot size={14} />Imagens <em>2 de 3</em></li>
                <li><span className="lp-step-dot" />Vídeos</li>
                <li><span className="lp-step-dot" />Revisão e entrega</li>
              </ol>
              <div className="lp-meter" aria-label="18 de 40 créditos usados"><span style={{ width: '45%' }} /></div>
              <div className="lp-card-foot"><span>18 de 40 créditos</span><span>limite da produção</span></div>
            </div>
          </div>
          <div className={'lp-layer' + (tab === 'conversa' ? ' is-on' : '')} aria-hidden={tab !== 'conversa'}>
            <Pin id="iris" quiet>Iris</Pin>
            <div className="lp-card lp-chat">
              <div className="lp-chat-head"><Sprite id="iris" size={32} /><div><strong>Iris</strong><span>Imagens · criando a cena 2</span></div></div>
              <p className="lp-bubble is-me">Vai manter o mesmo fundo da cena 1?</p>
              <p className="lp-bubble">Vou. A cena 1 aprovada virou referência, então luz e mármore continuam iguais.</p>
              <p className="lp-bubble is-me">E se eu quiser um fundo mais escuro?</p>
              <p className="lp-bubble">Pede ao Theo na direção. Eu só sigo o que estiver aprovado lá.</p>
            </div>
          </div>
        </Sede>
      </div>
      <div className="lp-switch" role="tablist" aria-label="O que mostrar na sede">
        {HERO_TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} className="lp-switch-btn" onClick={() => setTab(id)}>
            <Icon size={18} strokeWidth={1.8} aria-hidden="true" />{label}
          </button>
        ))}
      </div>
    </div>
  );
}

function useNarrow(q = '(max-width: 640px)') {
  const get = () => typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia(q).matches;
  const [n, setN] = React.useState(get);
  React.useEffect(() => {
    if (!window.matchMedia) return undefined;
    const m = window.matchMedia(q), h = () => setN(m.matches);
    if (m.addEventListener) m.addEventListener('change', h); else m.addListener(h);
    return () => { if (m.removeEventListener) m.removeEventListener('change', h); else m.removeListener(h); };
  }, [q]);
  return n;
}

// Etiqueta de um agente na sede. Fica dentro da camada com zoom: --inv devolve o tamanho real na tela.
function CrewPin({ a, dim }) {
  const p = AGENT_PINS[a.id];
  return (
    <span className={'lp-crew' + (a.align ? ' is-' + a.align : '') + (dim ? ' is-dim' : '')} data-state={a.state} style={{ left: p.x + '%', top: p.y + '%' }}>
      <span className="lp-crew-tag">
        <AgentHead active={a.state !== 'idle'} size={12} />
        <strong>{a.name}</strong><span className="lp-crew-step">{a.step}</span>
        {a.state === 'need' && <b className="lp-crew-need" aria-hidden="true">!</b>}
      </span>
    </span>
  );
}

function FocusScene() {
  const [k, setK] = React.useState(0);
  const narrow = useNarrow();
  const f = FOCUS[k];
  const [x, y, w] = f.box;
  const scale = 100 / w;
  // no celular, a visão geral não encolhe a sede inteira: ela fica maior e rola na horizontal
  const pan = narrow && f.id === 'todos';
  const viewRef = React.useRef(null);
  React.useEffect(() => { if (viewRef.current) viewRef.current.scrollLeft = 0; }, [pan]);
  const onKey = (e) => {
    const d = e.key === 'ArrowDown' || e.key === 'ArrowRight' ? 1 : e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const n = (k + d + FOCUS.length) % FOCUS.length;
    setK(n);
    const btn = e.currentTarget.querySelectorAll('button')[n];
    if (btn) btn.focus();
  };
  return (
    <div className="lp-focus">
      <ul className="lp-focus-list" aria-label="O que ver na demonstração" onKeyDown={onKey}>
        {FOCUS.map((it, i) => {
          const Icon = it.icon, on = k === i;
          return (
            <li key={it.id}>
              <button type="button" className="lp-focus-btn" aria-pressed={on} aria-label={it.title} onClick={() => setK(i)}>
                <span className="lp-focus-ic"><Icon size={18} strokeWidth={1.8} aria-hidden="true" /></span>
                <span className="lp-focus-body">
                  <strong><span className="lp-focus-long">{it.title}</span><span className="lp-focus-short">{it.short}</span></strong>
                  <span className="lp-focus-more" aria-hidden={!on}><span className="lp-focus-txt">{it.text}</span></span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <figure className="lp-focus-stage">
        <div className={'lp-focus-view' + (pan ? ' is-pan' : '')} ref={viewRef} aria-live="polite">
          <Sede className="lp-zoom" style={pan ? undefined : { transform: `scale(${scale}) translate(${-x}%, ${-y}%)`, '--inv': 1 / scale }}>
            <div className="lp-crew-layer">
              {CREW.map((a) => <CrewPin key={a.id} a={a} dim={f.id !== 'todos'} />)}
            </div>
          </Sede>
          {f.id === 'conversar' && (
            <div className="lp-card lp-float lp-float-r">
              <p className="lp-bubble is-me">Que luz você vai usar na cena 2?</p>
              <p className="lp-bubble">Luz de janela, da esquerda, igual à cena 1.</p>
            </div>
          )}
          {f.id === 'aprovar' && (
            <div className="lp-card lp-float lp-float-r">
              <div className="lp-card-kicker"><b className="lp-need is-inline">!</b> Nina precisa de você</div>
              <div className="lp-card-title">Liberar as imagens</div>
              <p className="lp-small">3 imagens · estimativa de 12 créditos. Seu limite nesta produção é 40.</p>
              <div className="lp-row"><span className="lp-fake-btn is-lime">Liberar</span><span className="lp-fake-btn">Ajustar antes</span></div>
            </div>
          )}
          {f.id === 'entrega' && (
            <div className="lp-card lp-float lp-float-l">
              <div className="lp-card-kicker">Entrega pronta</div>
              <div className="lp-file"><FileVideo size={18} aria-hidden="true" /><span>video-final.mp4</span><em>9:16</em></div>
              <div className="lp-file"><Music2 size={18} aria-hidden="true" /><span>video-sem-musica.mp4</span><em>9:16</em></div>
            </div>
          )}
        </div>
        <figcaption className="lp-focus-cap">
          <p className="lp-focus-note">{f.text}</p>
          <ul className="lp-legend" aria-label="Legenda">
            {['work', 'need', 'idle'].map((st) => (
              <li key={st}><AgentHead active={st !== 'idle'} size={12} />{st === 'need' && <b className="lp-crew-need is-sm" aria-hidden="true">!</b>}{STATE_LABEL[st]}</li>
            ))}
            {pan && <li className="lp-legend-hint">Arraste para ver as salas</li>}
          </ul>
        </figcaption>
      </figure>
    </div>
  );
}

export default function Landing({ onEnter, signupOpen }) {
  const start = () => onEnter(signupOpen ? 'signup' : 'login');
  const startLabel = signupOpen ? 'Começar no DEMO' : 'Entrar no estúdio';
  React.useEffect(() => { document.title = 'Kiroo — Uma equipe de vídeo para a sua loja'; return () => { document.title = 'Kiroo'; }; }, []);

  return (
    <div className="lp">
      <a className="lp-skip" href="#lp-main" onClick={go('lp-main')}>Pular para o conteúdo</a>
      <header className="lp-top">
        <nav className="lp-nav" aria-label="Principal">
          <a href="#lp-main" className="lp-brand" onClick={go('lp-main')}><img src={wordmark} alt="Kiroo" height="30" /></a>
          <ul className="lp-links">
            <li><a href="#como" onClick={go('como')}>Como funciona</a></li>
            <li><a href="#equipe" onClick={go('equipe')}>Equipe</a></li>
            <li><a href="#creditos" onClick={go('creditos')}>Créditos</a></li>
            <li><a href="#duvidas" onClick={go('duvidas')}>Dúvidas</a></li>
          </ul>
          <div className="lp-nav-cta">
            <button type="button" className="lp-btn is-ghost" onClick={() => onEnter('login')}>Entrar</button>
            {signupOpen && <button type="button" className="lp-btn is-ink" onClick={() => onEnter('signup')}>Criar conta</button>}
          </div>
        </nav>
      </header>

      <main id="lp-main" tabIndex={-1}>
        {/* ---------------------------------------------------------------- hero */}
        <section className="lp-hero lp-wrap">
          <div className="lp-hero-copy">
            <p className="lp-eyebrow"><span className="lp-eyebrow-dot" />Vídeos de produto para a Shopee Vídeo</p>
            <h1 className="lp-h1">Sua loja ganhou uma <mark>equipe de vídeo</mark>.</h1>
            <p className="lp-lead">
              Você manda as fotos do produto. Seis agentes planejam, criam as imagens, animam, conferem e montam, num escritório que você
              vê funcionando. Você aprova o que importa e baixa o vídeo pronto.
            </p>
            <div className="lp-row">
              <button type="button" className="lp-btn is-lime is-lg" onClick={start}>{startLabel}<ArrowRight size={18} aria-hidden="true" /></button>
              <a className="lp-btn is-line is-lg" href="#como" onClick={go('como')}>Ver como funciona</a>
            </div>
            <p className="lp-note">
              {signupOpen ? 'Sem cartão. O DEMO roda o fluxo inteiro com imagens de exemplo.' : 'Acesso por convite. Peça sua conta ao administrador do estúdio.'}
            </p>
          </div>
          <HeroScene />
        </section>

        {/* ---------------------------------------------------------------- o que sai */}
        <section className="lp-wrap lp-out" aria-labelledby="lp-out-t">
          <h2 id="lp-out-t" className="lp-out-t">O que chega no fim</h2>
          <ul className="lp-out-list">
            <li><FileVideo size={20} strokeWidth={1.8} aria-hidden="true" />Vídeo vertical 9:16</li>
            <li><Images size={20} strokeWidth={1.8} aria-hidden="true" />3 cenas feitas das suas fotos</li>
            <li><ReceiptText size={20} strokeWidth={1.8} aria-hidden="true" />Legenda só com dados da ficha</li>
            <li><Music2 size={20} strokeWidth={1.8} aria-hidden="true" />Versão sem música para som em alta</li>
          </ul>
        </section>

        {/* ---------------------------------------------------------------- como funciona */}
        <section id="como" className="lp-section lp-wrap">
          <div className="lp-head">
            <p className="lp-kicker">Escritório virtual</p>
            <h2 className="lp-h2">Veja a equipe trabalhando</h2>
            <p className="lp-sub">Nada de tela de “processando”. Cada etapa tem uma sala, cada sala tem um agente, e você sempre sabe onde está o seu vídeo.</p>
          </div>
          <FocusScene />
        </section>

        {/* ---------------------------------------------------------------- piloto */}
        <section className="lp-section lp-wrap" aria-labelledby="lp-pilot-t">
          <div className="lp-head">
            <p className="lp-kicker">Piloto</p>
            <h2 id="lp-pilot-t" className="lp-h2">Você decide até onde a equipe vai sozinha</h2>
            <p className="lp-sub">Três jeitos de trabalhar. Dá para trocar no meio da produção. A revisão final e a exportação são sempre suas.</p>
          </div>
          <div className="lp-pilots">
            {PILOT.map((p, i) => (
              <article key={p.id} className="lp-pilot">
                <div className="lp-pilot-art" aria-hidden="true">
                  <div className="lp-track">
                    {['Direção', 'Imagens', 'Vídeos', 'Entrega'].map((s, k) => {
                      const you = i === 0 || (i === 1 && k === 0) || k === 3;
                      return <span key={s} className={'lp-track-step' + (you ? ' is-you' : '')}>{you ? <Hand size={13} /> : <Sparkles size={13} />}{s}</span>;
                    })}
                  </div>
                  <span className="lp-track-key"><Hand size={12} /> você aprova <Sparkles size={12} /> a equipe segue</span>
                </div>
                <h3 className="lp-h3">{p.label}{p.tag && <span className="lp-tag">{p.tag}</span>}</h3>
                <p className="lp-pilot-line">{p.line}</p>
                <p className="lp-p">{p.text}</p>
              </article>
            ))}
          </div>
        </section>

        {/* ---------------------------------------------------------------- comparação */}
        <section className="lp-section lp-wrap" aria-labelledby="lp-cmp-t">
          <div className="lp-head">
            <h2 id="lp-cmp-t" className="lp-h2">E se o vídeo do anúncio não tomasse a sua tarde?</h2>
          </div>
          <div className="lp-compare">
            <div className="lp-cmp is-before">
              <h3 className="lp-cmp-h"><span className="lp-cmp-ic"><RotateCcw size={18} aria-hidden="true" /></span>Fazendo sozinho</h3>
              <ul>
                <li>Montar cenário, luz e celular para cada produto</li>
                <li>Gerar imagem com IA e torcer para não mudar o produto</li>
                <li>Refazer sem saber quanto já gastou</li>
                <li>Editar, cortar e exportar no tamanho certo</li>
                <li>Descobrir depois que a música não pode</li>
              </ul>
            </div>
            <div className="lp-cmp is-after">
              <h3 className="lp-cmp-h"><span className="lp-cmp-ic"><img src={agentHead} alt="" width="22" /></span>Com a equipe do Kiroo</h3>
              <ul>
                <li>Você manda fotos e ficha, a Nina organiza</li>
                <li>O Rui confere cada cena contra o produto real</li>
                <li>Estimativa antes de gastar, limite por produção</li>
                <li>O Beto entrega montado, em 9:16</li>
                <li>Versão sem música pronta para o som em alta</li>
              </ul>
              <div className="lp-cmp-team" aria-hidden="true">
                {TEAM.map((a) => <Sprite key={a.id} id={a.id} size={48} />)}
              </div>
            </div>
          </div>
        </section>

        {/* ---------------------------------------------------------------- equipe */}
        <section id="equipe" className="lp-section lp-wrap">
          <div className="lp-head">
            <p className="lp-kicker">Equipe</p>
            <h2 className="lp-h2">Seis agentes, um trabalho cada</h2>
            <p className="lp-sub">Eles não fazem tudo. Cada um cuida de uma parte e passa para o próximo, como num estúdio de verdade.</p>
          </div>
          <ol className="lp-team">
            {TEAM.map((a, i) => (
              <li key={a.id} className="lp-agent">
                <div className="lp-agent-top">
                  <Sprite id={a.id} size={64} />
                  <span className="lp-agent-n">{String(i + 1).padStart(2, '0')}</span>
                </div>
                <h3 className="lp-h3">{a.name}<span>{a.role}</span></h3>
                <p className="lp-p">{a.does}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* ---------------------------------------------------------------- créditos */}
        <section id="creditos" className="lp-section lp-wrap">
          <div className="lp-credits">
            <div>
              <p className="lp-kicker">Créditos</p>
              <h2 className="lp-h2">Você sabe o custo antes de gastar</h2>
              <ul className="lp-checks">
                <li><Coins size={20} strokeWidth={1.8} aria-hidden="true" /><span><strong>Estimativa antes de cada etapa paga.</strong> Imagens e vídeos só começam depois que você libera.</span></li>
                <li><ShieldCheck size={20} strokeWidth={1.8} aria-hidden="true" /><span><strong>Limite por produção.</strong> Chegou nele, a equipe para e guarda tudo o que já fez.</span></li>
                <li><Undo2 size={20} strokeWidth={1.8} aria-hidden="true" /><span><strong>Falhou, voltou.</strong> O crédito é reservado antes e devolvido se a geração não sai.</span></li>
              </ul>
            </div>
            <div className="lp-receipt" aria-label="Exemplo de extrato de uma produção">
              <div className="lp-receipt-h"><span>Extrato da produção</span><em>exemplo</em></div>
              <dl>
                <div><dt>Imagens · 3 cenas</dt><dd>12</dd></div>
                <div><dt>Refação da cena 2</dt><dd>4</dd></div>
                <div><dt>Vídeos · 3 takes</dt><dd>21</dd></div>
                <div className="is-back"><dt>Take 3 falhou · estorno</dt><dd>−7</dd></div>
                <div><dt>Montagem e legenda</dt><dd>0</dd></div>
              </dl>
              <div className="lp-receipt-t"><span>Total</span><strong>30 créditos</strong></div>
              <div className="lp-receipt-lim"><span style={{ width: '75%' }} /></div>
              <p className="lp-small">Limite desta produção: 40 créditos</p>
            </div>
          </div>
        </section>

        {/* ---------------------------------------------------------------- começar */}
        <section className="lp-section lp-wrap">
          <div className="lp-start">
            <div className="lp-start-copy">
              <p className="lp-kicker">Começar</p>
              <h2 className="lp-h2">Da foto ao vídeo em três passos seus</h2>
              <p className="lp-sub">O resto é com a equipe.</p>
              <button type="button" className="lp-btn is-lime is-lg" onClick={start}>{startLabel}<ArrowRight size={18} aria-hidden="true" /></button>
            </div>
            <ol className="lp-steps-big">
              <li><span className="lp-chip is-sun">Você</span><strong>Mande as fotos e a ficha do produto</strong></li>
              <li><span className="lp-chip is-sky">Você</span><strong>Aprove a direção que o Theo propôs</strong></li>
              <li><span className="lp-chip is-lime">Você</span><strong>Revise e baixe o vídeo montado</strong></li>
            </ol>
            <div className="lp-start-floor" aria-hidden="true">
              {TEAM.map((a) => <Sprite key={a.id} id={a.id} size={56} />)}
            </div>
          </div>
        </section>

        {/* ---------------------------------------------------------------- dúvidas */}
        <section id="duvidas" className="lp-section lp-wrap lp-faq-wrap">
          <div className="lp-head">
            <p className="lp-kicker">Dúvidas</p>
            <h2 className="lp-h2">Perguntas que todo mundo faz</h2>
          </div>
          <div className="lp-faq">
            {FAQ.map(([q, a]) => (
              <details key={q} className="lp-qa">
                <summary>{q}<span className="lp-qa-ic" aria-hidden="true" /></summary>
                <p>{a}</p>
              </details>
            ))}
          </div>
        </section>
      </main>

      {/* ---------------------------------------------------------------- rodapé */}
      <footer className="lp-foot">
        <div className="lp-wrap">
          <div className="lp-foot-cta">
            <h2 className="lp-h2 is-light">Seu estúdio ganha vida.</h2>
            <p>Conheça a equipe no DEMO e veja o primeiro vídeo sair antes de gastar um crédito.</p>
            <button type="button" className="lp-btn is-lime is-lg" onClick={start}>{startLabel}<ArrowRight size={18} aria-hidden="true" /></button>
          </div>
          <div className="lp-foot-row">
            <img className="lp-foot-brand" src={wordmarkOnDark} alt="Kiroo" height="26" />
            <nav aria-label="Rodapé" className="lp-foot-links">
              <a href="#como" onClick={go('como')}>Como funciona</a>
              <a href="#equipe" onClick={go('equipe')}>Equipe</a>
              <a href="#creditos" onClick={go('creditos')}>Créditos</a>
              <a href="#duvidas" onClick={go('duvidas')}>Dúvidas</a>
              <button type="button" onClick={() => onEnter('login')}>Entrar</button>
            </nav>
          </div>
          <p className="lp-foot-legal">
            Arte da sede: Modern Interiors e Modern Office por LimeZu (<a href="https://limezu.itch.io/moderninteriors" target="_blank" rel="noopener noreferrer">limezu.itch.io</a>).
            Shopee é marca da Sea Limited; o Kiroo não é afiliado à Shopee.
          </p>
        </div>
      </footer>
    </div>
  );
}
