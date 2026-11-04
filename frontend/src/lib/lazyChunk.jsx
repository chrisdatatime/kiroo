import React from 'react';

// Pedaços carregados sob demanda (Phaser, home, chat, preferências...) mudam de nome a cada build.
// Uma aba aberta antes do build ainda pede o arquivo antigo, que não existe mais: o import falha.
// Aqui: na falha, recarrega a página UMA vez (a página nova já conhece os nomes novos). Se falhar de novo,
// o erro sobe para o AppBoundary, que mostra um aviso com botão em vez de deixar a tela vazia.
const FLAG = 'bc.chunkReload';

export function lazyChunk(load) {
  return React.lazy(() => load().then((m) => {
    try { sessionStorage.removeItem(FLAG); } catch { /* sem storage */ }
    return m;
  }, (err) => {
    let already = false;
    try { already = Date.now() - Number(sessionStorage.getItem(FLAG) || 0) < 30000; sessionStorage.setItem(FLAG, String(Date.now())); } catch { already = true; }
    if (!already) {
      window.location.reload();
      return new Promise(() => {}); // segura o Suspense até a página recarregar
    }
    throw err;
  }));
}

export class AppBoundary extends React.Component {
  constructor(p) { super(p); this.state = { err: null }; }
  static getDerivedStateFromError(err) { return { err }; }
  componentDidCatch(err, info) { console.error('Pivoo: erro na interface', err, info && info.componentStack); }
  render() {
    if (!this.state.err) return this.props.children;
    return (
      <div role="alert" style={{ position: 'fixed', inset: 0, display: 'grid', placeItems: 'center', padding: 16, background: '#FBF7EE', fontFamily: "'Geist Variable', system-ui, sans-serif", color: '#17234B' }}>
        <div style={{ maxWidth: 420, textAlign: 'center', display: 'flex', flexDirection: 'column', gap: 12, alignItems: 'center' }}>
          <h1 style={{ margin: 0, font: "900 28px/1.1 'Nunito Sans', sans-serif", letterSpacing: '-.03em' }}>Algo travou por aqui</h1>
          <p style={{ margin: 0, color: '#646C86' }}>Seu trabalho está salvo no servidor. Recarregar a página costuma resolver; se o estúdio acabou de ser atualizado, é isso mesmo.</p>
          <button type="button" className="g-btn g-lime" onClick={() => window.location.reload()}>Recarregar</button>
        </div>
      </div>
    );
  }
}
