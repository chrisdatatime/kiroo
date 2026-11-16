import React from 'react';
import {
  ArrowLeft, Bell, Bot, Building2, CheckCheck, CircleDollarSign, GraduationCap, Home, Info, LogOut, Pause,
  Package, Plus, Search, Settings, Shield, Sparkles, UsersRound, Workflow,
} from 'lucide-react';
import { DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator } from '@/components/ui/dropdown-menu';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import Icon from './icons.jsx';
import { usePhone } from '../hooks/use-phone.js';
import { FalChips } from '../ui/FalMission.jsx';
import Sidebar from './Sidebar.jsx';
import { AccountDrawer, Spark } from './AccountMenu.jsx';
import KirooAvatar from './KirooAvatar.jsx';
import { phoneTabs } from './accountMenu.js';
import wordmark from '../assets/brand/wordmark-preto-laranja.svg';
import './shell.css';
import './phone.css';

// Layout: barra lateral nova (Sidebar.jsx) em todas as telas, inclusive o Escritório (Fase 2: o trilho e o painel antigos saíram),
// barra superior e a área de trabalho num cartão arredondado à direita. No celular, cabeçalho + barra inferior.
export const VIEWS = [
  { id: 'central', label: 'Início', title: 'Início', icon: Home },
  { id: 'missao', label: 'Produções', title: 'Produção', icon: Workflow },
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

// Itens do menu do estúdio (seletor do estúdio na barra lateral)
export function WorkspaceItems({ v, newMission }) {
  return (
    <>
        <div className="pv-menu-cta"><button type="button" className="pv-cta" onClick={newMission}><Plus size={16} aria-hidden="true" />Nova produção</button></div>
        <DropdownMenuItem onSelect={() => v.openPrefs('prefs')}><Settings />Preferências</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => v.openPrefs('pilot')}><Bot />Piloto: {v.pilot.label}</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => v.openPrefs('credits')}><CircleDollarSign />Créditos e extrato</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => v.openPrefs('about')}><Info />Sobre o Kiroo</DropdownMenuItem>
        <DropdownMenuItem onSelect={v.openTour}><GraduationCap />Rever tutorial</DropdownMenuItem>
        {v.account?.admin && (<>
          <DropdownMenuSeparator />
          <DropdownMenuLabel>Administrador</DropdownMenuLabel>
          <DropdownMenuItem onSelect={() => v.openPrefs('admin')}><Shield />Administrador</DropdownMenuItem>
          <DropdownMenuItem asChild><a href="/painel"><Shield />Painel antigo</a></DropdownMenuItem>
        </>)}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={v.logout}><LogOut />Sair</DropdownMenuItem>
    </>
  );
}

// Atividade: o que precisa de você. Lido = guardado neste navegador; o ponto azul some, o item continua até ser resolvido.
export function Activity({ v, side = 'right', topbar = false }) {
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
          <button type="button" className={topbar ? 'in-bell' : 'pv-rail-btn'} aria-label={`Atividade${unread ? `, ${unread} não lidas` : ''}`} data-active={open || undefined}>
            <Bell size={20} strokeWidth={1.8} aria-hidden="true" />
            {unread > 0 && <span className="pv-badge" aria-hidden="true">{unread}</span>}
          </button>
        </PopoverTrigger>
      </RailTip>
      <PopoverContent side={side} align={topbar ? 'end' : 'start'} sideOffset={10} className="pv-activity" onOpenAutoFocus={(e) => e.preventDefault()}>
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

// Celular: barra inferior de 72 px: Início, Escritório, "+" (nova produção), Produções e Entregas.
// Entregas ainda não tem tela própria e abre Produções. Conta e Créditos ficam no avatar do topo (gaveta da conta).
const TAB_ICONS = { inicio: Home, escritorio: Building2, producoes: Workflow, entregas: Package };
function TabBar({ v, newMission }) {
  const go = (view) => () => { if (v.win) v.closeWin(); v.setView(view); };
  return (
    <nav className="pv-tabbar in-tabbar" aria-label="Navegação principal">
      {phoneTabs(v).map((x) => {
        if (x.plus) return <button key={x.id} type="button" className="in-tab-plus" onClick={newMission} aria-label={x.label}><Plus size={26} aria-hidden="true" /></button>;
        const Ic = TAB_ICONS[x.id];
        return (
          <button key={x.id} type="button" className="pv-tab" data-active={x.on || undefined} aria-current={x.on ? 'page' : undefined} onClick={go(x.view)}
            aria-label={x.label + (x.live ? ', ao vivo' : '') + (x.badge ? `, ${x.badge} aguardando você` : '')}>
            <Ic size={22} strokeWidth={x.on ? 2.2 : 1.8} aria-hidden="true" /><span>{x.label}</span>
            {(x.badge > 0 || x.live) && <i className="pv-tab-dot" data-live={x.live && !x.badge ? '' : undefined} aria-hidden="true" />}
          </button>
        );
      })}
    </nav>
  );
}

// Avatar do topo no celular: abre a gaveta da conta.
function PhoneMe({ v, onOpen }) {
  const user = (v.account && v.account.user) || {};
  return (
    <button type="button" className="pv-me-phone" onClick={onOpen} aria-label="Conta" aria-haspopup="dialog" data-tour="account">
      <KirooAvatar user={user} size={34} />
    </button>
  );
}

const PHONE_TITLE = { central: 'Início', equipe: 'Equipe', escritorio: 'Escritório', config: 'Configurações' };
const DESK_TITLE = { central: 'Início', escritorio: 'Escritório', config: 'Configurações' };
// telas cujo cabeçalho no celular é o da marca (logo, saldo, avisos e conta), como no design do Início e do Escritório
const PHONE_HOME = { central: true, escritorio: true };

export default function Shell({ v, rootRef, stageRef, onKeyDown, onKeyUp, onBlur, children }) {
  const phone = usePhone();
  const [pal, setPal] = React.useState(false);
  const [drawer, setDrawer] = React.useState(false);
  React.useEffect(() => {
    const h = (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPal((p) => !p); } };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, []);
  const cur = VIEWS.find((x) => x.id === v.view) || (v.view === 'config' ? { id: 'config', label: 'Configurações', title: 'Configurações' } : VIEWS[0]);
  React.useEffect(() => { document.title = `Kiroo — ${cur.label}`; }, [cur.label]);
  const bal = v.wallet ? (v.wallet.exempt ? 'Isento' : `${v.wallet.balance} créditos`) : '';
  const newMission = () => { v.setView('missao'); v.newProd(); };
  const falTop = v.view === 'missao' && v.falMission ? v.falMission : null;   // missão fal: topo com chips e Nova missão em accent

  return (
    <div ref={rootRef} tabIndex={-1} onKeyDown={onKeyDown} onKeyUp={onKeyUp} onBlur={onBlur} className="pv" data-phone={phone || undefined}
      aria-label={phone ? 'Kiroo' : 'Kiroo. Menu lateral e área de trabalho. Ctrl K abre a busca de comandos.'}>
      <TooltipProvider delayDuration={250}>
        {!phone && <Sidebar v={v} menuItems={<WorkspaceItems v={v} newMission={newMission} />} />}
        <main className="pv-stage">
          {phone && PHONE_HOME[v.view] ? (
            <header className="pv-top pv-top-phone in-top-phone">
              <img src={wordmark} alt="Kiroo" height="22" />
              <span className="pv-rail-fill" />
              {v.conn === 'erro' && <span role="alert" className="pv-status pv-status-error">Sem conexão</span>}
              {v.mode === 'simulated' && <span className="pv-status pv-status-demo">DEMO</span>}
              {bal && <button type="button" className="pv-top-credits" onClick={() => v.openSettings('creditos')} aria-label={`Saldo: ${bal}. Abrir créditos`}><Spark size={14} />{v.wallet.exempt ? 'Isento' : v.wallet.balance}</button>}
              <Activity v={v} side="bottom" topbar />
              <PhoneMe v={v} onOpen={() => setDrawer(true)} />
            </header>
          ) : phone ? (
            <header className="pv-top pv-top-phone">
              {(v.view === 'missao' || v.view === 'config') && <button type="button" className="pv-back" onClick={() => v.setView('central')} aria-label="Voltar para o início"><ArrowLeft size={22} aria-hidden="true" /></button>}
              <h1>{v.view === 'missao' ? (v.hasProd && v.prodName ? v.prodName : 'Produção') : (PHONE_TITLE[v.view] || cur.title)}</h1>
              {v.conn === 'erro' && <span role="alert" className="pv-status pv-status-error">Sem conexão</span>}
              {v.mode === 'simulated' && <span className="pv-status pv-status-demo">DEMO</span>}
              <span className="pv-rail-fill" />
              {bal && <button type="button" className="pv-top-credits" onClick={() => v.openSettings('creditos')} aria-label={`Saldo: ${bal}. Abrir créditos`}><Spark size={14} />{v.wallet.exempt ? 'Isento' : v.wallet.balance}</button>}
              {falTop && <button type="button" className="pv-cta pv-cta-accent pv-cta-icon" onClick={newMission} aria-label="Nova produção"><Plus size={18} aria-hidden="true" /></button>}
              <PhoneMe v={v} onOpen={() => setDrawer(true)} />
            </header>
          ) : DESK_TITLE[v.view] ? (
          <header className="pv-top in-top">
            <h1>{DESK_TITLE[v.view]}</h1>
            <span className="pv-rail-fill" />
            {v.conn === 'erro' && <span role="alert" className="pv-status pv-status-error">Sem conexão</span>}
            {v.mode === 'simulated' && <span className="pv-status pv-status-demo" title="Nada é cobrado; imagens e vídeos são de exemplo">DEMO</span>}
            <button type="button" className="in-search" onClick={() => setPal(true)} aria-label="Buscar produções (Ctrl K)"><Search size={16} aria-hidden="true" /><span>Buscar produções</span><kbd aria-hidden="true">Ctrl K</kbd></button>
            <Activity v={v} side="bottom" topbar />
            <button type="button" className="pv-cta pv-cta-sm in-new" data-tour="new-mission" onClick={newMission}><Plus size={16} aria-hidden="true" />Nova produção</button>
          </header>
          ) : (
          <header className="pv-top">
            <h1>{falTop ? 'Missão' : cur.title}{!falTop && v.view !== 'central' && v.prodName ? <span> · {v.prodName}</span> : null}</h1>
            {falTop && <FalChips chips={falTop.chips} />}
            {v.conn === 'erro' && <span role="alert" className="pv-status pv-status-error">Sem conexão</span>}
            {v.mode === 'simulated' && <span className="pv-status pv-status-demo" title="Nada é cobrado; imagens e vídeos são de exemplo">DEMO</span>}
            {v.ended && <span className="pv-status pv-status-ended" role="status">{v.ended === 'cancelled' ? 'Cancelada' : 'Falhou'}</span>}
            {!falTop && v.active && v.view !== 'central' && (
              <span className="pv-status pv-status-format pv-hide-sm" data-testid="active-format"
                title={'Apresentação e formato ativos: ' + v.active.label + ' · ' + v.active.format + (v.active.provisional ? ' (formato provisório até a Direção)' : '')}>
                {v.active.label}{v.active.format && !v.active.provisional ? <code>{v.active.format}</code> : null}
              </span>
            )}
            <span className="pv-rail-fill" />
            <span className="pv-top-modes" data-tour="top-modes">
              {bal && <button type="button" className="pv-top-btn pv-hide-sm" onClick={() => v.openPrefs('credits')}><CircleDollarSign size={15} aria-hidden="true" />{bal}</button>}
              <button type="button" className="pv-top-btn pv-hide-md" onClick={() => v.openPrefs('pilot')}><Bot size={15} aria-hidden="true" />{v.pilot.label}</button>
            </span>
            <button type="button" className={'pv-cta pv-cta-sm' + (falTop ? ' pv-cta-accent' : '')} data-tour="new-mission" onClick={newMission}><Plus size={16} aria-hidden="true" /><span className="pv-hide-sm">Nova produção</span></button>
          </header>
          )}
          <div className="pv-body" ref={stageRef} data-tour={v.view === 'escritorio' ? 'office' : undefined}>{children}</div>
        </main>
        {phone && <TabBar v={v} newMission={newMission} />}
        {phone && <AccountDrawer v={v} open={drawer} onOpenChange={setDrawer} />}
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
    { id: 'new', label: 'Nova produção', hint: 'Ação', icon: 'plus', run: () => { v.setView('missao'); v.newProd(); } },
    ...(v.nextLabel ? [{ id: 'next', label: v.nextLabel, hint: v.nextLong, icon: 'arrow', run: v.goNext }] : []),
    ...v.rooms.filter((r) => r.placed).map((r) => ({ id: `r-${r.id}`, label: `Ir à sala ${r.name}`, hint: 'Escritório', icon: 'flow', run: () => { v.setView('escritorio'); r.go(); } })),
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
