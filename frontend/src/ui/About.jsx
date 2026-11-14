import React from 'react';
import { ChevronRight } from 'lucide-react';
import wordmark from '../assets/brand/wordmark-preto-laranja.svg';
import { aboutCards, aboutLinks, footerText } from './prefs.js';
import './prefs.css';

// Sobre (Preferências). Links e rodapé vêm do ambiente (`account.site`): sem env, o item some.
// A atribuição do tileset/cenário NÃO fica aqui: ver Landing.jsx (rodapé) e game/scenery/scenery.js (SCENERY_CREDIT,
// exibido em Preferências > Geral). Não confundir com ui/Credits.jsx, que é o saldo.
export function AboutView({ site, hasTour, onTour }) {
  const s = site || {};
  const cards = aboutCards(s, hasTour);
  const links = aboutLinks(s);
  const ext = { target: '_blank', rel: 'noopener noreferrer' };
  return (
    <div className="pf">
      <section className="pf-hero">
        <div>
          <img src={wordmark} alt="kiroo" />
          <h3>Seu estúdio ganha vida.</h3>
          <p className="pf-muted">Vídeos de produto com narração, foto, título e legenda, a partir de uma foto.</p>
        </div>
        {(s.version || s.changelog_url) && (
          <div className="pf-hero-r">
            {s.version && <span className="pf-pill is-ink" style={{ letterSpacing: 0 }}>Versão {s.version}</span>}
            {s.changelog_url && <a className="pf-link" href={s.changelog_url} {...ext}>O que há de novo</a>}
          </div>
        )}
      </section>
      {cards.length > 0 && (
        <div className="pf-shortcuts" style={{ '--n': Math.min(cards.length, 3) }}>
          {cards.map((c) => (c.action === 'tour'
            ? <button key={c.id} type="button" className="pf-sc" onClick={onTour}><strong>{c.title}</strong><span>{c.desc}</span></button>
            : c.href
              ? <a key={c.id} className="pf-sc" href={c.href} {...(c.href.startsWith('https') ? ext : {})}><strong>{c.title}</strong><span>{c.desc}</span></a>
              : <div key={c.id} className="pf-sc" style={{ cursor: 'default' }}><strong>{c.title}</strong><span>{c.desc}</span></div>))}
        </div>
      )}
      {links.length > 0 && (
        <nav className="pf-links" aria-label="Documentos">
          {links.map((l) => <a key={l.id} href={l.href} {...ext}>{l.title}<ChevronRight size={16} aria-hidden="true" /></a>)}
        </nav>
      )}
      <footer className="pf-legal">
        <span>{footerText(s)}</span>
        <span>Feito no Brasil</span>
      </footer>
    </div>
  );
}

export function AboutContent({ v } = {}) {
  return <AboutView site={v && v.account && v.account.site} hasTour={!!(v && v.openTour)} onTour={v && v.openTour} />;
}
