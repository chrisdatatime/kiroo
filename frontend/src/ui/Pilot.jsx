import React from 'react';

// Piloto: quanto o estúdio decide sozinho. Vale para a produção atual e vira o padrão das próximas.
export const PILOT = {
  manual: { label: 'Manual', short: 'Você aprova cada passo',
    desc: 'Você aprova a direção, libera cada etapa paga depois de ver a estimativa e aprova cada imagem e take. Se o Rui encontrar um problema, ele avisa você em vez de refazer sozinho.' },
  assistido: { label: 'Assistido', short: 'Você decide a direção e as dúvidas',
    desc: 'Você aprova a direção. Depois, dentro do valor que você autorizou, o estúdio gera tudo, refaz o que o Rui reprovar e aprova o que ele aprovar. Quando a conferência fica inconclusiva, a cena espera você.' },
  automatico: { label: 'Automático', short: 'Do produto ao vídeo montado sem parar',
    desc: 'Depois da ficha, o estúdio usa a direção sugerida, gera, refaz e aprova sozinho dentro do valor que você autorizou (inclusive o que ficar inconclusivo). Você só revisa o vídeo final antes de exportar.' },
};

export function PilotContent({ v }) {
  const cur = v.pilot.mode;
  return (
    <div className="pref-stack">
      <span className="g-muted" style={{ fontSize: 13.5 }}>Escolha quanto os agentes decidem sozinhos. {v.pilot.hasProd ? 'Vale para a produção atual e para as próximas.' : 'Vale para as próximas produções.'}</span>
      <div role="radiogroup" aria-label="Autonomia" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {Object.entries(PILOT).map(([id, p]) => (
          <button key={id} role="radio" aria-checked={cur === id} className="g-pick" aria-pressed={cur === id} onClick={() => v.pilot.set(id)} disabled={!!v.busy}
            style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: 14, textAlign: 'left' }}>
            <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}><strong className="fred" style={{ fontSize: 17, fontWeight: 600 }}>{p.label}</strong><span className="g-muted" style={{ fontSize: 13 }}>· {p.short}</span></span>
            <span style={{ fontSize: 13.5, lineHeight: 1.45 }}>{p.desc}</span>
          </button>
        ))}
      </div>
      <div className="g-card" style={{ padding: 12, fontSize: 13, lineHeight: 1.45 }}>
        Em qualquer modo: o estúdio <strong>nunca cobra além do valor que você autorizou</strong> nem passa do teto do mês (pausa antes), respeita o máximo de tentativas por cena e <strong>não exporta sem a sua revisão final</strong>. A conferência do Rui pode errar.
      </div>
    </div>
  );
}
