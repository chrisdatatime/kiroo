import React from 'react';

// Faixa "Criar outro vídeo" no fim do primeiro vídeo pronto. Texto em config/appConfig.js (NEXT_VIDEO_COPY), regra em ui/welcome.js.
export function UpsellNote({ copy, onClick }) {
  return (
    <section className="pv-upsell" aria-label="Continue criando">
      <p>{copy.text}</p>
      <button type="button" className="pv-upsell-btn" onClick={onClick}>{copy.cta}</button>
    </section>
  );
}
