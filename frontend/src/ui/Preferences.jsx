import React from 'react';
import { Bot, CircleDollarSign, GraduationCap, Info, Settings, Shield, UserRound, X } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { AccountContent } from './Account.jsx';
import { PilotContent } from './Pilot.jsx';
import { CreditsContent } from './Credits.jsx';
import { AboutContent } from './About.jsx';
import { adminTabVisible } from './admin.js';
import { SCENERY_THEMES, THEME_LABELS } from '../game/scenery/scenery.js';
import { lazyChunk } from '../lib/lazyChunk.jsx';

// Aba Administrador: carregada só quando aberta (e só existe no menu para administrador da plataforma).
const AdminContent = lazyChunk(() => import('./Admin.jsx').then((m) => ({ default: m.AdminContent })));

// Preferências: um modal com navegação à esquerda (padrão de layout de apps de escritório virtual) no lugar das janelas
// soltas de Conta, Piloto, Créditos e Sobre. A aba é o próprio `win` do App (prefs | account | pilot | credits | about).
const GROUPS = [
  { label: 'Preferências', items: [
    { id: 'prefs', label: 'Geral', icon: Settings },
    { id: 'pilot', label: 'Piloto', icon: Bot },
  ] },
  { label: 'Estúdio', items: [
    { id: 'account', label: 'Minha conta', icon: UserRound },
    { id: 'credits', label: 'Créditos e extrato', icon: CircleDollarSign },
    { id: 'about', label: 'Sobre', icon: Info },
    { id: 'admin', label: 'Administrador', icon: Shield, admin: true },
  ] },
];
const TITLES = { prefs: 'Geral', pilot: 'Piloto do estúdio', account: 'Minha conta', credits: 'Créditos do estúdio', about: 'Sobre e créditos', admin: 'Administrador' };
const DESCS = {
  prefs: 'Aparência e visual da sede.',
  pilot: 'Quanto os agentes decidem sozinhos.',
  account: 'Quem está conectado e em qual estúdio.',
  credits: 'Saldo, consumo por produção e extrato.',
  about: 'Kiroo e os créditos da arte.',
  admin: 'Contas, créditos, convites, métricas e auditoria da plataforma.',
};

function Row({ title, desc, children }) {
  return (
    <div className="pref-row">
      <div><div className="pref-row-title">{title}</div>{desc && <div className="pref-row-desc">{desc}</div>}</div>
      <div className="pref-row-ctl">{children}</div>
    </div>
  );
}

function General({ v }) {
  return (
    <div className="pref-stack">
      <section className="pref-sec">
        <h3 className="pref-sec-h">Aparência</h3>
        <Row title="Modo de cor" desc="O Kiroo usa o tema claro. O modo escuro vem depois.">
          <span className="pref-static">Claro</span>
        </Row>
        <Row title="Cenário do escritório" desc="O fundo atrás do mapa. Floresta usa a arte de Forest of Illusion; sem os arquivos, vira o cenário gerado.">
          <div role="group" aria-label="Cenário do escritório" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {SCENERY_THEMES.map((t) => (
              <button key={t} type="button" className="pw-btn" aria-pressed={v.cenario === t} onClick={() => v.setCenario(t)}
                style={v.cenario === t ? { background: '#0E0E10', color: '#FAFAF8', borderColor: '#0E0E10' } : undefined}>{THEME_LABELS[t]}</button>
            ))}
          </div>
        </Row>
      </section>
      <section className="pref-sec">
        <h3 className="pref-sec-h">Ajuda</h3>
        <Row title="Tutorial" desc="O tour rápido pelo estúdio, do começo.">
          <button type="button" className="pw-btn" onClick={v.openTour}><GraduationCap size={15} aria-hidden="true" />Rever tutorial</button>
        </Row>
      </section>
    </div>
  );
}

export default function Preferences({ v }) {
  const isAdmin = adminTabVisible(v.account);
  const tab = TITLES[v.win] && (v.win !== 'admin' || isAdmin) ? v.win : 'prefs';
  const onOpenChange = (open) => { if (!open) v.closeWin(); };
  // teclas digitadas no modal não chegam aos atalhos do jogo (só Esc, que o Radix usa para fechar)
  const stopKeys = (e) => { if (e.key !== 'Escape') e.stopPropagation(); };
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false} className="pref pw-theme duration-200" onKeyDown={stopKeys}>
        <nav className="pref-nav" aria-label="Seções das preferências">
          {GROUPS.map((g) => (
            <div key={g.label} className="pref-group">
              <div className="pref-group-label">{g.label}</div>
              {g.items.filter((it) => !it.admin || isAdmin).map((it) => (
                <button key={it.id} type="button" className="pref-item" aria-current={tab === it.id ? 'page' : undefined} onClick={() => v.openPrefs(it.id)}>
                  <it.icon size={16} aria-hidden="true" />{it.label}
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="pref-main">
          <header className="pref-head">
            <div>
              <DialogTitle className="pref-title">{TITLES[tab]}</DialogTitle>
              <DialogDescription className="sr-only">{DESCS[tab]}</DialogDescription>
            </div>
            <button type="button" className="pw-iconbtn" onClick={v.closeWin} aria-label="Fechar preferências"><X size={18} aria-hidden="true" /></button>
          </header>
          <div className="pref-body">
            {tab === 'prefs' && <General v={v} />}
            {tab === 'pilot' && <PilotContent v={v} />}
            {tab === 'account' && <AccountContent v={v} />}
            {tab === 'credits' && <CreditsContent v={v} />}
            {tab === 'about' && <AboutContent v={v} />}
            {tab === 'admin' && isAdmin && <React.Suspense fallback={null}><AdminContent v={v} /></React.Suspense>}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
