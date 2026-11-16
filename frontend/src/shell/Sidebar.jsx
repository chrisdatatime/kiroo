import React from 'react';
import { Building2, ChevronsUpDown, CircleHelp, Home, Package, Workflow } from 'lucide-react';
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { planName, initialOf } from '../ui/prefs.js';
import { AccountMenu, AccountRow } from './AccountMenu.jsx';
import { sideNav, studioName, supportHref } from './accountMenu.js';
import wordmark from '../assets/brand/wordmark-preto-laranja.svg';
import compactLogo from '../assets/brand/icone-app-preto.svg';
import './inicio.css';

// Menu lateral (desktop, 248 px; entre 768 e 1100 px vira só ícones por CSS): logo, seletor do estúdio, quatro destinos
// (Início, Escritório com AO VIVO, Produções com "aguardando você", Entregas) e, no rodapé, Ajuda e a linha da conta,
// que abre o menu da conta. Créditos saiu daqui: fica no menu da conta e em Configurações.
const ICONS = { inicio: Home, escritorio: Building2, producoes: Workflow, entregas: Package };

export function navItems(v) {
  return sideNav(v).map((x) => ({ ...x, icon: ICONS[x.id], go: () => v.setView(x.view) }));
}

export default function Sidebar({ v, menuItems }) {
  const ws = studioName(v.account);
  const plan = v.account && v.account.plan;
  return (
    <aside className="in-side" aria-label="Menu do estúdio">
      <img className="in-logo" src={wordmark} alt="Kiroo" height="24" />
      <img className="in-logo-icon" src={compactLogo} alt="" aria-hidden="true" />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button type="button" className="in-ws" aria-label={`${ws}. Abrir menu do estúdio`}>
            <span className="in-ws-av" aria-hidden="true">{initialOf({ name: ws.replace(/^Estúdio de\s+/i, '') })}</span>
            <span className="in-ws-txt"><strong>{ws}</strong><span>{plan ? `Plano ${planName(plan).toLowerCase()}` : 'Estúdio'}</span></span>
            <ChevronsUpDown size={15} aria-hidden="true" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="pv-menu w-60">{menuItems}</DropdownMenuContent>
      </DropdownMenu>
      <nav className="in-nav" aria-label="Seções">
        {navItems(v).map((x) => (
          <button key={x.id} type="button" className="in-nav-btn" data-active={x.on || undefined} aria-current={x.on ? 'page' : undefined} onClick={x.go}
            aria-label={x.label + (x.live ? ', ao vivo' : '') + (x.badge ? `, ${x.badge} aguardando você` : '')}>
            <x.icon size={18} aria-hidden="true" /><span className="in-nav-txt">{x.label}</span>
            {x.live && <b className="in-live" aria-hidden="true">AO VIVO</b>}
            {x.badge > 0 && <b className="in-count" aria-hidden="true">{x.badge}</b>}
          </button>
        ))}
      </nav>
      <span className="in-fill" />
      <a className="in-nav-btn in-help" href={supportHref(v.account)}><CircleHelp size={18} aria-hidden="true" /><span className="in-nav-txt">Ajuda e suporte</span></a>
      <AccountMenu v={v}><AccountRow v={v} /></AccountMenu>
    </aside>
  );
}
