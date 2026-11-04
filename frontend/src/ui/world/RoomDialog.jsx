import React from 'react';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { StatusChip } from './InfoCard.jsx';

// Detalhe da sala/etapa (carregado sob demanda). "Abrir trabalho" leva à janela da etapa (ProdWindow).
const stopKeys = (e) => { if (e.key !== 'Escape') e.stopPropagation(); };

export default function RoomDialog({ room, open, onOpenChange }) {
  const r = room || {};
  const act = (fn) => () => { onOpenChange(false); if (fn) fn(); };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="pw-theme pw-dialog duration-200" onKeyDown={stopKeys}>
        <DialogHeader>
          <DialogTitle>{r.name}</DialogTitle>
          <DialogDescription>{r.who ? `${r.who}${r.role ? ' · ' + r.role : ''}` : 'Área comum'}</DialogDescription>
        </DialogHeader>
        {r.status && <div><StatusChip need={r.need}>{r.status}</StatusChip></div>}
        {r.hint && <p className="pw-dialog-hint">{r.hint}</p>}
        <DialogFooter>
          <button type="button" className="pw-btn" onClick={act(r.go)}>Ir à sala</button>
          {r.agent && <button type="button" className="pw-btn pw-btn-primary" onClick={act(r.work)}>Abrir trabalho</button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
