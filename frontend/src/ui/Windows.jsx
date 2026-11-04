import React from 'react';
import Boneco from '../Boneco.jsx';
import { CloseButton } from './bits.jsx';

const center = { position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', zIndex: 20 };

export function Tutorial({ v }) {
  return (
    <section aria-labelledby="tut-h" className="g-panel pop" style={{ ...center, zIndex: 25, width: 'min(460px,calc(100vw - 32px))', padding: 22, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <h2 id="tut-h" className="fred" style={{ margin: 0, fontSize: 24, fontWeight: 600 }}>Bem-vindo ao seu estúdio</h2>
      <p style={{ margin: 0, fontSize: 15, lineHeight: 1.5 }}>Aqui seis agentes produzem vídeos de produto com você. Cada um cuida de uma etapa, e quem mostra o <strong style={{ background: '#D5F45B', border: '1px solid #D4DAE4', borderRadius: 999, padding: '0 7px' }}>!</strong> precisa de você.</p>
      <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 8, font: '700 14px/1.3 Nunito Sans,sans-serif' }}>
        <li style={{ display: 'flex', gap: 8, alignItems: 'center' }}><span className="kbd">W</span><span className="kbd">A</span><span className="kbd">S</span><span className="kbd">D</span> ou clique no chão para andar</li>
        <li style={{ display: 'flex', gap: 8, alignItems: 'center' }}><span className="kbd">E</span> perto de alguém para conversar</li>
        <li style={{ display: 'flex', gap: 8, alignItems: 'center' }}><span className="kbd">Esc</span> fecha qualquer janela</li>
      </ul>
      <p className="g-muted" style={{ margin: 0, fontSize: 13 }}>Pressa? Os botões do topo e a equipe no canto abrem cada etapa direto, sem andar.{v.mode === 'simulated' ? ' Modo DEMO ligado: nada é cobrado e as imagens são de exemplo.' : ''}</p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button className="g-btn g-lime" onClick={v.tutGo}>Começar agora</button>
        <button className="g-btn" onClick={v.tutClose}>Explorar primeiro</button>
      </div>
    </section>
  );
}

export function DialogWindow({ v }) {
  const d = v.dlg;
  return (
    <section role="dialog" aria-labelledby="dlg-name" className="g-panel popb" style={{ position: 'absolute', left: '50%', bottom: 20, transform: 'translateX(-50%)', zIndex: 20, width: 'min(760px,calc(100vw - 24px))', padding: 16, display: 'flex', gap: 16, alignItems: 'flex-start' }}>
      <div style={{ flex: 'none', width: 92, height: 92, borderRadius: 18, background: d.bg, border: '1px solid #D4DAE4', display: 'grid', placeItems: 'end center', overflow: 'hidden' }}>
        <Boneco look={d.look} anim={d.anim} crop size={84} />
      </div>
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <h2 id="dlg-name" className="fred" style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>{d.name}</h2>
          <span style={{ font: '800 12px/1 Nunito Sans,sans-serif', padding: '4px 8px', borderRadius: 999, background: '#17234B', color: '#fff' }}>{d.role}</span>
          <span style={{ flex: 1 }} />
          <CloseButton onClick={v.closeWin} label="Fechar conversa" />
        </div>
        <p style={{ margin: 0, fontSize: 16, lineHeight: 1.5, fontWeight: 600 }}>{d.line}</p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {d.opts.map((o, k) => <button key={k} className={o.cls} onClick={o.act}>{o.label}</button>)}
        </div>
      </div>
    </section>
  );
}

export function BoardWindow({ v }) {
  const label = { received: 'Preparando o produto', awaiting_references: 'Faltam fotos', validated: 'Direção', scripted: 'Direção', producing: 'Em produção',
    editing: 'Montando', awaiting_final_review: 'Pronto para revisar', completed: 'Exportado', paused: 'Pausada', failed: 'Falhou', cancelled: 'Cancelada' };
  return (
    <section role="dialog" aria-labelledby="brd-h" className="g-panel pop" style={{ ...center, width: 'min(600px,calc(100vw - 24px))', maxHeight: 'calc(100vh - 32px)', overflow: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <h2 id="brd-h" className="fred" style={{ margin: 0, fontSize: 22, fontWeight: 600, flex: 1 }}>Quadro de produções</h2>
        <CloseButton onClick={v.closeWin} label="Fechar quadro" />
      </div>
      {v.productions.length === 0 && <p className="g-muted" style={{ margin: 0 }}>Nenhuma produção ainda. Comece com a Nina.</p>}
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {v.productions.map((p) => (
          <li key={p.id} className="g-card" style={{ padding: 12, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', outline: p.current ? '3px solid #D5F45B' : 'none' }}>
            <div style={{ flex: 1, minWidth: 180, display: 'flex', flexDirection: 'column', gap: 2 }}>
              <strong style={{ fontSize: 15 }}>{p.name || p.id}</strong>
              <span className="g-muted" style={{ fontSize: 13 }}>{label[p.status] || p.label}{p.mode === 'simulated' ? ' · DEMO' : ''} · {new Date(p.created_at).toLocaleDateString('pt-BR')}</span>
            </div>
            {p.current ? <button className="g-btn g-lime g-sm" onClick={v.boardOpenProd}>Abrir</button> : <button className="g-btn g-sm" onClick={p.open}>Trabalhar nesta</button>}
          </li>
        ))}
      </ul>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', borderTop: '2px dashed #D8CDB9', paddingTop: 14 }}>
        <button className="g-btn g-lime" onClick={v.newProd}>Nova produção</button>
        <span className="g-muted" style={{ fontSize: 13, flex: 1, minWidth: 200 }}>{v.newProdHint}</span>
      </div>
    </section>
  );
}

export function CustomWindow({ v }) {
  return (
    <section role="dialog" aria-labelledby="cus-h" className="g-panel" style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', zIndex: 20, width: 'min(420px,calc(100vw - 28px))', maxHeight: 'calc(100vh - 28px)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: '16px 16px 10px', display: 'flex', alignItems: 'center', gap: 12, borderBottom: '1px solid #D4DAE4', background: '#F7F8FA' }}>
        <div style={{ width: 58, height: 58, borderRadius: 14, background: '#fff', border: '1px solid #D4DAE4', display: 'grid', placeItems: 'end center', overflow: 'hidden', flex: 'none' }}>
          <Boneco look={v.look} anim="happy" crop size={54} />
        </div>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <h2 id="cus-h" className="fred" style={{ margin: 0, fontSize: 21, fontWeight: 600 }}>Meu setup</h2>
          <span className="g-muted" style={{ fontSize: 13, fontWeight: 700 }}>As mudanças aparecem na hora no escritório.</span>
        </div>
        <CloseButton onClick={v.closeWin} label="Fechar personalização" />
      </div>
      <div role="tablist" aria-label="Personalizar" style={{ display: 'flex', gap: 4, padding: '10px 12px 0', flexWrap: 'wrap' }}>
        {v.ctabs.map((ct) => <button key={ct.id} role="tab" className="g-tab" aria-selected={ct.sel} onClick={ct.pick} style={{ padding: '0 12px' }}>{ct.label}</button>)}
      </div>
      <div style={{ padding: '14px 16px 18px', overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
        {v.cgroups.map((cg) => (
          <div key={cg.label} role="group" aria-label={cg.label} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span className="g-label">{cg.label}</span>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {cg.opts.map((co) => co.type === 'swatch'
                ? <button key={co.label} className="sw" aria-pressed={co.sel} aria-label={co.label} title={co.label} onClick={co.pick} style={{ background: co.color }} />
                : <button key={co.label} className="g-chip" aria-pressed={co.sel} onClick={co.pick}>{co.label}</button>)}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
