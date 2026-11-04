import React from 'react';
import Icon from './icons.jsx';
import { Avatar, Pill, AGENT_STATE } from './Central.jsx';

const ABOUT = {
  nina: 'Lê a ficha do produto, organiza as fotos oficiais e separa fato de suposição. Não inventa característica.',
  theo: 'Transforma o produto em direção criativa e em um roteiro de 3 cenas, com a sua aprovação.',
  iris: 'Cria a imagem de cada cena a partir das fotos oficiais. A cena 1 vira referência das outras.',
  rui: 'Confere se o produto continua fiel às referências. Pode responder "inconclusivo": ele ajuda, não garante.',
  lia: 'Anima as imagens aprovadas e guarda a trilha musical escolhida.',
  beto: 'Monta o vídeo final com cortes, texto, capa e legenda, só com FFmpeg.',
};

// Equipe: cadastro dos agentes. Hoje são os seis do estúdio de vídeo; criar e configurar agentes é a Fase 3 do plano.
export default function TeamView({ v }) {
  return (
    <div className="pv-scroll"><div className="pv-wrap">
      <header>
        <h2 className="pv-hello">Sua equipe</h2>
        <p className="pv-sub">Seis agentes especialistas, coordenados pelo Orquestrador. Cada um tem uma etapa, um estado e um jeito de aprender com as suas decisões.</p>
      </header>
      <div className="pv-card" style={{ padding: 16, display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="pv-nicon"><Icon name="brain" size={20} /></span>
        <div className="pv-grow" style={{ flexBasis: 220 }}><div className="pv-title">Orquestrador PIVOO</div><div className="pv-meta">Interpreta o objetivo, planeja, delega, controla orçamento e tentativas, retoma o que parou e chama você nas decisões. Trabalha sozinho.</div></div>
        <Pill s={v.pipeline.orchestrator.state}>{v.pipeline.orchestrator.label}</Pill>
      </div>
      <div className="pv-grid">
        {v.team.map((a) => { const [s, t] = AGENT_STATE[v.statuses[a.id]] || AGENT_STATE.idle; return (
          <article key={a.id} className="pv-card" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
              <Avatar look={a.look} size={52} />
              <div className="pv-grow"><div className="pv-title" style={{ fontSize: 17 }}>{a.name}</div><div className="pv-meta" style={{ marginTop: 0 }}>{a.role}</div></div>
            </div>
            <p className="pv-meta" style={{ margin: 0, minHeight: 54 }}>{ABOUT[a.id]}</p>
            <div><Pill s={s}>{t}</Pill></div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button className={s === 'need' ? 'pv-btn pv-btn-lime' : 'pv-btn'} onClick={() => v.openStep(a.tab)}>{s === 'need' ? 'Resolver' : 'Abrir etapa'}</button>
              <button className="pv-btn pv-btn-quiet" onClick={() => v.openTraining(a.id)}>Treinar</button>
            </div>
          </article>); })}
      </div>
    </div></div>
  );
}
