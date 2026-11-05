import React from 'react';
import {
  Bell, Bot, Building2, CheckCheck, ChevronDown, CircleDollarSign, GraduationCap, Home, Info, LogOut, PanelLeft, Pause,
  Plus, Search, Settings, Shield, Sparkles, UserRound, UsersRound, Workflow,
} from 'lucide-react';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import Icon from './icons.jsx';
import { Avatar, AGENT_STATE } from './Central.jsx';
import compactLogo from '../assets/brand/icone-app-preto.svg';
import wordmark from '../assets/brand/wordmark-preto-laranja.svg';
import './shell.css';

// Layout (padrão de escritório virtual): trilho de ícones à esquerda, painel colapsável com o contexto do estúdio
// (próxima ação, equipe, missões) e a área de trabalho num cartão arredondado à direita.
export const VIEWS = [
  { id: 'central', label: 'Central', title: 'Central', icon: Home },
  { id: 'missao', label: 'Missões', title: 'Missão', icon: Workflow },
  { id: 'equipe', label: 'Agentes', title: 'Equipe', icon: UsersRound },
  { id: 'escritorio', label: 'Escritório', title: 'Escritório virtual', icon: Building2 },
];

const LS = {
  get(k, d) { try { const x = localStorage.getItem(k); return x == null ? d : JSON.parse(x); } catch { return d; } },
  set(k, x) { try { localStorage.setItem(k, JSON.stringify(x)); } catch { /* sem armazenamento */ } },
};

function RailTip({ label, children, kbd }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side="right" sideOffset={8}>{label}{kbd && <kbd className="pv-tip-kbd">{kbd}</kbd>}</TooltipContent>
    </Tooltip>
  );
}

// Menu do estúdio (logo no topo do trilho)
function WorkspaceMenu({ v, newMission }) {
  const ws = v.account?.workspace?.name || 'Kiroo';
  return (
    <DropdownMenu>
      <RailTip label={ws}>
        <DropdownMenuTrigger asChild>
          <button type="button" className="pv-ws" aria-label={`Menu do estúdio ${ws}`}>
            <img src={compactLogo} alt="" />
            <span className="pv-ws-caret" aria-hidden="true"><ChevronDown size={10} strokeWidth={3} /></span>
          </button>
        </DropdownMenuTrigger>
      </RailTip>
      <DropdownMenuContent side="right" align="start" sideOffset={10} className="pv-menu">
        <div className="pv-menu-cta"><button type="button" className="pv-cta" onClick={newMission}><Plus size={16} aria-hidden="true" />Nova missão</button></div>
        <DropdownMenuItem onSelect={() => v.openPrefs('prefs')}><Settings />Preferências</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => v.openPrefs('pilot')}><Bot />Piloto: {v.pilot.label}</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => v.openPrefs('credits')}><CircleDollarSign />Créditos e extrato</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => v.openPrefs('about')}><Info />Sobre o Kiroo</DropdownMenuItem>
        <DropdownMenuItem onSelect={v.openTour}><GraduationCap />Rever tutorial</DropdownMenuItem>
        {v.account?.admin && (<>
          <DropdownMenuSeparator />
          <DropdownMenuLabel>Administrador</DropdownMenuLabel>
          <DropdownMenuItem asChild><a href="/painel"><Shield />Painel do administrador</a></DropdownMenuItem>
        </>)}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={v.logout}><LogOut />Sair</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

// Atividade: o que precisa de você. Lido = guardado neste navegador; o ponto azul some, o item continua até ser resolvido.
function Activity({ v }) {
  const [seen, setSeen] = React.useState(() => LS.get('bc.seen', []));
  const [open, setOpen] = React.useState(false);
  const key = (a) => `${a.id}:${a.text}`;
  const items = v.attn.map((a) => ({ ...a, unread: !seen.includes(key(a)) }));
  const unread = items.filter((a) => a.unread).length;
  const markAll = () => { const s = items.map(key); setSeen(s); LS.set('bc.seen', s); };
  const go = (a) => {
    const s = Array.from(new Set([...seen, key(a)])); setSeen(s); LS.set('bc.seen', s); setOpen(false);
    if (a.room) a.room.work(); else v.setView('missao');
  };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <RailTip label="Atividade">
        <PopoverTrigger asChild>
          <button type="button" className="pv-rail-btn" aria-label={`Atividade${unread ? `, ${unread} não lidas` : ''}`} data-active={open || undefined}>
            <Bell size={20} strokeWidth={1.8} aria-hidden="true" />
            {unread > 0 && <span className="pv-badge" aria-hidden="true">{unread}</span>}
          </button>
        </PopoverTrigger>
      </RailTip>
      <PopoverContent side="right" align="start" sideOffset={10} className="pv-activity" onOpenAutoFocus={(e) => e.preventDefault()}>
        <header><h2>Atividade</h2>
          <RailTip label="Marcar tudo como lido"><button type="button" className="pv-icon-btn" onClick={markAll} aria-label="Marcar tudo como lido" disabled={!unread}><CheckCheck size={17} aria-hidden="true" /></button></RailTip>
        </header>
        {items.length === 0 && <div className="pv-activity-empty"><span className="pv-act-ic" data-k="ok"><Sparkles size={18} aria-hidden="true" /></span><strong>Tudo em dia</strong><span>Quando alguém da equipe precisar de você, aparece aqui.</span></div>}
        <ul>
          {items.map((a) => (
            <li key={a.id}>
              <button type="button" onClick={() => go(a)}>
                <span className="pv-act-ic" data-k={a.kind}>{a.kind === 'pause' ? <Pause size={18} aria-hidden="true" /> : <Bell size={18} aria-hidden="true" />}</span>
                <span className="pv-grow"><strong>{a.kind === 'pause' ? a.title : `${a.who} precisa de você`}</strong><span>{a.kind === 'pause' ? a.text : `${a.title}: ${a.text}`}</span></span>
                {a.unread && <i className="pv-dot" aria-label="não lida" />}
              </button>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

function Rail({ v, onSearch, newMission }) {
  return (
    <nav className="pv-rail" aria-label="Navegação principal">
      <WorkspaceMenu v={v} newMission={newMission} />
      <div className="pv-rail-search">
        <RailTip label="Buscar" kbd="Ctrl K"><button type="button" className="pv-rail-btn" onClick={onSearch} aria-label="Buscar (Ctrl K)"><Search size={20} strokeWidth={1.8} aria-hidden="true" /></button></RailTip>
        <span className="pv-rail-kbd" aria-hidden="true"><kbd>Ctrl</kbd><kbd>K</kbd></span>
      </div>
      <span className="pv-rail-sep" aria-hidden="true" />
      {VIEWS.map((x) => (
        <RailTip key={x.id} label={x.label}>
          <button type="button" className="pv-rail-btn" data-tour={x.id === 'escritorio' ? 'office-rail' : undefined} data-active={v.view === x.id || undefined} aria-current={v.view === x.id ? 'page' : undefined}
            aria-label={x.label + (x.id === 'central' && v.attn.length ? `, ${v.attn.length} pendências` : '')} onClick={() => v.setView(x.id)}>
            <x.icon size={20} strokeWidth={1.8} aria-hidden="true" />
          </button>
        </RailTip>
      ))}
      <Activity v={v} />
      <span className="pv-rail-fill" />
      <RailTip label="Preferências"><button type="button" className="pv-rail-btn" onClick={() => v.openPrefs('prefs')} aria-label="Preferências"><Settings size={20} strokeWidth={1.8} aria-hidden="true" /></button></RailTip>
    </nav>
  );
}

// Painel: estúdio, missão aberta, próxima ação, busca e equipe com estado
function Panel({ v, onCollapse, newMission }) {
  const [q, setQ] = React.useState('');
  const [teamOpen, setTeamOpen] = React.useState(true);
  const ws = v.account?.workspace?.name || 'Kiroo';
  const name = v.account?.user?.name || 'Minha conta';
  const team = v.team.filter((a) => `${a.name} ${a.role}`.toLowerCase().includes(q.trim().toLowerCase()));
  const busy = v.team.filter((a) => v.statuses[a.id] !== 'idle').length;
  const openAgent = (a) => {
    if (v.view === 'escritorio') { const r = v.rooms.find((x) => x.agent === a.id); if (r) { r.go(); return; } }
    v.openStep(a.tab);
  };
  return (
    <aside className="pv-panel" aria-label="Painel do estúdio">
      <header className="pv-panel-head">
        <div className="pv-brand"><img src={wordmark} alt="Kiroo" height="22" /><h2 title={ws}>{ws}</h2></div>
        <RailTip label="Recolher painel"><button type="button" className="pv-icon-btn" onClick={onCollapse} aria-label="Recolher painel"><PanelLeft size={18} aria-hidden="true" /></button></RailTip>
      </header>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button type="button" className="pv-mission-pick"><Workflow size={14} aria-hidden="true" /><span>{v.hasProd ? v.prodName : 'Nenhuma missão aberta'}</span><ChevronDown size={14} aria-hidden="true" /></button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-64">
          <DropdownMenuLabel>Missões</DropdownMenuLabel>
          {v.productions.length === 0 && <DropdownMenuItem disabled>Nenhuma missão ainda</DropdownMenuItem>}
          {v.productions.slice(0, 8).map((p) => (
            <DropdownMenuItem key={p.id} onSelect={p.open}>{p.current ? <CheckCheck /> : <span className="w-4" />}<span className="truncate">{p.name || p.id}</span></DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={newMission}><Plus />Nova missão</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <section className="pv-next" aria-label="Próxima ação" data-tour="next-action">
        <strong>{v.nextLabel ? 'Próxima ação' : 'Tudo em andamento'}</strong>
        <p>{v.nextLong}</p>
        {v.nextLabel
          ? <button type="button" className="pv-cta" onClick={v.goNext}>{v.nextLabel}</button>
          : <button type="button" className="pv-cta" onClick={newMission}><Plus size={16} aria-hidden="true" />Nova missão</button>}
      </section>

      <label className="pv-search">
        <Search size={15} aria-hidden="true" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Pesquisar agentes" aria-label="Pesquisar agentes" />
      </label>

      <button type="button" className="pv-group-h" data-tour="team-head" aria-expanded={teamOpen} onClick={() => setTeamOpen((o) => !o)}>
        Equipe ({busy} de {v.team.length} ativos)<ChevronDown size={13} aria-hidden="true" />
      </button>
      {teamOpen && (
        <ul className="pv-people" data-tour="team">
          {team.map((a) => { const st = v.statuses[a.id] || 'idle'; const [s, t] = AGENT_STATE[st] || AGENT_STATE.idle; return (
            <li key={a.id}>
              <button type="button" onClick={() => openAgent(a)} aria-label={`${a.name}, ${a.role}: ${t}`}>
                <span className="pv-person-av"><Avatar look={a.look} size={34} /><i data-s={s} aria-hidden="true" /></span>
                <span className="pv-grow"><strong>{a.name}</strong><span>{st === 'idle' ? a.role : t}</span></span>
                {st === 'need' && <span className="pv-need" aria-hidden="true">!</span>}
              </button>
            </li>); })}
          {team.length === 0 && <li className="pv-people-empty">Ninguém com esse nome.</li>}
        </ul>
      )}

      <span className="pv-rail-fill" />
      <button type="button" className="pv-me" data-tour="account" onClick={() => v.openPrefs('account')}>
        <span className="pv-me-av" aria-hidden="true">{name.trim().charAt(0).toUpperCase() || 'P'}<i /></span>
        <span className="pv-grow"><strong>{name}</strong><span>Conta e preferências</span></span>
        <UserRound size={16} aria-hidden="true" />
      </button>
    </aside>
  );
}

export default function Shell({ v, rootRef, stageRef, onKeyDown, onKeyUp, onBlur, children }) {
  const [pal, setPal] = React.useState(false);
  const [panel, setPanelRaw] = React.useState(() => LS.get('bc.panel', typeof window === 'undefined' || window.innerWidth >= 900));
  const setPanel = (x) => { setPanelRaw(x); LS.set('bc.panel', x); };
  React.useEffect(() => {
    const h = (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPal((p) => !p); } };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, []);
  const cur = VIEWS.find((x) => x.id === v.view) || VIEWS[0];
  React.useEffect(() => { document.title = `Kiroo — ${cur.label}`; }, [cur.label]);
  const bal = v.wallet ? (v.wallet.exempt ? 'Isento' : `${v.wallet.balance} créditos`) : '';
  const newMission = () => { v.setView('missao'); v.newProd(); };

  return (
    <div ref={rootRef} tabIndex={-1} onKeyDown={onKeyDown} onKeyUp={onKeyUp} onBlur={onBlur} className="pv" data-panel={panel ? 'open' : 'closed'}
      aria-label="Kiroo. Trilho de navegação, painel do estúdio e área de trabalho. Ctrl K abre a busca de comandos.">
      <TooltipProvider delayDuration={250}>
        <Rail v={v} onSearch={() => setPal(true)} newMission={newMission} />
        {panel && <Panel v={v} onCollapse={() => setPanel(false)} newMission={newMission} />}
        <main className="pv-stage">
          <header className="pv-top">
            {!panel && <RailTip label="Abrir painel"><button type="button" className="pv-icon-btn" onClick={() => setPanel(true)} aria-label="Abrir painel"><PanelLeft size={18} aria-hidden="true" /></button></RailTip>}
            <h1>{cur.title}{v.view !== 'central' && v.prodName ? <span> · {v.prodName}</span> : null}</h1>
            {v.conn === 'erro' && <span role="alert" className="pv-status pv-status-error">Sem conexão</span>}
            {v.mode === 'simulated' && <span className="pv-status pv-status-demo" title="Nada é cobrado; imagens e vídeos são de exemplo">DEMO</span>}
            <span className="pv-rail-fill" />
            <span className="pv-top-modes" data-tour="top-modes">
              {bal && <button type="button" className="pv-top-btn pv-hide-sm" onClick={() => v.openPrefs('credits')}><CircleDollarSign size={15} aria-hidden="true" />{bal}</button>}
              <button type="button" className="pv-top-btn pv-hide-md" onClick={() => v.openPrefs('pilot')}><Bot size={15} aria-hidden="true" />{v.pilot.label}</button>
            </span>
            <button type="button" className="pv-cta pv-cta-sm" data-tour="new-mission" onClick={newMission}><Plus size={16} aria-hidden="true" /><span className="pv-hide-sm">Nova missão</span></button>
          </header>
          <div className="pv-body" ref={stageRef} data-tour={v.view === 'escritorio' ? 'office' : undefined}>{children}</div>
        </main>
        {pal && <Palette v={v} onClose={() => setPal(false)} />}
      </TooltipProvider>
    </div>
  );
}

function Palette({ v, onClose }) {
  const [q, setQ] = React.useState('');
  const [sel, setSel] = React.useState(0);
  const items = React.useMemo(() => [
    ...VIEWS.map((x) => ({ id: `v-${x.id}`, label: `Ir para ${x.label}`, hint: 'Navegar', icon: 'flow', run: () => v.setView(x.id) })),
    { id: 'new', label: 'Nova missão', hint: 'Ação', icon: 'plus', run: () => { v.setView('missao'); v.newProd(); } },
    ...(v.nextLabel ? [{ id: 'next', label: v.nextLabel, hint: v.nextLong, icon: 'arrow', run: v.goNext }] : []),
    ...v.rooms.filter((r) => r.placed || v.world !== 'phaser').map((r) => ({ id: `r-${r.id}`, label: `Ir à sala ${r.name}`, hint: 'Escritório', icon: 'flow', run: () => { v.setView('escritorio'); r.go(); } })),
    { id: 'credits', label: 'Créditos e extrato', hint: 'Conta', icon: 'coin', run: () => v.openPrefs('credits') },
    { id: 'pilot', label: 'Configurar piloto', hint: 'Automação', icon: 'pilot', run: () => v.openPrefs('pilot') },
    { id: 'prefs', label: 'Preferências', hint: 'Conta', icon: 'user', run: () => v.openPrefs('prefs') },
    { id: 'tour', label: 'Rever tutorial', hint: 'Ajuda', icon: 'arrow', run: v.openTour },
    ...v.team.map((a) => ({ id: `a-${a.id}`, label: `${a.name} · ${a.role}`, hint: 'Abrir etapa', icon: 'team', run: () => v.openStep(a.tab) })),
    ...v.productions.map((p) => ({ id: `p-${p.id}`, label: p.name || p.id, hint: 'Missão', icon: 'flow', run: () => { p.open(); v.setView('missao'); } })),
  ], [v]);
  const list = items.filter((i) => `${i.label} ${i.hint}`.toLowerCase().includes(q.trim().toLowerCase())).slice(0, 12);
  const run = (i) => { onClose(); if (i) i.run(); };
  const onKey = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); onClose(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(s + 1, list.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); run(list[sel]); }
    e.stopPropagation();
  };
  return (
    <div className="pv-scrim" onMouseDown={onClose}>
      <div className="pv-pal" role="dialog" aria-modal="true" aria-label="Buscar e executar comandos" onMouseDown={(e) => e.stopPropagation()} onKeyDown={onKey}>
        <div className="pv-pal-search"><Search aria-hidden="true" /><input autoFocus value={q} onChange={(e) => { setQ(e.target.value); setSel(0); }} placeholder="Buscar missão, sala, agente ou ação…" aria-label="Buscar" /></div>
        <ul role="listbox">
          {list.map((i, k) => (
            <li key={i.id}><button role="option" aria-selected={k === sel} onMouseEnter={() => setSel(k)} onClick={() => run(i)}><Icon name={i.icon} /><span>{i.label}</span><small>{i.hint}</small></button></li>
          ))}
          {list.length === 0 && <li className="pv-empty">Nada encontrado.</li>}
        </ul>
        <footer><span><Sparkles />Comandos rápidos</span><span><kbd>↑</kbd><kbd>↓</kbd> navegar <kbd>Enter</kbd> abrir</span></footer>
      </div>
    </div>
  );
}
