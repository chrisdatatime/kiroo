import React from 'react';

// Convite discreto para os pacotes (primeiro vídeo pronto com saldo abaixo de um vídeo). Texto em ui/welcome.js.
export function UpsellNote({ copy, onClick }) {
  return (
    <section className="pv-upsell" aria-label="Continue criando">
      <p>{copy.text}</p>
      <button type="button" className="pv-upsell-btn" onClick={onClick}>{copy.cta}</button>
    </section>
  );
}
