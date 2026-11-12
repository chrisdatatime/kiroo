import React from 'react';

// "Cancelar missão" com confirmação dentro do app (o navegador embutido bloqueia window.confirm).
// Cancelar é definitivo: nada mais é gerado nem cobrado; o que já foi gerado fica no histórico e a reserva não usada volta.
export default function CancelMission({ v }) {
  if (!v.canCancel) return null;
  if (!v.confirmCancel) {
    return <button type="button" className="pv-btn pv-btn-quiet" onClick={v.cancelProd} disabled={!!v.busy}>Cancelar missão</button>;
  }
  return (
    <div role="alertdialog" aria-labelledby="cancel-q" aria-describedby="cancel-d" className="pv-confirm">
      <strong id="cancel-q">Cancelar esta missão?</strong>
      <span id="cancel-d">Nada mais será gerado nem cobrado. O que já foi gerado fica no histórico e a reserva não usada volta para o saldo. Não dá para retomar.</span>
      <span className="pv-confirm-actions">
        <button type="button" className="pv-btn pv-btn-danger" onClick={v.cancelProd} disabled={!!v.busy}>{v.busy === 'cancelar' ? 'Cancelando…' : 'Sim, cancelar'}</button>
        <button type="button" className="pv-btn" onClick={v.keepProd} autoFocus>Manter missão</button>
      </span>
    </div>
  );
}
