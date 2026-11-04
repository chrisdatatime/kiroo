import React from 'react';
import { CloseButton } from './bits.jsx';

// Minha conta: quem está logado, estúdio (workspace), modo e sair.
export default function AccountWindow({ v }) {
  const a = v.account;
  if (!a) return null;
  return (
    <section role="dialog" aria-labelledby="acc-h" className="g-panel pop" style={{ position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', zIndex: 22, width: 'min(460px,calc(100vw - 24px))', padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <h2 id="acc-h" className="fred" style={{ margin: 0, fontSize: 22, fontWeight: 600, flex: 1 }}>Minha conta</h2>
        <CloseButton onClick={v.closeWin} label="Fechar conta" />
      </div>
      <dl className="g-card" style={{ margin: 0, padding: '6px 14px' }}>
        {[['Nome', a.user.name], ['E-mail', a.user.email], ['Estúdio', a.workspace.name],
          ['Modo', a.workspace.mode === 'real' ? 'IA real (gera custo)' : 'DEMO (sem custo, imagens de exemplo)'],
          ['Produção com IA real', a.workspace.allow_real ? 'liberada' : 'liberada com os planos de créditos'],
          ['Créditos', (v.wallet || a.workspace.credits || {}).exempt ? 'isento (conta do dono)' : ((v.wallet || a.workspace.credits || {}).balance || '0') + ' créditos']].map(([k, val]) => (
          <div key={k} style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '8px 0', borderBottom: '2px dotted #E2D7C3' }}>
            <dt className="g-label">{k}</dt><dd style={{ margin: 0, font: '700 14px/1.35 Nunito Sans,sans-serif' }}>{val}</dd>
          </div>
        ))}
      </dl>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button className="g-btn g-sm g-lime" onClick={v.openCredits}>Créditos e extrato</button>
        {a.admin && <a className="g-btn g-sm" href="/painel">Painel do administrador</a>}
        <button className="g-btn g-sm" onClick={v.openAbout}>Sobre e créditos</button>
        <button className="g-btn g-sm" onClick={v.logout}>Sair</button>
      </div>
    </section>
  );
}
