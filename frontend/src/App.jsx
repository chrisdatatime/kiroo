import React from 'react';
import { GRID, AGENTS, TABS, STAGES, STAGE_LABELS, BLOCKED, SPOTS, ROOMS, CHAIRS, FURNITURE, INTERACT, SPAWN, tilesOf } from './game/data.js';
import { bfs, screenToTile, facing } from './game/geometry.js';
import { initialAgent, stepSeated } from './game/agentLife.js';
import { lazyChunk } from './lib/lazyChunk.jsx';
import SectorsWindow from './ui/Sectors.jsx';
import TrainingWindow, { LearnPanel } from './ui/Training.jsx';
import MusicWindow from './ui/Music.jsx';
// Phaser (~1 MB) só carrega com a flag ligada e depois do login: chunk separado (SPEC-VIS-001, Fase 2)
const WorldPhaser = lazyChunk(() => import('./ui/WorldPhaser.jsx'));
import Hud from './ui/Hud.jsx';
import { normalizeTheme, DEFAULT_THEME, THEME_KEY } from './game/scenery/scenery.js';
import { Tutorial, DialogWindow, BoardWindow, CustomWindow } from './ui/Windows.jsx';
import ProdWindow from './ui/ProdWindow.jsx';
import GamesWindow from './ui/Games.jsx';
import { PILOT } from './ui/Pilot.jsx';
import { me, auth, authConfig, setLoggedOutHandler, AuthRequired, getJSON, post, readFile } from './engine/api.js';
import AuthScreen from './ui/Auth.jsx';
const Landing = lazyChunk(() => import('./landing/Landing.jsx'));
// Conta, Piloto, Créditos e Sobre vivem no modal de Preferências (carregado ao abrir)
const Preferences = lazyChunk(() => import('./ui/Preferences.jsx'));
// Conversa com os agentes (Fase 6, mundo Phaser): chunk próprio, carrega no primeiro clique num agente
const AgentChat = lazyChunk(() => import('./ui/world/AgentChat.jsx'));
const PREF_WINS = ['prefs', 'account', 'pilot', 'credits', 'about', 'admin'];
// Kit de onboarding (Fase 5): chunk próprio, só carrega quando o tour abre (onboarding_done_at nulo ou "Rever tutorial")
const Onboarding = lazyChunk(() => import('./onboarding/Onboarding.jsx'));
// se o tour falhar, ele some (e o passo fica salvo); o estúdio continua funcionando
class TourBoundary extends React.Component {
  constructor(p) { super(p); this.state = { failed: false }; }
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(e) { console.error('Tutorial falhou:', e); this.props.onFail(); }
  render() { return this.state.failed ? null : this.props.children; }
}
import { deriveStage, sceneView, toCredits, creditsToUsd } from './engine/adapter.js';
import { adjustmentGate, pauseKind } from './ui/pause.js';
import { balanceLabel, needsConfirmation, usedLabel } from './ui/nextVideo.js';
import { adjustFunds, noBalanceFromError, noBalanceNotice } from './ui/credits.js';
import Shell, { VIEWS } from './shell/Shell.jsx';
import Central from './shell/Central.jsx';
import MissionView from './shell/MissionView.jsx';
import TeamView from './shell/TeamView.jsx';
import { buildPipeline, attention } from './shell/pipeline.js';
import { splitRequests, joinRequests, summaryRows } from './ui/direcao.js';

// Kiroo — escritório-jogo sobre o motor REAL (servidor Python).
// O estado da produção vem de /api/state; as ações chamam a API. O jogo (mundo, movimento, personalização)
// continua local. Se o motor estiver em modo DEMO, as gerações são simuladas lá e a interface avisa.

const AGM = {}; AGENTS.forEach((a) => { AGM[a.id] = a; });
const blocked = {}; BLOCKED.forEach((t) => { blocked[t[0] + ',' + t[1]] = true; });
const WALK_SPOTS = SPOTS;
const T = GRID.T;
const SC = T / 16;          // escala do personagem: 1 no mapa antigo (16 px), 2 no .tmj (32 px)
const placedRoom = (r) => !!r && r.placed !== false;
const TICK = 200;            // ms por passo do jogador; o desenho interpola exatamente esse tempo (constante única)
const AGENT_EVERY = 5;       // agentes andam 1 tile a cada AGENT_EVERY ticks; o desenho deles dura AGENT_EVERY * TICK
const MOVE = { arrowup: [0, -1], w: [0, -1], arrowdown: [0, 1], s: [0, 1], arrowleft: [-1, 0], a: [-1, 0], arrowright: [1, 0], d: [1, 0] };
const CHAIR_BY_ID = {}; CHAIRS.forEach((c) => { CHAIR_BY_ID[c.id] = c; });
const furn = (kind, oh) => { const f = FURNITURE.find((x) => x.kind === kind); return f ? { x: f.x, y: f.y, w: f.w, h: f.h, oh } : null; };
// objetos com interação: retângulo para destaque e clique (oh = quanto o desenho sobe acima da pegada)
const HOT_FURNITURE = { board: furn('prodBoard', 22), coffee: furn('coffeeBar', 16), games: furn('gamesTable', 4), music: furn('musicShelf', 20) };
const CONFETTI = Array.from({ length: 28 }, (_, k) => ({ x: (k * 37) % 100, c: ['#D5F45B', '#E46F5A', '#2F55D4', '#F5C542', '#3FB8AF'][k % 5], d: ((k * 0.23) % 2.4).toFixed(2), t: (2.6 + (k % 5) * 0.35).toFixed(2) }));
const LS = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* armazenamento indisponível */ } },
};
const EMPTY_DRAFT = { name: '', category: '', attrs: '', verified: '', claims: '' };
const ROLES = [['front', 'Frente'], ['side', 'Lateral'], ['lid', 'Tampa'], ['detail', 'Detalhe'], ['back', 'Traseira'], ['top', 'Topo'], ['interior', 'Interior'], ['other', 'Outra']];
const DEFAULT_ROLES = ['front', 'side', 'lid', 'detail', 'interior'];
const cr = (n) => `${n} crédito${n === 1 ? '' : 's'}`;

export default class App extends React.Component {
  constructor(props) {
    super(props);
    this.timers = []; this.t = 0; this.lastStage = null;
    // o escritório só monta depois do login: mede ao montar, não só no componentDidMount
    this.setRoot = (el) => { this.rootEl = el; if (el && this.measure) this.measure(); };
    // o mundo ocupa só a área útil ao lado da navegação: é ela que define vw/vh (zoom e câmera)
    this.setStage = (el) => { this.stageEl = el; if (el && this.measure) this.measure(); };
    this.onKey = (e) => this.handleKey(e);
    this.held = [];          // teclas de direção ainda pressionadas (a última manda)
    this.onKeyUp = (e) => { const k = (e.key || '').toLowerCase(); this.held = this.held.filter((h) => h !== k); };
    this.onBlur = () => { this.held = []; };
    this.onWorldClick = (e) => this.handleWorldClick(e);
    // callbacks estáveis para o tour (não dependem do viewModel recriado a cada tick)
    this.tourApi = {
      save: (p) => this.saveTour(p),
      setView: (id) => { if (this.state.ui.win) this.closeWin(); if (this.state.view !== id) this.setState({ view: id }); },
      newMission: () => { this.setState({ view: 'missao' }); this.newProduction(); },
    };
    this.tourDone = (how) => this.tourClosed(how);
    const agents = {};
    // agente sem sala no mapa (seat null, mapa novo da Fase 2) fica fora do mundo: i/j = -1
    // mundo Phaser (Fase 6): agentes fixos na cadeira da própria sala; o canvas antigo mantém o passeio
    AGENTS.forEach((a) => { agents[a.id] = initialAgent(a.seat); });
    const pid = LS.get('bc.pid', null);
    const view0 = LS.get('bc.view', 'central');
    this.state = {
      view: VIEWS.some((x) => x.id === view0) ? view0 : 'central',
      vw: window.innerWidth, vh: window.innerHeight,
      player: { i: SPAWN[0], j: SPAWN[1], path: [], dir: 'down', moving: false, seat: null }, pending: null, dest: null, agents,
      // motor real
      onb: null,  // { start, key } enquanto o tour está aberto
      S: null, pid, draftMode: false, conn: 'carregando', busy: null, err: null, authState: 'checking', account: null, signup: 'closed',
      resetToken: new URLSearchParams(window.location.search).get('reset'),
      // sem sessão: home pública (null) ou tela de acesso ('login' | 'signup'); ?entrar abre direto o login
      entry: new URLSearchParams(window.location.search).has('entrar') ? 'login' : null,
      draft: Object.assign({}, EMPTY_DRAFT, LS.get('bc.draft', {})), files: [],
      opts: null, creative: null, preview: null, reqText: '', caption: null, pilot: LS.get('bc.autonomy', 'assistido'),
      ui: { win: null, who: null, tab: 'produto', dirSub: 'dir', ctab: 'personagem', revSel: 1, revView: 'scene', adjust: false, issues: [], adjText: '', toast: null, tut: !LS.get('bc.tutDone', false), playing: false, budgetHit: false },
      cenario: normalizeTheme(LS.get(THEME_KEY, DEFAULT_THEME)),
      look: LS.get('bc.look', { shirt: '#D5F45B', acc: 'broto' }),
      setup: LS.get('bc.setup', { desk: 'madeira', chair: 'classica', pc: 'notebook', planta: true, gato: true, luminaria: true, caneca: false, tapete: false }),
    };
  }

  // ---------- ciclo de vida ----------
  componentDidMount() {
    this.measure = () => { const el = this.stageEl || this.rootEl; if (!el) return; const w = el.clientWidth, h = el.clientHeight; if (w !== this.state.vw || h !== this.state.vh) this.setState({ vw: w, vh: h }); };
    this.measure();
    window.addEventListener('resize', this.measure);
    this.iv = setInterval(() => this.tick(), TICK);
    this.poll = setInterval(() => { if (this.state.authState === 'in') this.refresh(); }, 1500);
    // sessão expirou com o estúdio aberto: volta direto ao login (no primeiro /api/me sem sessão, fica a home)
    setLoggedOutHandler(() => this.setState((s) => ({ authState: 'out', account: null, entry: s.authState === 'in' ? 'login' : s.entry })));
    this.checkSession();
    authConfig().then((c) => this.setState({ signup: c.signup || 'closed' })).catch(() => {});  // cadastro: quem decide é o servidor
    this.later(() => this.rootEl && this.rootEl.focus({ preventScroll: true }), 80);
  }
  componentWillUnmount() { clearInterval(this.iv); clearInterval(this.poll); this.timers.forEach(clearTimeout); window.removeEventListener('resize', this.measure); }
  componentDidUpdate(_, prev) {
    if (prev.cenario !== this.state.cenario) LS.set(THEME_KEY, this.state.cenario);
    if (prev.look !== this.state.look) LS.set('bc.look', this.state.look);
    if (prev.setup !== this.state.setup) LS.set('bc.setup', this.state.setup);
    if (prev.draft !== this.state.draft) LS.set('bc.draft', this.state.draft);
    if (prev.pid !== this.state.pid) LS.set('bc.pid', this.state.pid);
    if (prev.view !== this.state.view) { LS.set('bc.view', this.state.view); this.measure && this.measure(); }
  }
  later(fn, ms) { this.timers.push(setTimeout(fn, ms)); }

  // ---------- conta ----------
  async checkSession() {
    if (this.state.resetToken) { this.setState({ authState: 'out' }); return; }
    try {
      const account = await me();
      if (LS.get('bc.ws', null) !== account.workspace.id) {  // outro estúdio neste navegador: não reaproveita a produção aberta
        LS.set('bc.ws', account.workspace.id);
        this.setState({ pid: null, draftMode: false });
      }
      this.setState({ authState: 'in', account }, () => this.refresh());
      this.maybeStartTour(account);
    } catch (e) {
      this.setState({ authState: 'out', conn: e instanceof AuthRequired ? 'ok' : 'erro', err: e instanceof AuthRequired ? null : e.message });
    }
  }
  // ---------- kit de onboarding ----------
  // O estado fica no usuário (servidor: users.onboarding_done_at / onboarding_step, POST /api/onboarding), então vale em
  // qualquer dispositivo. Se o servidor não tiver o campo ou o POST falhar, guarda em localStorage (bc.onb) como reserva.
  maybeStartTour(account) {
    const srv = account && account.user && account.user.onboarding;
    this.onbLocal = !srv;
    const ob = srv || LS.get('bc.onb', { done_at: null, step: 0 });
    if (!ob.done_at) this.setState({ onb: { start: ob.step || 0, key: Date.now() } });
  }
  openTour() {
    this.dismissTut();
    this.setUI({ win: null });
    this.setState({ onb: { start: 0, key: Date.now() } });
  }
  saveTour(p) {
    const local = () => LS.set('bc.onb', { ...LS.get('bc.onb', { done_at: null, step: 0 }), step: p.step ?? 0, ...(p.done ? { done_at: new Date().toISOString() } : {}) });
    if (this.onbLocal) { local(); return; }
    post('/api/onboarding', p).catch(() => { this.onbLocal = true; local(); });
  }
  tourClosed(how) {
    if (how === 'done') this.dismissTut();  // a dica antiga do escritório fica redundante
    this.setState({ onb: null });
    if (this.rootEl) this.rootEl.focus({ preventScroll: true });
  }

  async logout() {
    try { await auth('logout'); } catch { /* sessão já encerrada */ }
    this.setState({ authState: 'out', account: null, S: null, pid: null, draftMode: true, files: [], onb: null });
    this.setUI({ win: null });
  }

  // ---------- motor real ----------
  async refresh() {
    try {
      const q = this.state.pid ? `?pid=${encodeURIComponent(this.state.pid)}&since=999999999` : '?since=999999999';
      const S = await getJSON('/api/state' + q);
      const patch = { S, conn: 'ok' };
      if (!this.state.pid && !this.state.draftMode && S.selected) patch.pid = S.selected;
      if (S.production && this.state.caption === null && S.production.caption) patch.caption = S.production.caption;
      this.setState(patch, () => this.announce());
    } catch (e) { this.setState({ conn: 'erro', err: e.message }); }
  }
  prodP() { const s = this.state; return s.draftMode || !s.S ? null : s.S.production; }
  stage() { return deriveStage(this.prodP()); }
  scenes() { const P = this.prodP(); return P ? P.scenes.map((x) => sceneView(x, P.go_ahead)) : []; }
  pol() { return this.state.S ? this.state.S.settings.credit_policy : null; }
  announce() {
    const st = this.stage();
    if (this.lastStage && st !== this.lastStage) {
      const msg = { direcao: 'A Nina entregou a ficha. O Theo já tem uma proposta.', gerar_img: 'Roteiro pronto. A Iris mostra a estimativa antes de gastar.',
        img_revisao: 'Imagem pronta! O Rui conferiu e chamou você.', gerar_vid: 'Imagens aprovadas! A Lia está pronta para animar.',
        vid_revisao: 'Take pronto. O Rui quer sua opinião.', montando: 'Takes aprovados. O Beto está montando o vídeo.',
        entrega: 'Vídeo montado! Fale com o Beto.', exportado: 'Exportado! Hora de comemorar.' }[st];
      if (msg) this.toast(msg);
    }
    this.lastStage = st;
  }
  async act(label, fn, ok) {
    if (this.state.busy) return false;
    this.setState({ busy: label });
    try { await fn(); if (ok) this.toast(ok); await this.refresh(); return true; }
    catch (e) {
      // Falta de saldo para um ajuste extra: mostra a conta e as saídas (nada foi cobrado nem alterado).
      const nb = noBalanceFromError(e, this.state.ui.revSel);
      if (nb) { this.setUI({ noBalance: nb }); return false; }
      this.toast('Não deu certo: ' + e.message); return false;
    }
    finally { this.setState({ busy: null }); }
  }

  // ---------- grade e caminhos ----------
  inB(i, j) { return i >= 0 && j >= 0 && i < GRID.C && j < GRID.R; }
  passP(i, j) { return this.inB(i, j) && !blocked[i + ',' + j]; }
  passA(a) { return (i, j) => this.inB(i, j) && (!blocked[i + ',' + j] || (i === a.seat[0] && j === a.seat[1])); }

  // ---------- status de cada agente (derivado do estado REAL) ----------
  statusOf(id) {
    const P = this.prodP(), st = this.stage(), sc = this.scenes();
    const imgGen = sc.some((x) => x.img === 'gerando' || x.img === 'fila');
    const vidGen = sc.some((x) => x.vid === 'gerando' || x.vid === 'fila');
    if (id === 'nina') return this.state.busy === 'produto' ? 'work' : (st === 'produto' ? 'need' : 'idle');
    if (id === 'theo') return st === 'direcao' ? (P && P.creative && P.running ? 'work' : 'need') : 'idle';
    if (id === 'iris') return st === 'gerar_img' ? 'need' : (imgGen && P && P.running ? 'work' : 'idle');
    if (id === 'rui') return sc.some((x) => (st.startsWith('img') && (x.img === 'pronta' || x.img === 'falhou')) || (st.startsWith('vid') && (x.vid === 'pronta' || x.vid === 'falhou'))) ? 'need' : 'idle';
    if (id === 'lia') return st === 'gerar_vid' ? 'need' : (vidGen && P && P.running ? 'work' : 'idle');
    if (id === 'beto') return st === 'montando' ? 'work' : (st === 'entrega' ? 'need' : 'idle');
    return 'idle';
  }

  // ---------- IA de movimento dos agentes ----------
  stepAgent(a, st) {
    if (!a.seat) return st;
    return stepSeated(a.seat, st, this.state.ui.win === 'chat' && this.state.ui.who === a.id ? 'talk' : this.statusOf(a.id));
    let { i, j, path, dir, rest } = st;
    if (path.length) {
      const n = path[0];
      return { i: n[0], j: n[1], path: path.slice(1), dir: facing(n[0] - i, n[1] - j, dir), rest, moving: true };
    }
    const status = this.statusOf(a.id);
    const atSeat = i === a.seat[0] && j === a.seat[1];
    const talking = this.state.ui.win === 'dialog' && this.state.ui.who === a.id;
    if (talking) return { i, j, path: [], dir: 'down', rest, moving: false };
    if (status !== 'idle') {
      if (!atSeat) path = bfs([i, j], (u, v) => u === a.seat[0] && v === a.seat[1], this.passA(a)) || [];
      return { i, j, path, dir, rest, moving: false };
    }
    rest -= 1;
    if (rest <= 0) {
      if (atSeat) {
        if (Math.random() < 0.55) {
          const others = AGENTS.filter((b) => b.id !== a.id).map((b) => { const s2 = this.state.agents[b.id]; const end = s2.path.length ? s2.path[s2.path.length - 1] : [s2.i, s2.j]; return end[0] + ',' + end[1]; });
          const free = WALK_SPOTS.filter((sp) => others.indexOf(sp[0] + ',' + sp[1]) < 0);
          const spot = free[Math.floor(Math.random() * free.length)];
          if (spot) path = bfs([i, j], (u, v) => u === spot[0] && v === spot[1], this.passA(a)) || [];
        }
        rest = 8 + Math.floor(Math.random() * 12);
      } else {
        path = bfs([i, j], (u, v) => u === a.seat[0] && v === a.seat[1], this.passA(a)) || [];
        rest = 10 + Math.floor(Math.random() * 12);
      }
    }
    return { i, j, path, dir, rest, moving: false };
  }

  // Loop do jogo: jogador anda a cada 150 ms, agentes a cada 600 ms
  tick() {
    this.t++;
    const s = this.state; const patch = {}; let arrived = false;
    const p = s.player;
    if (p.path.length) {
      const n = p.path[0];
      patch.player = { ...p, i: n[0], j: n[1], dir: facing(n[0] - p.i, n[1] - p.j, p.dir), path: p.path.slice(1), moving: true, seat: null, teleport: false };
      if (!patch.player.path.length) { arrived = true; patch.dest = null; }
    } else if (p.moving) { patch.player = Object.assign({}, p, { moving: false }); }
    // tecla ainda pressionada: emenda o próximo passo antes de parar, para o andar não ficar picotado
    const np = patch.player || p;
    if (!np.path.length && !s.pending && !np.seat) {
      const nx = this.heldStep(np);
      if (nx) { patch.player = { ...np, path: [nx], moving: true }; patch.dest = null; arrived = false; }
    }
    if (this.t % AGENT_EVERY === 0) { const ag = {}; AGENTS.forEach((a) => { ag[a.id] = this.stepAgent(a, s.agents[a.id]); }); patch.agents = ag; }
    if (Object.keys(patch).length) this.setState(patch, () => {
      if (arrived && this.state.pending) { const act = this.state.pending; this.setState({ pending: null }); this.doAction(act); }
    });
  }

  // ---------- interação com objetos ----------
  // agent, monitor (da sala), chair (sentar), stand (levantar), mine, board, coffee, games, music (trilhas da Lia)
  targetTiles(t) {
    if (t.type === 'agent') { const st = this.state.agents[t.id]; return [[st.i, st.j]]; }
    if (t.type === 'monitor') { const r = ROOMS.find((x) => x.id === t.room); return r && r.desk ? tilesOf(r.desk) : []; }
    if (t.type === 'chair' || t.type === 'sit') { const c = CHAIR_BY_ID[t.id]; return [[c.x, c.y]]; }
    if (t.type === 'stand') return [[this.state.player.i, this.state.player.j]];
    return INTERACT[t.type] || [];
  }
  isAdjacent(t) { const p = this.state.player; return this.targetTiles(t).some((x) => Math.max(Math.abs(x[0] - p.i), Math.abs(x[1] - p.j)) <= 1); }
  targetAtTile(i, j) {
    for (const a of AGENTS) { const st = this.state.agents[a.id]; if (st.i === i && st.j === j) return { type: 'agent', id: a.id }; }
    for (const r of ROOMS) if (r.desk && placedRoom(r) && tilesOf(r.desk).some((d) => d[0] === i && d[1] === j)) return r.agent ? { type: 'monitor', room: r.id } : { type: 'mine' };
    // no mapa novo a cadeira tem 2 tiles de altura (encosto em cima): clicar no encosto também é a cadeira
    const c = CHAIRS.find((x) => x.x === i && x.y === j) || (SC > 1 ? CHAIRS.find((x) => x.x === i && x.back > 0 && j < x.y && j >= x.y - x.back) : null);
    if (c) return c.kind === 'agent' ? { type: 'agent', id: c.agent } : { type: 'chair', id: c.id };
    for (const k of Object.keys(INTERACT)) if (INTERACT[k].some((d) => d[0] === i && d[1] === j)) return { type: k };
    return null;
  }
  playerChair() { const p = this.state.player; return p.seat ? CHAIR_BY_ID[p.seat] : null; }
  goInteract(t) {
    this.dismissTut();
    const p = this.state.player;
    if (t.type === 'stand') { this.standUp(); return; }
    if (t.type === 'chair') {
      const c = CHAIR_BY_ID[t.id];
      if (p.seat === c.id) { this.standUp(); return; }
      const pass = (u, v) => this.passP(u, v) || (u === c.x && v === c.y);
      const path = bfs([p.i, p.j], (u, v) => u === c.x && v === c.y, pass);
      if (!path) { this.toast('Não dá para chegar a essa cadeira agora.'); return; }
      this.setState({ player: { ...p, path, seat: null }, pending: { type: 'sit', id: c.id }, dest: [c.x, c.y], ui: { ...this.state.ui, win: null } });
      return;
    }
    if (this.isAdjacent(t) || t.type === 'agent') { this.doAction(t); return; }  // conversa a 1 clique, sem andar
    const tiles = this.targetTiles(t);
    const path = bfs([p.i, p.j], (u, v) => this.passP(u, v) && tiles.some((x) => Math.max(Math.abs(x[0] - u), Math.abs(x[1] - v)) <= 1), (u, v) => this.passP(u, v));
    if (!path) { this.toast('Não dá para chegar lá agora.'); return; }
    this.setState({ player: { ...p, path, seat: null }, pending: t, dest: path[path.length - 1], ui: { ...this.state.ui, win: null } });
  }
  sit(id) {
    const c = CHAIR_BY_ID[id]; const p = this.state.player;
    this.setState({ player: { ...p, i: c.x, j: c.y, path: [], moving: false, seat: c.id, dir: c.face }, dest: null });
  }
  // Levanta para um tile livre ao lado: na direção pedida, senão para trás da cadeira, senão qualquer um
  standUp(d) {
    const p = this.state.player; if (!p.seat) return false;
    const c = CHAIR_BY_ID[p.seat];
    const back = { up: [0, 1], down: [0, -1], left: [1, 0], right: [-1, 0] }[c.face] || [0, 1];
    const dirs = [...(d ? [d] : []), back, [0, 1], [1, 0], [-1, 0], [0, -1], [1, 1], [-1, 1], [1, -1], [-1, -1]];
    for (const [di, dj] of dirs) {
      const ni = p.i + di, nj = p.j + dj;
      if (this.passP(ni, nj)) { this.setState({ player: { ...p, path: [[ni, nj]], seat: null }, pending: null, dest: null }); return true; }
    }
    this.toast('Sem espaço para levantar aqui.');
    return false;
  }
  doAction(t) {
    this.dismissTut();
    // mundo Phaser (Fase 6): agente abre direto o painel de conversa; o canvas antigo mantém o diálogo roteirizado
    if (t.type === 'agent') this.setUI({ win: 'chat', who: t.id });
    else if (t.type === 'monitor') this.openRoomWork(t.room);
    else if (t.type === 'sit') this.sit(t.id);
    else if (t.type === 'chair') this.goInteract(t);
    else if (t.type === 'stand') this.standUp();
    else if (t.type === 'mine') this.setUI({ win: 'custom' });
    else if (t.type === 'board') this.setUI({ win: 'board' });
    else if (t.type === 'games') this.setUI({ win: 'games' });
    else if (t.type === 'music') this.setUI({ win: 'music' });
    else this.toast('Café quentinho. Energia recarregada!');
  }
  nearestTarget() {
    const ch = this.playerChair();
    if (ch) {
      const room = ch.room && ROOMS.find((r) => r.id === ch.room);
      // no mapa novo a cadeira fica a 2 tiles da mesa: o assento diz se usa o monitor (seat.monitor no .tmj)
      if (room && room.agent && (ch.monitor || this.isAdjacent({ type: 'monitor', room: room.id }))) return { type: 'monitor', room: room.id };
      if (ch.kind === 'mine') return { type: 'mine' };
      return { type: 'stand' };
    }
    const cands = [];
    AGENTS.forEach((a) => { if (this.statusOf(a.id) === 'need') cands.push({ type: 'agent', id: a.id }); });
    AGENTS.forEach((a) => { if (this.statusOf(a.id) !== 'need') cands.push({ type: 'agent', id: a.id }); });
    ROOMS.forEach((r) => { if (r.agent && placedRoom(r) && r.desk) cands.push({ type: 'monitor', room: r.id }); });
    cands.push({ type: 'mine' }, { type: 'board' }, { type: 'music' }, { type: 'games' }, { type: 'coffee' });
    CHAIRS.forEach((c) => { if (c.kind !== 'agent') cands.push({ type: 'chair', id: c.id }); });
    return cands.find((c) => this.isAdjacent(c)) || null;
  }
  labelFor(t) {
    if (!t) return '';
    const L = {
      agent: () => 'Falar com ' + AGM[t.id].name, monitor: () => 'Usar o monitor: ' + ROOMS.find((r) => r.id === t.room).name,
      chair: () => 'Sentar', stand: () => 'Levantar', mine: () => 'Personalizar meu setup', board: () => 'Ver quadro de produções',
      games: () => 'Jogar na mesa de jogos', music: () => 'Abrir as trilhas da Lia', coffee: () => 'Pegar um café',
    };
    return (L[t.type] || L.coffee)();
  }
  highlightOf(t) {
    if (!t || t.type === 'stand') return null;
    if (t.type === 'agent') return { char: t.id };
    if (t.type === 'monitor' || t.type === 'mine') { const r = ROOMS.find((x) => (t.type === 'mine' ? x.id === 'meu' : x.id === t.room)); const d = r && r.desk; return d ? { x: d.x, y: d.y, w: d.w, h: d.h, oh: 14 * SC } : null; }
    if (t.type === 'chair') { const c = CHAIR_BY_ID[t.id]; return { x: c.x, y: c.y, w: 1, h: 1, oh: 6 * SC }; }
    return HOT_FURNITURE[t.type] || null;
  }
  // Hover do mapa (mundo Phaser): o que o clique neste tile faz. floor = dá para andar até aqui; target = cadeira/monitor/objeto
  // (retângulo em tiles + rótulo da ação). Agente fica de fora: ele já tem o hover card.
  hoverAt(i, j) {
    if (!this.inB(i, j)) return null;
    const t = this.targetAtTile(i, j);
    if (t) {
      if (t.type === 'agent') return null;
      const h = this.highlightOf(t); if (!h || h.char) return null;
      if (t.type === 'chair') {
        const c = CHAIR_BY_ID[t.id], back = SC > 1 ? (c.back || 0) : 0;
        return { kind: 'target', x: c.x, y: c.y - back, w: 1, h: 1 + back, label: this.state.player.seat === c.id ? 'Levantar' : 'Sentar aqui' };
      }
      return { kind: 'target', x: h.x, y: h.y, w: h.w, h: h.h, oh: h.oh || 0, label: this.labelFor(t) };
    }
    return this.passP(i, j) ? { kind: 'floor', x: i, y: j, w: 1, h: 1 } : null;
  }

  // ---------- entrada: teclado e clique ----------
  handleKey(e) {
    const tag = ((e.target && e.target.tagName) || '').toLowerCase();
    const k = (e.key || '').toLowerCase();
    if (k === 'escape') { if (this.state.ui.win) { e.preventDefault(); this.closeWin(); } return; }
    if (this.state.view !== 'escritorio') return;  // andar e interagir só valem no Escritório
    // digitando em um campo: os atalhos do jogo ficam suspensos
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || (e.target && e.target.isContentEditable)) return;
    if (this.state.ui.win && this.state.ui.win !== 'custom') return;
    if ((tag === 'button' || tag === 'a') && (k === 'enter' || k === ' ')) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (MOVE[k]) {
      e.preventDefault();
      if (!this.held.includes(k)) this.held.push(k);
      if (!e.repeat) { this.dismissTut(); this.stepPlayer(MOVE[k]); }
      return;
    }
    if (k === 'e' || k === 'enter' || k === ' ') { e.preventDefault(); const n = this.nearestTarget(); if (n) this.doAction(n); }
  }
  heldStep(p) {
    for (let k = this.held.length - 1; k >= 0; k--) {
      const d = MOVE[this.held[k]];
      const t = [p.i + d[0], p.j + d[1]];
      if (this.passP(t[0], t[1])) return t;
    }
    return null;
  }
  stepPlayer(d) {
    const p = this.state.player;
    if (p.seat) { this.standUp(d); return; }
    if (p.path.length) return;
    const t = [p.i + d[0], p.j + d[1]];
    if (this.passP(t[0], t[1])) this.setState({ player: { ...p, path: [t], moving: true }, pending: null, dest: null });
  }
  handleWorldClick(e) {
    this.dismissTut();
    if (this.state.ui.win === 'dialog' || this.state.ui.win === 'board') this.closeWin();
    const rect = e.currentTarget.getBoundingClientRect(); const sc = rect.width / GRID.W;
    const [i, j] = screenToTile((e.clientX - rect.left) / sc, (e.clientY - rect.top) / sc, T);
    if (this.rootEl) this.rootEl.focus({ preventScroll: true });
    if (!this.inB(i, j)) return;
    const hit = this.targetAtTile(i, j); if (hit) { this.goInteract(hit); return; }
    this.walkTo(i, j);
  }
  walkTo(i, j) {
    if (!this.passP(i, j)) return;
    const p = this.state.player; if (p.i === i && p.j === j) return;
    const path = bfs([p.i, p.j], (u, v) => u === i && v === j, (u, v) => this.passP(u, v));
    if (path) this.setState({ player: { ...p, path, seat: null }, pending: null, dest: [i, j] });
    else this.toast('Não dá para chegar lá agora.');
  }

  // ---------- mapa e salas ----------
  // A sede inteira sempre na tela, como no Gather: só as paredes externas ficam sob o HUD
  fitZoom() { return Math.min((this.state.vw - 12) / GRID.W, (this.state.vh - 46) / GRID.H); }
  // Vai direto para a entrada da sala, sem caminhar
  goRoom(id) {
    const r = ROOMS.find((x) => x.id === id); const p = this.state.player;
    if (!placedRoom(r)) return false;  // sala ainda fora do mapa novo (Fase 2b): os atalhos seguem funcionando
    this.setState({ player: { ...p, i: r.entry[0], j: r.entry[1], path: [], moving: false, seat: null, teleport: true }, pending: null, dest: null });
  }
  openRoomWork(id) {
    const r = ROOMS.find((x) => x.id === id);
    if (!r.agent) { this.setUI({ win: 'custom' }); return; }
    this.openProd(r.tab);
  }
  roomStatus(r) {
    const P = this.prodP(), st = this.stage(), sc = this.scenes(), idx = STAGES.indexOf(st);
    const running = (k) => sc.find((x) => x[k] === 'gerando');
    if (!r.agent) return P ? STAGE_LABELS[st] : 'Nenhuma produção aberta';
    if (!P && r.agent !== 'nina') return 'Sem tarefa agora';
    const status = this.statusOf(r.agent);
    switch (r.agent) {
      case 'nina': if (!P) return 'Aguardando produto'; if (P.status === 'awaiting_references') return 'Aguardando referência'; return status === 'need' ? 'Ficha para conferir' : 'Ficha conferida';
      case 'theo': if (st === 'direcao') return status === 'work' ? 'Escrevendo o roteiro' : 'Precisa de aprovação'; return idx > 1 ? 'Direção aprovada' : 'Aguardando a ficha';
      case 'iris': { const g = running('img'); if (g) return 'Criando cena ' + g.idx; if (st === 'gerar_img') return 'Aguardando sua liberação'; return idx > 3 ? 'Imagens entregues' : 'Aguardando a direção'; }
      case 'lia': { const g = running('vid'); if (g) return 'Animando cena ' + g.idx; if (st === 'gerar_vid') return 'Aguardando sua liberação'; return idx > 6 ? 'Vídeos entregues' : 'Aguardando as imagens'; }
      case 'rui': return status === 'need' ? 'Precisa de aprovação' : (idx >= 8 ? 'Revisão concluída' : 'Sem cena para revisar');
      case 'beto': if (st === 'montando') return 'Montando o vídeo'; if (st === 'entrega') return 'Precisa de aprovação'; return st === 'exportado' ? 'Exportado' : 'Aguardando os vídeos';
      default: return '';
    }
  }

  // ---------- helpers de estado ----------
  setUI(patch) { this.setState((s) => ({ ui: Object.assign({}, s.ui, patch) })); }
  setDraft(patch) { this.setState((s) => ({ draft: Object.assign({}, s.draft, patch) })); }
  closeWin() { this.setUI({ win: null, adjust: false, playing: false }); this.later(() => this.rootEl && this.rootEl.focus({ preventScroll: true }), 30); }
  dismissTut() { if (this.state.ui.tut) { this.setUI({ tut: false }); LS.set('bc.tutDone', true); } }
  toast(text) { const id = Date.now() + Math.random(); this.setUI({ toast: { text, id } }); this.later(() => { if (this.state.ui.toast && this.state.ui.toast.id === id) this.setUI({ toast: null }); }, 3800); }

  openProd(tab) {
    const sc = this.scenes(); const kind = this.revKind();
    const first = sc.find((x) => x[kind] === 'pronta' || x[kind] === 'falhou');
    this.setUI({ win: 'prod', tab, adjust: false, issues: [], adjText: '', revSel: first ? first.idx : this.state.ui.revSel, revView: 'scene' });
    if (tab === 'direcao') this.loadOptions();
  }
  revKind() { return STAGES.indexOf(this.stage()) >= 5 ? 'vid' : 'img'; }

  // ---------- ações da produção (API real) ----------
  async addFiles(list) {
    const files = this.state.files.slice();
    for (const f of list) {
      if (!/\.(jpe?g|png|webp|mp4)$/i.test(f.name)) { this.toast('Arquivo ignorado: use JPG, PNG, WEBP ou MP4.'); continue; }
      try {
        const data = await readFile(f);
        files.push({ name: f.name, size: f.size, data, isVideo: /\.mp4$/i.test(f.name), role: DEFAULT_ROLES[files.filter((x) => !x.isVideo).length] || 'other' });
      } catch (e) { this.toast(e.message); }
    }
    this.setState({ files });
  }
  filePayload() { return this.state.files.map((f) => ({ name: f.name, data: f.data, role: f.role, source: 'official_listing' })); }
  draftErrors() {
    const d = this.state.draft, e = [];
    if (!d.name.trim()) e.push('o nome do produto');
    if (!this.state.files.some((f) => !f.isVideo)) e.push('ao menos uma foto do produto');
    return e;
  }
  confirmProduct() {
    const errs = this.draftErrors();
    if (errs.length) { this.toast('Falta ' + errs.join(', ') + '.'); return; }
    const d = this.state.draft;
    this.act('produto', async () => {
      const r = await post('/api/productions', {
        name: d.name, category: d.category, visual_attributes: d.attrs,
        verified: d.verified, seller_claims: d.claims, flow: 'game', start: false, files: this.filePayload(),
        autonomy: this.state.pilot,
      });
      this.setState({ pid: r.pid, draftMode: false, files: [], creative: null, preview: null, caption: null });
      const val = await post(`/api/productions/${r.pid}/validate`);
      this.setState({ draft: Object.assign({}, EMPTY_DRAFT) });
      if (val.ok && this.state.pilot === 'automatico') await this.autoDirection(r.pid);
    }, this.state.pilot === 'automatico' ? 'Piloto automático: o Theo seguiu a proposta. Em produção real, o estúdio começa depois que você confirma o seu próximo vídeo.' : 'A Nina recebeu o produto e está conferindo as fotos.');
  }
  resendRefs() {
    const P = this.prodP(); if (!P) return;
    if (!this.state.files.some((f) => !f.isVideo)) { this.toast('Escolha as fotos primeiro.'); return; }
    this.act('produto', async () => {
      await post(`/api/productions/${P.id}/references`, { files: this.filePayload(), replace: true, visual_attributes: this.state.draft.attrs || undefined });
      this.setState({ files: [] });
    }, 'Fotos enviadas. A Nina está conferindo de novo.');
  }
  async loadOptions() {
    const P = this.prodP(); if (!P) return;
    try {
      const q = new URLSearchParams({ name: P.product.name || '', category: '' });
      const opts = await getJSON('/api/creative/options?' + q);
      const patch = { opts };
      if (!this.state.creative) patch.creative = Object.assign({}, (P.creative || opts.ideas[0].choices));
      this.setState(patch, () => this.loadPreview());
    } catch (e) { this.toast('O Theo não conseguiu carregar as opções: ' + e.message); }
  }
  async autoDirection(pid) {
    const P = this.prodP();
    const name = P ? P.product.name : this.state.draft.name;
    const q = new URLSearchParams({ name: name || '', category: '' });
    const opts = await getJSON('/api/creative/options?' + q);
    const creative = Object.assign({}, opts.ideas[0].choices);
    this.setState({ opts, creative });
    await post(`/api/productions/${pid || P.id}/direction`, { creative });
  }
  setEdit(style, music) {
    const P = this.prodP(); if (!P) return;
    const ready = P.status === 'awaiting_final_review' || P.status === 'completed';
    this.act('montagem', () => post(`/api/productions/${P.id}/edit`, { style, music }),
      ready ? 'O Beto está remontando o vídeo (sem custo de geração).' : 'Estilo da montagem salvo. O Beto usa quando os takes estiverem prontos.');
  }
  setPilot(mode) {
    LS.set('bc.autonomy', mode);
    this.setState({ pilot: mode });
    const P = this.prodP();
    if (!P || ['completed', 'cancelled', 'failed'].includes(P.status)) { this.toast('Piloto ' + PILOT[mode].label + ' para as próximas produções.'); return; }
    this.act('piloto', async () => {
      await post(`/api/productions/${P.id}/autonomy`, { mode });
      if (mode === 'automatico' && this.stage() === 'direcao' && !P.creative) await this.autoDirection(P.id);
    }, 'Piloto ' + PILOT[mode].label + ' nesta produção.');
  }
  setCreative(patch) {
    this.setState((s) => ({ creative: Object.assign({}, s.creative, patch) }), () => { clearTimeout(this.pvT); this.pvT = setTimeout(() => this.loadPreview(), 250); });
  }
  async loadPreview() {
    const P = this.prodP(); if (!P || !this.state.creative) return;
    try { const pv = await post('/api/creative/preview', { name: P.product.name, variant: P.product.variant, creative: this.state.creative }); this.setState({ preview: pv }); }
    catch (e) { /* prévia é auxiliar; a aprovação valida no servidor */ }
  }
  // "Confirmar e criar vídeo": com o resumo "Seu próximo vídeo" à vista, autoriza o custo (nada é gasto antes) e só então
  // manda a direção. Produção sem confirmação (DEMO, antiga) segue o caminho de sempre.
  approveDirection() {
    const P = this.prodP(); if (!P || !this.state.creative) return;
    const confirm = needsConfirmation(P) ? P.confirmation.summary.total_cc : null;
    this.act('direcao', async () => {
      if (confirm !== null) await post(`/api/productions/${P.id}/confirm`, { total_cc: confirm });
      await post(`/api/productions/${P.id}/direction`, { creative: this.state.creative });
    }, confirm !== null ? 'Custo autorizado. O Theo passou as cenas adiante e o roteiro está sendo montado.' : 'O Theo passou as cenas adiante. O roteiro está sendo montado.');
    this.setUI({ win: null });
  }
  // O limite operacional é freio interno do servidor: o cliente não é barrado nem convidado a aumentar nada aqui.
  fits() { return !!this.prodP(); }
  startImages() {
    const P = this.prodP(); if (!P) return;
    if (!this.fits(P.estimates.images.credits)) { this.setUI({ budgetHit: true }); return; }
    this.act('imagens', () => post(`/api/productions/${P.id}/go_ahead`, { stage: 'images' }), 'A Iris começou pela cena 1, que fixa o visual das outras.');
    this.setUI({ win: 'prod', tab: 'imagens' });
  }
  startVideos() {
    const P = this.prodP(); if (!P) return;
    if (!this.fits(P.estimates.videos.credits)) { this.setUI({ budgetHit: true, win: 'prod', tab: 'revisao' }); return; }
    this.act('videos', () => post(`/api/productions/${P.id}/go_ahead`, { stage: 'videos' }), 'A Lia está animando as cenas aprovadas.');
    this.setUI({ win: 'prod', tab: 'videos' });
  }
  // O painel "deve aprender?" só abre depois que o servidor aceitou a decisão.
  async approveScene(idx) {
    const P = this.prodP(); const kind = this.revKind(); if (!P) return;
    const ok = await this.act('aprovar', () => post(`/api/productions/${P.id}/approve`, { scene: idx, stage: kind === 'img' ? 'image' : 'video' }), 'Cena ' + idx + ' aprovada.');
    this.setUI({ adjust: false, issues: [], adjText: '', learn: ok ? { agent: kind === 'img' ? 'iris' : 'lia', name: kind === 'img' ? 'a Iris' : 'a Lia', decision: 'approve', note: '', pid: P.id } : null });
  }
  async sendAdjust() {
    const P = this.prodP(); const kind = this.revKind(); const idx = this.state.ui.revSel; const ui = this.state.ui;
    const stage = kind === 'img' ? 'image' : 'video';
    const sc = (P.scenes || []).find((x) => x.idx === idx);
    const gate = adjustmentGate(sc && sc.adjustments, stage);
    // Ajuste além dos incluídos: só com autorização explícita, mostrando o custo (confirmação dentro do jogo).
    // Sem saldo para o ajuste extra: não pede autorização; mostra saldo, custo e quanto falta (o vídeo fica como está).
    const costCc = sc && sc.adjustments && sc.adjustments.extra_cost_cc ? sc.adjustments.extra_cost_cc[stage] : gate.cost * 100;
    const w = this.state.S && this.state.S.credits;
    if (gate.needsAuth && w && !adjustFunds({ costCc, balanceCc: w.balance_cc, exempt: w.exempt }).enough) {
      this.setUI({ confirmExtra: null, noBalance: noBalanceNotice({ scene: idx, costCc, balanceCc: w.balance_cc }) });
      return;
    }
    this.setUI({ noBalance: null });
    if (gate.needsAuth && !(ui.confirmExtra && ui.confirmExtra.scene === idx)) { this.setUI({ confirmExtra: { scene: idx, cost: gate.cost } }); return; }
    const authorize = !!(gate.needsAuth && ui.confirmExtra && ui.confirmExtra.scene === idx);
    this.setUI({ confirmExtra: null });
    const note = ui.issues.concat((ui.adjText || '').trim() ? [ui.adjText.trim()] : []).join('; ');
    const ok = await this.act('ajuste', () => post(`/api/productions/${P.id}/reject`, { scene: idx, stage, note, authorize_extra: authorize }),
      (kind === 'img' ? 'A Iris' : 'A Lia') + ' está refazendo só a cena ' + idx + '.');
    this.setUI({ adjust: false, issues: [], adjText: '', learn: ok ? { agent: kind === 'img' ? 'iris' : 'lia', name: kind === 'img' ? 'a Iris' : 'a Lia', decision: 'reject', note, pid: P.id } : null });
  }
  // Cena bloqueada sem material: concede +1 tentativa e o motor gera de novo (só esta cena).
  retryScene(idx) {
    const P = this.prodP(); const kind = this.revKind(); if (!P) return;
    this.act('retry', () => post(`/api/productions/${P.id}/retry`, { scene: idx, stage: kind === 'img' ? 'image' : 'video' }),
      (kind === 'img' ? 'A Iris' : 'A Lia') + ' vai tentar a cena ' + idx + ' de novo.');
  }
  // Por que a produção pausou? Cada motivo tem uma saída diferente (o teto do mês não sobe com o limite da produção).
  pauseInfo() {
    const P = this.prodP(), S = this.state.S, pol = this.pol();
    const reason = P && P.status === 'paused' ? (P.reason || '') : '';
    const kind = pauseKind(P && P.status === 'paused' ? P.pause_code : null, reason);
    const m = /estimado US\$([\d.]+)/.exec(reason);
    const nextUsd = m ? +m[1] : 0;
    const spentUsd = S ? S.settings.month_spend_usd : 0, capUsd = S ? S.settings.monthly_cap_usd : 0;
    const opt1 = Math.ceil(toCredits(spentUsd + nextUsd * 3, pol) / 10) * 10;  // folga para mais ~3 passos como este
    const cs = S && S.credits;
    return { kind, reason, next: toCredits(nextUsd, pol), balance: cs ? cs.balance : '0', monthSpent: toCredits(spentUsd, pol), monthCap: toCredits(capUsd, pol),
      capOptions: [opt1, opt1 + 100] };
  }
  raiseMonthly(credits) {
    const P = this.prodP(); if (!P) return;
    const usd = creditsToUsd(credits, this.pol());
    // Confirmação dentro do jogo (o navegador embutido do app bloqueia window.confirm).
    if (this.state.ui.confirmCap !== credits) { this.setUI({ confirmCap: credits, confirmCapUsd: usd }); return; }
    this.setUI({ confirmCap: null });
    this.act('teto', async () => {
      await post('/api/runtime', { monthly_cap_usd: Math.ceil(usd * 100) / 100 });
      if (P.status === 'paused') await post(`/api/productions/${P.id}/resume`);
    }, 'Teto do mês: ' + cr(credits) + '. A produção continua.');
    this.setUI({ budgetHit: false });
  }
  resumeOnly() {
    const P = this.prodP(); if (!P) return;
    this.act('retomar', () => post(`/api/productions/${P.id}/resume`), 'Produção retomada.');
    this.setUI({ budgetHit: false });
  }
  // Encerrar de vez (confirmação dentro do jogo: o navegador embutido bloqueia window.confirm).
  cancelProd() {
    const P = this.prodP(); if (!P) return;
    if (!this.state.ui.confirmCancel) { this.setUI({ confirmCancel: true }); return; }
    this.setUI({ confirmCancel: false, budgetHit: false });
    this.act('cancelar', () => post(`/api/productions/${P.id}/cancel`), 'Produção encerrada. O que já foi gerado continua no histórico.');
  }
  exportVideo() {
    const P = this.prodP(); if (!P) return;
    this.act('exportar', () => post(`/api/productions/${P.id}/final`, { decision: 'approve', note: 'exportado pelo estúdio' }), 'Exportado! Baixe os arquivos e publique pelo app da Shopee.');
  }
  newProduction() {
    this.setState({ pid: null, draftMode: true, files: [], creative: null, preview: null, opts: null, caption: null, draft: Object.assign({}, EMPTY_DRAFT) });
    this.setUI({ win: 'prod', tab: 'produto' });
    this.toast('Nova produção! A Nina está esperando o produto.');
  }
  pickProduction(pid) { this.setState({ pid, draftMode: false, creative: null, preview: null, opts: null, caption: null }, () => this.refresh()); this.closeWin(); }

  summaryText() {
    if (this.state.preview) return this.state.preview.summary;
    return 'Mãos da Bia mostrando o produto em ambiente neutro e limpo. Três cenas, sem fala.';
  }

  dialogFor(id) {
    const P = this.prodP(), st = this.stage(), idx = STAGES.indexOf(st);
    const status = this.statusOf(id);
    const ok = (label = 'Ok') => ({ label, cls: 'g-btn', act: () => this.closeWin() });
    const open = (tab, label, lime) => ({ label, cls: lime ? 'g-btn g-lime' : 'g-btn', act: () => this.openProd(tab) });
    const sc = this.scenes();
    const curScene = (kind) => { const k = sc.find((x) => x[kind] === 'gerando'); return k ? String(k.idx) : ''; };
    const est = P ? P.estimates : null;
    if (id === 'nina') {
      if (!P) return { line: 'Oi! Sou a Nina, cuido da preparação. Me passa o nome e as fotos oficiais do produto. A importação automática por link de marketplace ainda não existe, então as fotos vêm de você.', opts: [open('produto', 'Abrir ficha do produto', true), ok('Depois')] };
      if (P.status === 'awaiting_references') return { line: 'Conferi a ficha e falta material: ' + ((P.reason || '').slice(0, 160)) + ' Me manda fotos válidas?', opts: [open('produto', 'Ver o que falta', true), ok('Depois')] };
      if (st === 'exportado') return { line: 'Que vídeo bonito! Quando quiser, me traz o próximo produto.', opts: [{ label: 'Nova produção', cls: 'g-btn g-lime', act: () => this.newProduction() }, ok('Depois')] };
      return { line: 'Ficha conferida e entregue. Só uso o que está nas fotos e no que você confirmou: nada de características inventadas.', opts: [open('produto', 'Ver ficha'), ok('Valeu!')] };
    }
    if (id === 'theo') {
      if (idx < 1) return { line: 'Assim que a Nina fechar o produto, eu monto a direção. Tô rabiscando umas ideias aqui.', opts: [ok('Combinado')] };
      if (st === 'direcao') return status === 'work'
        ? { line: 'Escrevendo o roteiro das 3 cenas com a direção que você aprovou…', opts: [ok()] }
        : { line: 'Pensei assim: ' + this.summaryText() + ' Quer ajustar algo ou posso seguir?', opts: [open('direcao', 'Ver proposta e cenas', true), { label: 'Pode seguir assim', cls: 'g-btn', act: () => { this.loadOptions().then(() => this.approveDirection()); } }] };
      return { line: 'Direção aprovada: ' + this.summaryText(), opts: [open('direcao', 'Ver direção'), ok()] };
    }
    if (id === 'iris') {
      if (idx < 2) return { line: 'Eu crio as imagens de cada cena. Entro depois que o Theo fechar o plano. Enquanto isso, café!', opts: [ok('Bom café')] };
      if (st === 'gerar_img') return { line: 'Plano recebido! Criar as 3 imagens custa cerca de ' + cr(est.images.credits) + ' (estimativa). Usado neste vídeo: ' + P.credits.spent + '. Começo pela cena 1, que define o visual das outras. Posso?', opts: [{ label: 'Gerar imagens', cls: 'g-btn g-lime', act: () => this.startImages() }, open('imagens', 'Ver detalhes')] };
      if (status === 'work') return { line: 'Criando a imagem da cena ' + curScene('img') + '… Pode circular, eu aviso o Rui quando terminar.', opts: [open('imagens', 'Ver andamento'), ok()] };
      return { line: 'Imagens entregues para o Rui revisar. Se precisar refazer alguma, é só pedir por lá.', opts: [open('imagens', 'Ver imagens'), ok()] };
    }
    if (id === 'rui') {
      if (status === 'need') {
        const kind = this.revKind(); const n = sc.filter((x) => x[kind] === 'pronta').length;
        return { line: (kind === 'img' ? 'Conferi as imagens. ' : 'Conferi os takes. ') + n + (n === 1 ? ' está esperando' : ' estão esperando') + ' sua aprovação. Minha conferência ajuda, mas pode errar: confira com a foto de referência.', opts: [open('revisao', 'Revisar agora', true), ok('Depois')] };
      }
      return { line: 'Eu confiro se o produto continua igual às fotos. Quando algo chegar, eu chamo você.', opts: [open('revisao', 'Abrir revisão'), ok()] };
    }
    if (id === 'lia') {
      if (idx < 5) return { line: 'Eu dou movimento às imagens aprovadas. Ainda é cedo pra mim, então tô ajustando meus fones.', opts: [ok()] };
      if (st === 'gerar_vid') return { line: 'Imagens aprovadas! Animar as 3 cenas custa cerca de ' + cr(est.videos.credits) + ' (estimativa). Usado neste vídeo: ' + P.credits.spent + '. Posso animar?', opts: [{ label: 'Gerar movimentos', cls: 'g-btn g-lime', act: () => this.startVideos() }, open('videos', 'Ver detalhes')] };
      if (status === 'work') return { line: 'Animando a cena ' + curScene('vid') + '… cada take leva cerca de um minuto.', opts: [open('videos', 'Ver andamento'), ok()] };
      return { line: 'Takes entregues para o Rui.', opts: [open('videos', 'Ver takes'), ok()] };
    }
    if (st === 'montando') return { line: 'Montando seu vídeo… capa e legenda vêm junto.', opts: [ok()] };
    if (st === 'entrega') return { line: 'Vídeo montado! Uns 15 segundos, com capa e legenda. Dá uma olhada antes de exportar?', opts: [open('entrega', 'Ver resultado', true), ok('Depois')] };
    if (st === 'exportado') return { line: 'Exportado! Agora é só publicar pelo app da Shopee Vídeo. Bora para o próximo?', opts: [{ label: 'Nova produção', cls: 'g-btn g-lime', act: () => this.newProduction() }, open('entrega', 'Ver resultado')] };
    return { line: 'Eu monto o vídeo final. Enquanto isso, tô organizando as trilhas.', opts: [ok()] };
  }

  // ---------- view model: tudo que a UI precisa para desenhar ----------
  viewModel() {
    const s = this.state, ui = s.ui, P = this.prodP(), st = this.stage();
    const scale = this.fitZoom(), zoom = scale;
    const camX = GRID.W / 2, camY = GRID.H / 2;
    const idx = STAGES.indexOf(st);
    const near = ui.win ? null : this.nearestTarget();
    const statuses = {}; AGENTS.forEach((a) => { statuses[a.id] = this.statusOf(a.id); });
    const sc = this.scenes();
    const mode = s.S ? s.S.settings.mode : 'simulated';

    const chars = AGENTS.filter((a) => a.seat).map((a) => {
      const ast = s.agents[a.id]; const status = statuses[a.id];
      const seated = !ast.path.length && !ast.moving && ast.i === a.seat[0] && ast.j === a.seat[1];
      let anim = 'idle';
      if (ast.moving) anim = 'walk'; else if (st === 'exportado') anim = 'happy'; else if (status === 'work' && seated) anim = 'type'; else if (status === 'need') anim = 'wave';
      const isNear = near && near.type === 'agent' && near.id === a.id;
      const room = ROOMS.find((r) => r.agent === a.id);
      return {
        // sentado trabalhando: de costas, olhando o monitor; precisando de você ou livre: vira para a tela
        id: a.id, i: ast.i, j: ast.j, walking: !!ast.moving, seated, face: seated ? ast.dir : null,
        l: (ast.i + 0.5) * T - 8 * SC, t: (ast.j + 1) * T - (seated ? 28 : 24) * SC, z: 10 + ast.j, w: 16 * SC, h: 22 * SC,
        look: a.look, anim, need: status === 'need', work: status === 'work', near: !!isNear, status: this.roomStatus(room),
        name: a.name, role: a.role, room: room ? room.id : null,
        tagText: isNear ? a.name + ' · ' + a.role : a.name,
        aria: 'Falar com ' + a.name + ', ' + a.role + (status === 'need' ? ', precisa de você' : status === 'work' ? ', trabalhando' : ''),
        click: (e) => { e.stopPropagation(); this.goInteract({ type: 'agent', id: a.id }); },
      };
    });
    const ch = this.playerChair();
    const pl = { i: s.player.i, j: s.player.j, teleport: s.player.teleport, seated: !!ch && !s.player.path.length, face: ch ? ch.face : null,
      l: (s.player.i + 0.5) * T - 8 * SC, t: (s.player.j + 1) * T - (ch ? 28 : 24) * SC, z: 10 + s.player.j, w: 16 * SC, h: 22 * SC,
      anim: s.player.moving || s.player.path.length ? 'walk' : (st === 'exportado' ? 'happy' : 'idle'), dur: TICK / 1000 };
    const desks = AGENTS.map((a) => ({ id: a.id, work: statuses[a.id] === 'work', need: statuses[a.id] === 'need' }));
    const su = s.setup;
    const highlight = this.highlightOf(near);
    const dest = s.dest && s.player.path.length ? s.dest : null;
    const hot = (type, f, oh, label, aria, lime) => f && ({ key: type, x: f.x * T, y: f.y * T - oh, w: f.w * T, h: f.h * T + oh, label, aria, always: true, lime,
      click: (e) => { e.stopPropagation(); this.goInteract({ type }); } });

    // Atalho direto (decisão de produto: tudo a 1 clique, andar é opcional)
    const needA = AGENTS.find((a) => statuses[a.id] === 'need');
    const workA = AGENTS.find((a) => statuses[a.id] === 'work');
    const tabOf = (aid) => (TABS.find((t) => t.agent === aid) || {}).id;
    let nextLabel = '', nextLong = '', goNext = () => {};
    if (P && P.status === 'paused') { nextLabel = 'Ver pausa'; nextLong = 'Produção pausada: ' + (P.reason || ''); goNext = () => { this.setUI({ budgetHit: true, budgetDismissed: null }); this.openProd('revisao'); }; }
    else if (needA) { nextLabel = { nina: 'Abrir ficha', theo: 'Ver proposta', iris: 'Liberar imagens', rui: 'Revisar agora', lia: 'Liberar vídeos', beto: 'Ver vídeo' }[needA.id]; nextLong = needA.name + ' precisa de você.'; goNext = () => this.openProd(tabOf(needA.id)); }
    else if (workA) { nextLabel = 'Acompanhar'; nextLong = workA.name + ' está trabalhando. Você pode circular.'; goNext = () => this.openProd(tabOf(workA.id)); }
    else if (st === 'exportado') { nextLong = 'Tudo pronto. Comece outra produção quando quiser.'; nextLabel = 'Nova produção'; goNext = () => this.newProduction(); }

    const roster = AGENTS.map((a) => {
      const rs = statuses[a.id];
      return { id: a.id, name: a.name, look: a.look, bg: rs === 'need' ? '#F2FBD9' : 'transparent', dot: rs === 'need' ? '#D5F45B' : rs === 'work' ? '#8ED8F8' : '#E7E1D6', sym: rs === 'need' ? '!' : rs === 'work' ? '…' : '',
        aria: a.name + ', ' + a.role + (rs === 'need' ? ': precisa de você' : rs === 'work' ? ': trabalhando' : ': livre') + '. Abrir ' + a.role,
        go: () => this.openProd(tabOf(a.id)) };
    });

    let dlg = null;
    if (ui.win === 'dialog' && ui.who) {
      const a = AGM[ui.who]; const talk = this.dialogFor(ui.who); const room = ROOMS.find((r) => r.agent === a.id);
      const menu = [
        { label: 'Ver trabalho', cls: 'g-btn g-lime', act: () => this.openRoomWork(room.id) },
        { label: 'Conversar', cls: 'g-btn', act: () => this.setUI({ dlgTalk: true }) },
        { label: 'Treinar agente', cls: 'g-btn', act: () => this.setUI({ win: 'training', trainAgent: a.id }) },
        ...(a.id === 'lia' || a.id === 'beto' ? [{ label: 'Trilhas', cls: 'g-btn', act: () => this.setUI({ win: 'music' }) }] : []),
      ];
      const d = ui.dlgTalk ? talk : { line: room.hint + '. Agora: ' + this.roomStatus(room) + '.', opts: menu };
      dlg = { name: a.name, role: a.role, look: a.look, line: d.line, opts: d.opts, bg: a.look.shirt, anim: statuses[a.id] === 'need' ? 'wave' : 'idle' };
    }

    let chat = null;
    if (ui.win === 'chat' && ui.who && AGM[ui.who]) {
      const a = AGM[ui.who]; const room = ROOMS.find((r) => r.agent === a.id);
      chat = { agentId: a.id, name: a.name, role: a.role, intro: this.dialogFor(a.id).line, stage: st, status: statuses[a.id],
        statusText: room ? this.roomStatus(room) : '', pid: P ? s.pid : null,
        needs: AGENTS.filter((b) => statuses[b.id] === 'need').map((b) => b.id).join(','),
        actions: [
          ...(room ? [{ label: 'Ver trabalho', act: () => this.openRoomWork(room.id) }] : []),
          { label: 'Treinar', act: () => this.setUI({ win: 'training', trainAgent: a.id }) },
          ...(a.id === 'lia' || a.id === 'beto' ? [{ label: 'Trilhas', act: () => this.setUI({ win: 'music' }) }] : []),
        ],
        onClose: () => this.closeWin() };
    }

    const doneAt = { produto: 1, direcao: 2, imagens: 4, revisao: 8, videos: 7, entrega: 10 };
    const tabs = TABS.map((tb) => {
      const a = AGM[tb.agent]; const ts = statuses[tb.agent];
      const done = idx >= doneAt[tb.id];
      let dot = '#E7E1D6', sym = '', ink = '#17234B', stTxt = '';
      if (ts === 'need') { dot = '#D5F45B'; sym = '!'; stTxt = ', precisa de você'; }
      else if (ts === 'work') { dot = '#8ED8F8'; sym = '…'; stTxt = ', em andamento'; }
      else if (done) { dot = '#2D7A3E'; sym = '✓'; ink = '#fff'; stTxt = ', concluída'; }
      return { id: tb.id, label: tb.label, look: a.look, bg: a.look.shirt, sel: ui.tab === tb.id, dot, sym, dotInk: ink, aria: tb.label + ' com ' + a.name + stTxt, pick: () => this.openProd(tb.id) };
    });

    // --- créditos ---
    const credits = P ? P.credits : { spent: 0, budget: 0 };
    const est = P ? P.estimates : null;

    // --- produto ---
    const d = s.draft;
    const refs = P ? ((P.sheet && P.sheet.references) || []).filter((r) => r.url && !/\.mp4/i.test(r.url)) : [];
    const product = {
      editing: !P || P.status === 'awaiting_references', created: !!P, refs, issues: P && P.sheet ? P.sheet.issues : [], unknown: P && P.sheet ? P.sheet.unknown_fields : [],
      name: P ? P.product.name : d.name, variant: P ? P.product.variant : '', link: P ? P.product.link : '',
      draft: d, setDraft: (k) => (e) => this.setDraft({ [k]: e.target.value }), files: s.files.map((f, k) => ({ ...f, k,
        setRole: (e) => { const fs = s.files.slice(); fs[k] = Object.assign({}, fs[k], { role: e.target.value }); this.setState({ files: fs }); },
        remove: () => this.setState({ files: s.files.filter((_, q) => q !== k) }) })), roles: ROLES,
      addFiles: (e) => { this.addFiles(Array.from(e.target.files || [])); e.target.value = ''; },
      confirm: () => this.confirmProduct(), resend: () => this.resendRefs(), missing: !P ? this.draftErrors() : [],
      fullEstimate: est ? est.images.credits + est.videos.credits : null,
    };

    // --- direção ---
    const o = s.opts, c = s.creative;
    const dir = { ready: !!(o && c), summary: this.summaryText(), locked: idx < 1, done: idx > 1 || (P && P.creative && st !== 'direcao'), working: st === 'direcao' && P && P.creative,
      canApprove: st === 'direcao' && !(P && P.creative && P.running) && !!c };
    if (o && c) {
      dir.formats = [['product_only', false, false], ['hands_only', true, false], ['presenter', true, true]].map(([id, hand, person]) => ({
        id, hand, person, label: o.presentations[id].label, desc: o.presentations[id].desc, sel: c.presentation === id,
        disabled: id === 'presenter' && !o.presenter_available, pick: () => this.setCreative({ presentation: id }) }));
      dir.reqs = splitRequests(c.details_text).map((text, k, arr) => ({ text, remove: () => this.setCreative({ details_text: arr.filter((_, q) => q !== k).join('; ') }) }));
      dir.basis = o.basis;
      dir.rows = summaryRows(o.presentations, c);
    }
    dir.scenes = s.preview ? s.preview.scenes : [];
    dir.warnings = s.preview ? s.preview.warnings : [];
    dir.reqText = s.reqText; dir.onReq = (e) => this.setState({ reqText: e.target.value });
    dir.addReq = () => { const v = (s.reqText || '').trim(); if (!v || !c) return; this.setCreative({ details_text: joinRequests(c.details_text, v) }); this.setState({ reqText: '' }); this.toast('Theo: anotado! Vou aplicar nas cenas.'); };
    dir.approve = () => this.approveDirection(); dir.load = () => this.loadOptions();

    // --- imagens / vídeos / revisão ---
    const stLabel = { none: ['Aguardando', '#E7E1D6'], fila: ['Na fila', '#E7E1D6'], gerando: ['Criando…', '#8ED8F8'], pronta: ['Para revisar', '#D5F45B'], aprovada: ['Aprovada', '#BDE5B0'], falhou: ['Não saiu', '#FFE1DC'] };
    const slot = (key) => sc.map((x) => {
      const lb = stLabel[x[key]]; const att = key === 'img' ? x.image : x.video;
      const waitScene1 = key === 'img' && x.img === 'fila' && x.idx > 1;
      return { k: x.idx, n: x.idx, status: x[key], label: lb[0], bg: lb[1], url: att && att.url, isVideo: key === 'vid',
        sub: waitScene1 ? 'Espera a cena 1 ser aprovada' : x[key] === 'gerando' ? (key === 'img' ? 'Criando a imagem' : 'Animando') : x[key] === 'pronta' ? 'Com o Rui' : x[key] === 'aprovada' ? 'Aprovada' : '' };
    });
    const kind = this.revKind();
    const sel = sc.find((x) => x.idx === ui.revSel) || sc[0];
    const revScenes = sc.map((x) => { const lb = stLabel[x[kind]]; return { k: x.idx, n: x.idx, label: x.blocked ? 'Bloqueada' : lb[0], bg: x.blocked ? '#FFE1DC' : lb[1], sel: sel && sel.idx === x.idx, pick: () => this.setUI({ revSel: x.idx, adjust: false, issues: [], adjText: '', revView: 'scene' }) }; });
    let rev = null;
    if (sel) {
      const att = kind === 'img' ? sel.image : sel.video;
      const auto = att && att.reviews ? att.reviews.filter((r) => r.reviewer.startsWith('auto:')).slice(-1)[0] : null;
      let chk = { title: 'Conferência do Rui', text: 'Aguardando material.', bg: '#fff' };
      if (auto) {
        const issues = (auto.issues || []).join(' ');
        chk = auto.decision === 'approved' ? { title: 'Parece certo', text: 'Produto, cor e formato parecem bater com a referência. Confira você também: minha conferência pode errar.', bg: '#E3F5DC' }
          : auto.decision === 'rejected' ? { title: 'Encontrei um problema', text: issues || 'Algo não bate com a referência.', bg: '#FFE1DC' }
          : { title: 'Inconclusivo', text: (issues ? issues + ' ' : '') + (mode === 'simulated' ? 'Modo DEMO: não houve análise visual de verdade.' : 'Não tenho certeza. Compare com a referência.'), bg: '#FFE7C2' };
      } else if (sel[kind] === 'gerando' || sel[kind] === 'fila') chk = { title: 'Conferência do Rui', text: 'Vou conferir assim que ficar pronto.', bg: '#fff' };
      const tries = kind === 'img' ? sel.imgTries : sel.vidTries;
      const maxT = est ? (kind === 'img' ? est.max_tries.image : est.max_tries.video) : 3;
      const ref = refs[0];
      const view = ui.revView;
      rev = {
        n: sel.idx, title: (kind === 'img' ? 'Imagem' : 'Take') + ' da cena ' + sel.idx + ': ' + sel.title, sub: sel.motion,
        canAct: sel[kind] === 'pronta' && !!(att && att.url) && !(P && P.running),
        failed: sel[kind] === 'falhou', failBilling: /error code: 402|prepayment credits|credits are depleted/i.test((att && att.error) || ''), failText: (att && att.error) || 'A geração não terminou e as tentativas desta cena acabaram.',
        canRetry: sel[kind] === 'falhou' && !(P && P.running), limitHit: tries >= maxT, nextTry: tries + 1, maxTries: maxT, tries,
        cost: est ? (kind === 'img' ? est.redo_image.credits : est.redo_video.credits) : 0, who: kind === 'img' ? 'a Iris' : 'a Lia', what: kind === 'img' ? 'imagem' : 'animação',
        chk, criteria: sel.criteria,
        media: { view, refUrl: ref && ref.url, imgUrl: sel.image && sel.image.url, vidUrl: sel.video && sel.video.url,
          label: view === 'ref' ? 'Referência · sua foto' : view === 'video' ? 'Conteúdo gerado · take v' + Math.max(tries, 1) : 'Conteúdo gerado · imagem',
          busy: (sel[kind] === 'gerando' || sel[kind] === 'fila') && view !== 'ref', busyText: kind === 'img' ? 'Criando a imagem da cena ' + sel.idx : 'Animando a cena ' + sel.idx },
        viewTabs: [{ id: 'ref', label: 'Referência', off: !ref }, { id: 'scene', label: 'Imagem', off: !(sel.image && sel.image.url) }, { id: 'video', label: 'Vídeo', off: !(sel.video && sel.video.url) }]
          .map((vt) => ({ ...vt, sel: view === vt.id, pick: () => this.setUI({ revView: vt.id }) })),
      };
    }
    const issueList = kind === 'img' ? ['Produto diferente', 'Cor incorreta', 'Falta um detalhe (ex.: acessório, tampa)', 'Mãos estranhas', 'Cenário inconsistente'] : ['Movimento artificial', 'Produto deforma', 'Mãos estranhas', 'Cenário muda', 'Objeto novo aparece'];
    const issues = issueList.map((lb) => ({ label: lb, sel: ui.issues.indexOf(lb) >= 0, pick: () => { const arr = ui.issues.indexOf(lb) >= 0 ? ui.issues.filter((x) => x !== lb) : ui.issues.concat(lb); this.setUI({ issues: arr }); } }));

    // --- personalização (inalterada) ---
    const ctabs = [{ id: 'personagem', label: 'Personagem' }, { id: 'mesa', label: 'Mesa e cadeira' }, { id: 'computador', label: 'Computador' }, { id: 'decoracao', label: 'Decoração' }]
      .map((x) => ({ ...x, sel: ui.ctab === x.id, pick: () => this.setUI({ ctab: x.id }) }));
    const L = s.look;
    const setLook = (k, v) => () => { const n = Object.assign({}, s.look); n[k] = v; this.setState({ look: n }); };
    const setSet = (k, v) => () => { const n = Object.assign({}, s.setup); n[k] = v; this.setState({ setup: n }); };
    const sw = (label, color, isSel, pick) => ({ type: 'swatch', label, color, sel: isSel, pick });
    const chip = (label, isSel, pick) => ({ type: 'chip', label, sel: isSel, pick });
    let cgroups = [];
    if (ui.ctab === 'personagem') cgroups = [
      { label: 'Cor do personagem', opts: [['Lima', '#D5F45B'], ['Céu', '#8ED8F8'], ['Rosa', '#FF8FC0'], ['Laranja', '#FF9A3D'], ['Amarelo', '#F5C542'], ['Verde-água', '#4FD0BF'], ['Lilás', '#A88BF0'], ['Azul', '#4A7BF0'], ['Creme', '#FFF8EC']].map((x) => sw(x[0], x[1], L.shirt === x[1], setLook('shirt', x[1]))) },
      { label: 'Acessório', opts: [['Nenhum', 'nenhum'], ['Óculos', 'oculos'], ['Boné', 'bone'], ['Fones', 'fones'], ['Gorro', 'boina'], ['Broto', 'broto']].map((x) => chip(x[0], L.acc === x[1], setLook('acc', x[1]))) },
    ];
    else if (ui.ctab === 'mesa') cgroups = [
      { label: 'Mesa', opts: [['Madeira', 'madeira'], ['Branca', 'branca'], ['Gamer', 'gamer']].map((x) => chip(x[0], su.desk === x[1], setSet('desk', x[1]))) },
      { label: 'Cadeira', opts: [['Clássica', 'classica'], ['Gamer', 'gamer'], ['Bola de pilates', 'bola']].map((x) => chip(x[0], su.chair === x[1], setSet('chair', x[1]))) },
    ];
    else if (ui.ctab === 'computador') cgroups = [{ label: 'Equipamento', opts: [['Notebook', 'notebook'], ['Monitor duplo', 'duplo'], ['PC retrô', 'retro']].map((x) => chip(x[0], su.pc === x[1], setSet('pc', x[1]))) }];
    else cgroups = [{ label: 'Na mesa e em volta', opts: [['Planta', 'planta'], ['Gato dormindo', 'gato'], ['Luminária', 'luminaria'], ['Caneca', 'caneca'], ['Tapete', 'tapete']].map((x) => chip(x[0], !!su[x[1]], setSet(x[1], !su[x[1]]))) }];

    const needTab = TABS.find((tb) => statuses[tb.agent] === 'need');
    const pilotMode = P && P.autonomy && P.autonomy !== 'classico' ? P.autonomy : s.pilot;
    const pilot = { mode: pilotMode, label: (PILOT[pilotMode] || PILOT.manual).label, hasProd: !!P, set: (m) => this.setPilot(m) };
    const rivalA = AGENTS.find((a) => statuses[a.id] === 'idle') || AGM.rui;
    const games = { rival: { name: rivalA.name, role: rivalA.role, look: rivalA.look },
      needYou: needA || (P && P.status === 'paused') ? { text: needA ? needA.name + ' precisa de você.' : 'A produção pausou.', label: nextLabel || 'Ver', go: goNext } : null,
      working: workA ? workA.name + ' está trabalhando; o aviso aparece aqui quando precisarem de você.' : '' };
    const productions = s.S ? s.S.productions.map((x) => ({ ...x, current: !s.draftMode && x.id === s.pid, open: () => this.pickProduction(x.id) })) : [];

    // --- shell: fluxo da missão e fila de decisões (derivados do mesmo estado real) ---
    const rsOf = (id) => { const r = ROOMS.find((x) => x.agent === id); return r ? this.roomStatus(r) : ''; };
    const paused = !!(P && P.status === 'paused');
    const pipeline = buildPipeline({ idx, statuses, hasProd: !!P, paused, detail: {
      objetivo: P ? P.product.name : '', orquestrador: paused ? 'Pausada: ' + (P.reason || '') : P ? STAGE_LABELS[st] : '',
      roteiro: rsOf(idx < 1 ? 'nina' : 'theo'), criativo: rsOf('iris'), video: rsOf('lia'), revisao: rsOf('rui'), entrega: rsOf('beto') } });
    const attn = P ? attention({ paused, pauseReason: P.reason, rooms: ROOMS.filter((r) => r.agent && statuses[r.agent] === 'need').map((r) => ({ id: r.id, name: r.name, who: AGM[r.agent].name,
      status: this.roomStatus(r), need: true, look: AGM[r.agent].look, work: () => this.openRoomWork(r.id) })) }) : [];

    return {
      // shell
      view: s.view, setView: (id) => { if (s.ui.win === 'dialog') this.closeWin(); this.setState({ view: id }); }, shell: true,
      pipeline, attn, statuses: P ? statuses : { ...statuses, nina: 'idle' }, hasProd: !!P, openStep: (tab) => this.openProd(tab),
      // mundo
      scale, zoom, camX, camY, vw: s.vw, vh: s.vh, setup: su, desks, highlight, dest,
      openTour: () => this.openTour(), tourOpen: !!s.onb,
      openAbout: () => { this.dismissTut(); this.setUI({ win: 'about' }); },
      cenario: s.cenario, setCenario: (t) => this.setState({ cenario: normalizeTheme(t) }),
      openPrefs: (tab) => { this.dismissTut(); this.setUI({ win: tab || 'prefs' }); },
      nearAlt: ch && near && near.type !== 'stand' ? { label: 'Levantar', go: () => this.standUp() } : null,
      openSectors: () => { this.dismissTut(); this.setUI({ win: 'sectors' }); },
      openMusic: () => this.setUI({ win: 'music' }), trainAgent: ui.trainAgent, team: AGENTS, openTraining: (id) => this.setUI({ win: 'training', trainAgent: id, learn: null }),
      learn: ui.learn || null, closeLearn: () => this.setUI({ learn: null }),
      afterMusic: (body) => { const P2 = this.prodP(); if (P2 && body.track_id) this.setUI({ learn: { agent: 'lia', name: 'a Lia', decision: 'approve', note: 'Preferir trilhas como esta', pid: P2.id } }); this.refresh(); },
      rooms: ROOMS.map((r) => {
        const a = r.agent ? AGM[r.agent] : null;
        const status = this.roomStatus(r);
        const placed = placedRoom(r);
        return { id: r.id, name: r.name, hint: r.hint, agent: r.agent || null, who: a ? a.name : '', role: a ? a.role : '', look: a ? a.look : s.look, status, need: a ? statuses[a.id] === 'need' : false, placed,
          x: placed ? ((r.x0 + r.x1 + 1) / 2) * T : 0, y: placed ? r.y0 * T + 1 : 0,
          click: (e) => { e.stopPropagation(); this.goRoom(r.id); },
          go: () => { if (!this.goRoom(r.id) && !placed) this.toast(r.name + ' ainda não está no mapa novo. Use o botão Abrir.'); this.closeWin(); },
          work: () => { this.goRoom(r.id); this.openRoomWork(r.id); } };
      }),
      hots: [
        ...ROOMS.filter((r) => r.agent && placedRoom(r) && r.desk).map((r) => ({ key: 'm' + r.id, x: r.desk.x * T, y: r.desk.y * T - 14 * SC, w: r.desk.w * T, h: r.desk.h * T + 14 * SC, label: 'Monitor',
          aria: 'Usar o monitor de ' + r.name, click: (e) => { e.stopPropagation(); this.goInteract({ type: 'monitor', room: r.id }); } })),
        hot('mine', (ROOMS.find((r) => r.id === 'meu' && placedRoom(r)) || {}).desk, 14 * SC, 'Meu setup', 'Meu setup: personalizar móveis e equipamentos', true),
        hot('board', HOT_FURNITURE.board, 22, 'Produções', 'Quadro de produções'),
        hot('coffee', HOT_FURNITURE.coffee, 16, 'Café', 'Café'),
        hot('games', HOT_FURNITURE.games, 4, 'Jogos', 'Mesa de jogos: jogo da velha e damas'),
        hot('music', HOT_FURNITURE.music, 20, 'Trilhas', 'Trilhas da Lia: biblioteca musical'),
      ].filter(Boolean),
      chars, pl, look: s.look, agentDur: AGENT_EVERY * TICK / 1000,
      onWorldClick: this.onWorldClick,
      hoverAt: (i, j) => this.hoverAt(i, j),
      goBoard: (e) => { e.stopPropagation(); this.goInteract({ type: 'board' }); },
      goCoffee: (e) => { e.stopPropagation(); this.goInteract({ type: 'coffee' }); },
      goMine: (e) => { e.stopPropagation(); this.goInteract({ type: 'mine' }); },
      goGames: (e) => { e.stopPropagation(); this.goInteract({ type: 'games' }); }, games, pilot,
      account: s.account, logout: () => this.logout(), openAccount: () => { this.dismissTut(); this.setUI({ win: 'account' }); },
      wallet: s.S ? s.S.credits : null, openCredits: () => { this.dismissTut(); this.setUI({ win: 'credits' }); },
      openProduction: (id) => { this.setState({ pid: id, draftMode: false }); this.closeWin(); },
      openGames: () => { this.dismissTut(); this.setUI({ win: 'games' }); }, openPilot: () => { this.dismissTut(); this.setUI({ win: 'pilot' }); },
      celebrate: st === 'exportado', confetti: CONFETTI,
      // HUD
      mode, conn: s.conn, connErr: s.err, busy: s.busy,
      prodName: P ? P.product.name : (s.draft.name || 'Nova produção'), stageLabel: P && P.status === 'paused' ? 'Pausada' : STAGE_LABELS[st],
      nextLabel, nextLong: nextLong || 'Nada pendente agora.', goNext,
      // Cabeçalho: só um indicador discreto do saldo; o destaque é o produto e as cenas. Nunca "X de Y créditos".
      spentText: balanceLabel(s.S ? s.S.credits : null) || usedLabel(credits), usedText: usedLabel(credits),
      balanceText: balanceLabel(s.S ? s.S.credits : null), credits, confirmation: P ? P.confirmation : null,
      openBoard: () => { this.dismissTut(); this.setUI({ win: 'board' }); },      toggleHelp: () => this.setUI({ tut: !ui.tut }), roster,
      near, promptLabel: this.labelFor(near), useNear: () => { if (near) this.doAction(near); },
      toast: ui.toast ? ui.toast.text : '',
      // janelas
      win: ui.win, showTut: ui.tut,
      tutGo: () => { this.dismissTut(); this.openProd(needTab ? needTab.id : 'produto'); },
      tutClose: () => { this.dismissTut(); if (this.rootEl) this.rootEl.focus({ preventScroll: true }); },
      closeWin: () => this.closeWin(), dlg, chat,
      boardOpenProd: () => this.openProd(needTab ? needTab.id : 'produto'), productions,
      newProd: () => this.newProduction(), newProdHint: 'Cada produção guarda fotos, cenas, versões e gastos separados.',
      ctabs, cgroups, tabs, tab: ui.tab, idx, stage: st, P,
      product, dir, dirSub: ui.dirSub, toDir: () => this.setUI({ dirSub: 'dir' }), toCenas: () => this.setUI({ dirSub: 'cenas' }),
      // etapas pagas
      est, imgGate: st === 'gerar_img', imgLocked: idx < 2, imgProgress: idx >= 3 || (P && P.go_ahead !== 'none' && idx >= 2), imgSlots: slot('img'),
      startImages: () => this.startImages(), vidGate: st === 'gerar_vid', vidLocked: idx < 5, vidProgress: idx >= 6, vidSlots: slot('vid'), startVideos: () => this.startVideos(),
      // revisão
      revLocked: !sc.some((x) => x.img !== 'none' && x.img !== 'fila'), revKindLabel: kind === 'img' ? 'Imagens' : 'Takes', revScenes, rev, ruiLook: AGM.rui.look,
      adjusting: ui.adjust, issues, adjText: ui.adjText, onAdjText: (e) => this.setUI({ adjText: e.target.value }), noIssue: ui.issues.length === 0 && !(ui.adjText || '').trim(),
      openAdjust: () => this.setUI({ adjust: true }), closeAdjust: () => this.setUI({ adjust: false, issues: [], adjText: '' }),
      approveCur: () => rev && this.approveScene(rev.n), retryCur: () => rev && this.retryScene(rev.n),sendAdjust: () => this.sendAdjust(),
      budgetHit: ui.budgetHit || (P && P.status === 'paused' && ui.budgetDismissed !== P.reason), pauseReason: P && P.status === 'paused' ? P.reason : '',
      confirmExtra: ui.confirmExtra || null, cancelExtra: () => this.setUI({ confirmExtra: null }),
      noBalance: ui.noBalance || null,
      // "Manter meu vídeo como está": fecha o ajuste sem mudar nada; cenas, versões e aprovações continuam.
      keepAsIs: () => this.setUI({ noBalance: null, confirmExtra: null, adjust: false, issues: [], adjText: '' }),
      dismissBudget: () => this.setUI({ budgetHit: false, confirmCap: null, budgetDismissed: P && P.status === 'paused' ? P.reason : null }),
      confirmCap: ui.confirmCap || null, confirmCapUsd: ui.confirmCapUsd || 0, cancelCap: () => this.setUI({ confirmCap: null }),
      pause: this.pauseInfo(), raiseMonthly: (n) => this.raiseMonthly(n), resumeOnly: () => this.resumeOnly(),
      cancelProd: () => this.cancelProd(), confirmCancel: !!ui.confirmCancel, keepProd: () => this.setUI({ confirmCancel: false }),
      // entrega
      entLocked: idx < 8, entBuilding: st === 'montando', delivery: P ? P.delivery : {},
      edit: P ? P.edit : null, editOptions: s.S ? s.S.settings.edit_styles : null,
      setEdit: (style, music) => this.setEdit(style, music), caption: s.caption || '', onCaption: (e) => this.setState({ caption: e.target.value }),
      exported: st === 'exportado', exportVideo: () => this.exportVideo(),
    };
  }

  render() {
    if (this.state.authState === 'checking') return <div className="dotsbg" style={{ position: 'fixed', inset: 0 }} aria-busy="true" />;
    if (this.state.authState !== 'in') {
      if (!this.state.resetToken && !this.state.entry) {
        return <React.Suspense fallback={<div style={{ position: 'fixed', inset: 0, background: '#FBF7EE' }} />}><Landing signupOpen={this.state.signup !== 'closed'} onEnter={(entry) => this.setState({ entry })} /></React.Suspense>;
      }
      return <AuthScreen key={this.state.entry} signup={this.state.signup} resetToken={this.state.resetToken} initialMode={this.state.entry} onBack={() => this.setState({ entry: null })}
        onDone={() => this.setState({ resetToken: null, entry: null }, () => this.checkSession())} />;
    }
    const v = this.viewModel();
    return (
      <Shell v={v} rootRef={this.setRoot} stageRef={this.setStage} onKeyDown={this.onKey} onKeyUp={this.onKeyUp} onBlur={this.onBlur}>
        {v.view === 'central' && <Central v={v} />}
        {v.view === 'missao' && <MissionView v={v} />}
        {v.view === 'equipe' && <TeamView v={v} />}
        {v.view === 'escritorio' && (<>
          <React.Suspense fallback={null}><WorldPhaser v={v} /></React.Suspense>
          <Hud v={v} />
          {v.showTut && !v.tourOpen && <Tutorial v={v} />}
        </>)}
        {v.win === 'dialog' && v.dlg && <DialogWindow v={v} />}
        {v.win === 'chat' && v.chat && <React.Suspense fallback={null}><AgentChat {...v.chat} /></React.Suspense>}
        {v.win === 'board' && <BoardWindow v={v} />}
        {v.win === 'sectors' && <SectorsWindow v={v} />}
        {v.win === 'training' && <TrainingWindow key={v.trainAgent} v={v} />}
        {v.win === 'music' && <MusicWindow v={v} />}
        {v.learn && <LearnPanel key={JSON.stringify(v.learn)} v={v} />}
        {v.win === 'custom' && <CustomWindow v={v} />}
        {v.win === 'prod' && <ProdWindow v={v} />}
        {v.win === 'games' && <GamesWindow v={v} />}
        {PREF_WINS.includes(v.win) && <React.Suspense fallback={null}><Preferences v={v} /></React.Suspense>}
        {this.state.onb && (
          <TourBoundary key={this.state.onb.key} onFail={this.tourDone}><React.Suspense fallback={null}>
            <Onboarding key={this.state.onb.key} start={this.state.onb.start} api={this.tourApi}
              ctx={{ world: true, walletExempt: !!(v.wallet && v.wallet.exempt), pilotLabel: v.pilot.label }} onClosed={this.tourDone} />
          </React.Suspense></TourBoundary>
        )}
      </Shell>
    );
  }
}
