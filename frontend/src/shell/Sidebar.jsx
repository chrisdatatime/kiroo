import React from 'react';
import { ChevronsUpDown, CircleDollarSign, HelpCircle, Home, Package, Users, Workflow } from 'lucide-react';
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { countsOf, balanceRatio, videosLeft, videosLine } from './inicio.js';
import { planName, initialOf } from '../ui/prefs.js';
import wordmark from '../assets/brand/wordmark-preto-laranja.svg';
import compactLogo from '../assets/brand/icone-app-preto.svg';
import './inicio.css';

// Barra lateral nova (desktop, 256 px; entre 768 e 1100 px vira só ícones por CSS). Cinco destinos; os que ainda não têm tela
// própria apontam para a mais próxima (Entregas → Produções), sem criar telas novas.
export function navItems(v) {
  const c = countsOf(v.productions);
  const waiting = c.aprovacao + c.decisao;
  return [
    { id: 'inicio', label: 'Início', icon: Home, on: v.view === 'central' && !v.win, go: () => v.setView('central') },
    { id: 'producoes', label: 'Produções', icon: Workflow, badge: waiting, on: v.view === 'missao' && !v.win, go: () => v.setView('missao') },
    { id: 'entregas', label: 'Entregas', icon: Package, on: false, go: () => v.setView('missao') },   // sem tela própria: abre Produções
    { id: 'equipe', label: 'Equipe', icon: Users, on: v.view === 'equipe' && !v.win, go: () => v.setView('equipe') },
    { id: 'creditos', label: 'Créditos', icon: CircleDollarSign, on: v.win === 'credits', go: () => v.openPrefs('credits') },
  ];
}

export function BalanceCard({ v }) {
  const w = v.wallet;
  if (!w) return null;
  const n = videosLeft(w, v.offer);
  const ratio = balanceRatio(w, v.account && v.account.welcome);
  return (
    <section className="in-bal" aria-label="Saldo de créditos" data-tour="top-modes">
      <div className="in-bal-top"><span>Créditos</span>{v.openBuy && !w.exempt && <button type="button" className="in-link" onClick={v.openBuy}>Comprar</button>}</div>
      <strong>{w.exempt ? 'Isento' : w.balance}</strong>
      {ratio != null && <div className="in-bar in-bar-sm" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(ratio * 100)} aria-label="Saldo de créditos"><i style={{ width: `${ratio * 100}%` }} /></div>}
      {n != null && <span className="in-muted">{videosLine(n)}</span>}
    </section>
  );
}

export default function Sidebar({ v, menuItems }) {
  const ws = (v.account && v.account.workspace && v.account.workspace.name) || 'Kiroo';
  const user = (v.account && v.account.user) || {};
  const plan = v.account && v.account.plan;
  const email = (plan && plan.support && plan.support.email) || 'suporte@kiroo.io';
  return (
    <aside className="in-side" aria-label="Menu do estúdio">
      <img className="in-logo" src={wordmark} alt="Kiroo" height="24" />
      <img className="in-logo-icon" src={compactLogo} alt="" aria-hidden="true" />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button type="button" className="in-ws" aria-label={`Estúdio ${ws}. Abrir menu`}>
            <span className="in-ws-av" aria-hidden="true">{initialOf({ name: ws })}</span>
            <span className="in-ws-txt"><strong>{ws}</strong><span>{plan ? `Plano ${planName(plan).toLowerCase()}` : 'Estúdio'}</span></span>
            <ChevronsUpDown size={15} aria-hidden="true" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="pv-menu w-60">{menuItems}</DropdownMenuContent>
      </DropdownMenu>
      <nav className="in-nav" aria-label="Navegação principal">
        {navItems(v).map((x) => (
          <button key={x.id} type="button" className="in-nav-btn" data-active={x.on || undefined} aria-current={x.on ? 'page' : undefined} onClick={x.go}
            aria-label={x.label + (x.badge ? `, ${x.badge} esperando ação` : '')}>
            <x.icon size={18} aria-hidden="true" /><span className="in-nav-txt">{x.label}</span>
            {x.badge > 0 && <b className="in-count" aria-hidden="true">{x.badge}</b>}
          </button>
        ))}
      </nav>
      <span className="in-fill" />
      <BalanceCard v={v} />
      <a className="in-nav-btn in-help" href={`mailto:${email}?subject=${encodeURIComponent('Suporte Kiroo')}`}><HelpCircle size={18} aria-hidden="true" /><span className="in-nav-txt">Ajuda e suporte<small>{email}</small></span></a>
      <button type="button" className="in-me" data-tour="account" onClick={() => v.openPrefs('account')} aria-label={`${user.name || 'Minha conta'}. Conta e preferências`}>
        <span className="in-me-av" aria-hidden="true">{initialOf(user)}</span>
        <span className="in-nav-txt"><strong>{user.name || 'Minha conta'}</strong><small>{user.email || 'Conta e preferências'}</small></span>
      </button>
    </aside>
  );
}
