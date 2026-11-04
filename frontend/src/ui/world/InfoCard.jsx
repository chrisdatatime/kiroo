import React from 'react';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';

// Cartão de hover (sala ou agente): nome, agente, estado e "Ir à sala" / "Abrir".
// O conteúdo vai para o body (portal) e segue o gatilho mesmo com a câmera andando (updatePositionStrategy="always").
// Teclas dentro do cartão não descem para o atalho do jogo (WASD), exceto Esc, que o Radix usa para fechar.
const stopKeys = (e) => { if (e.key !== 'Escape') e.stopPropagation(); };

export function StatusChip({ need, children }) {
  return <span className={'pw-chip' + (need ? ' pw-chip-need' : '')}>{need && <b aria-hidden="true">!</b>}{children}</span>;
}

export default function InfoCard({ title, subtitle, status, need, onGo, onOpen, onTalk, children }) {
  return (
    <HoverCard openDelay={150} closeDelay={120}>
      <HoverCardTrigger asChild>{children}</HoverCardTrigger>
      <HoverCardContent side="top" sideOffset={8} updatePositionStrategy="always" className="pw-theme pw-card duration-150" onKeyDown={stopKeys}>
        <div className="pw-card-head">
          <strong>{title}</strong>
          {subtitle && <span>{subtitle}</span>}
        </div>
        {status && <StatusChip need={need}>{status}</StatusChip>}
        {(onGo || onOpen || onTalk) && (
          <div className="pw-card-actions">
            {onTalk && <button type="button" className="pw-btn" onClick={onTalk}>Conversar</button>}
            {onGo && <button type="button" className="pw-btn" onClick={onGo}>Ir à sala</button>}
            {onOpen && <button type="button" className="pw-btn pw-btn-primary" onClick={onOpen}>Abrir</button>}
          </div>
        )}
      </HoverCardContent>
    </HoverCard>
  );
}
