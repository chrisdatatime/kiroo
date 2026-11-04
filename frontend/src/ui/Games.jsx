import React from 'react';
import Boneco from '../Boneco.jsx';
import { CloseButton } from './bits.jsx';
import { tttResult, tttAiMove, damasInitial, damasMoves, damasApply, damasAiMove, damasResult, rc, sideOf, isKing } from '../game/minigames.js';

// Mesa de jogos: passatempo enquanto os agentes trabalham. Um agente livre é o adversário.
const center = { position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', zIndex: 22 };
const LS = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* sem armazenamento */ } },
};
const COLS = 'ABCDEFGH';

function useScore(key) {
  const [score, setScore] = React.useState(() => LS.get(key, { voce: 0, agente: 0, empate: 0 }));
  const add = (k) => setScore((s) => { const n = { ...s, [k]: s[k] + 1 }; LS.set(key, n); return n; });
  return [score, add];
}

function Velha({ rival }) {
  const [b, setB] = React.useState(Array(9).fill(null));
  const [score, add] = useScore('bc.score.velha');
  const res = tttResult(b);
  const counted = React.useRef(false);
  React.useEffect(() => {
    if (res && !counted.current) { counted.current = true; add(res.who === 'X' ? 'voce' : res.who === 'O' ? 'agente' : 'empate'); }
  }, [res]); // eslint-disable-line react-hooks/exhaustive-deps
  const play = (k) => {
    if (b[k] || res) return;
    const nb = b.slice(); nb[k] = 'X';
    if (!tttResult(nb)) { const ai = tttAiMove(nb, 'O', 0.7); if (ai >= 0) nb[ai] = 'O'; }
    setB(nb);
  };
  const reset = () => { counted.current = false; setB(Array(9).fill(null)); };
  const msg = !res ? 'Sua vez: você é o X.' : res.who === 'X' ? 'Você venceu!' : res.who === 'O' ? `${rival.name} venceu.` : 'Deu velha (empate).';
  return (
    <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'flex-start' }}>
      <div role="grid" aria-label="Jogo da velha" style={{ display: 'grid', gridTemplateColumns: 'repeat(3,76px)', gap: 8 }}>
        {b.map((v, k) => {
          const win = res && res.line.includes(k);
          return (
            <button key={k} className="g-pick" onClick={() => play(k)} disabled={!!v || !!res}
              aria-label={`Casa ${Math.floor(k / 3) + 1}, ${(k % 3) + 1}: ${v === 'X' ? 'seu X' : v === 'O' ? 'O de ' + rival.name : 'vazia'}`}
              style={{ width: 76, height: 76, display: 'grid', placeItems: 'center', background: win ? '#D5F45B' : undefined, opacity: 1 }}>
              <span className="fred" style={{ fontSize: 40, fontWeight: 700, color: v === 'X' ? '#17234B' : '#E46F5A' }}>{v || ''}</span>
            </button>
          );
        })}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, minWidth: 200 }}>
        <strong role="status" className="fred" style={{ fontSize: 19, fontWeight: 600 }}>{msg}</strong>
        <span className="g-muted" style={{ fontSize: 13 }}>Placar: você {score.voce} · {rival.name} {score.agente} · empates {score.empate}</span>
        <button className="g-btn g-lime" onClick={reset}>Nova partida</button>
      </div>
    </div>
  );
}

function Damas({ rival }) {
  const [b, setB] = React.useState(() => damasInitial());
  const [turn, setTurn] = React.useState('w');
  const [sel, setSel] = React.useState(null);
  const [last, setLast] = React.useState(null);
  const [score, add] = useScore('bc.score.damas');
  const result = damasResult(b, turn);
  const counted = React.useRef(false);
  const moves = React.useMemo(() => (turn === 'w' && !result ? damasMoves(b, 'w') : []), [b, turn, result]);
  const mustCapture = moves.length > 0 && moves[0].caps.length > 0;

  React.useEffect(() => {
    if (result && !counted.current) { counted.current = true; add(result === 'w' ? 'voce' : 'agente'); }
    if (turn !== 'b' || result) return undefined;
    const t = setTimeout(() => {
      const m = damasAiMove(b, 'b');
      if (m) { setB(damasApply(b, m)); setLast(m); }
      setTurn('w');
    }, 650);
    return () => clearTimeout(t);
  }, [turn, b, result]); // eslint-disable-line react-hooks/exhaustive-deps

  const fromSet = new Set(moves.map((m) => m.from));
  const targets = sel !== null ? moves.filter((m) => m.from === sel) : [];
  const click = (i) => {
    if (turn !== 'w' || result) return;
    if (fromSet.has(i)) { setSel(i); return; }
    const m = targets.find((x) => x.to === i);
    if (m) { setB(damasApply(b, m)); setLast(m); setSel(null); setTurn('b'); }
  };
  const reset = () => { counted.current = false; setB(damasInitial()); setTurn('w'); setSel(null); setLast(null); };
  const msg = result ? (result === 'w' ? 'Você venceu!' : `${rival.name} venceu.`)
    : turn === 'b' ? `${rival.name} está pensando…` : mustCapture ? 'Captura obrigatória: pegue o máximo de peças possível.' : sel !== null ? 'Escolha a casa de destino.' : 'Sua vez: escolha uma peça clara.';

  return (
    <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'flex-start' }}>
      <div role="grid" aria-label="Tabuleiro de damas" style={{ display: 'grid', gridTemplateColumns: 'repeat(8,44px)', border: '1px solid #D4DAE4', borderRadius: 8, overflow: 'hidden' }}>
        {b.map((p, i) => {
          const [r, c] = rc(i), dark = (r + c) % 2 === 1;
          const isTarget = targets.some((m) => m.to === i);
          const isLast = last && (last.from === i || last.to === i);
          const label = `${COLS[c]}${8 - r}: ${p ? (sideOf(p) === 'w' ? 'sua ' : 'de ' + rival.name + ', ') + (isKing(p) ? 'dama' : 'peça') : 'vazia'}${isTarget ? ', destino possível' : ''}`;
          return (
            <button key={i} onClick={() => click(i)} disabled={!dark} aria-label={label} aria-pressed={sel === i}
              style={{ width: 44, height: 44, border: 0, padding: 0, display: 'grid', placeItems: 'center', cursor: dark ? 'pointer' : 'default',
                background: !dark ? '#F3E3C7' : sel === i ? '#D5F45B' : isTarget ? '#9DD86A' : isLast ? '#8D6E50' : '#7A5A3E',
                outline: fromSet.has(i) && sel !== i ? '2px dashed #D5F45B' : 'none', outlineOffset: -4 }}>
              {p && <span aria-hidden="true" style={{ width: 32, height: 32, borderRadius: '50%', border: '1px solid #D4DAE4', display: 'grid', placeItems: 'center',
                background: sideOf(p) === 'w' ? '#F7F8FA' : '#E46F5A', boxShadow: '0 1px 2px rgba(31, 36, 48, .08)', font: '900 14px/1 Nunito Sans,sans-serif', color: '#17234B' }}>{isKing(p) ? 'D' : ''}</span>}
            </button>
          );
        })}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, minWidth: 200, maxWidth: 260 }}>
        <strong role="status" className="fred" style={{ fontSize: 18, fontWeight: 600 }}>{msg}</strong>
        <span className="g-muted" style={{ fontSize: 13 }}>Placar: você {score.voce} · {rival.name} {score.agente}</span>
        <span className="g-muted" style={{ fontSize: 12.5, lineHeight: 1.45 }}>Regras brasileiras: captura obrigatória, vale a jogada que pega mais peças, peão captura para trás, dama anda e captura à distância. “D” marca as damas.</span>
        <button className="g-btn g-lime" onClick={reset}>Nova partida</button>
      </div>
    </div>
  );
}

export default function GamesWindow({ v }) {
  const [tab, setTab] = React.useState(() => LS.get('bc.game.tab', 'velha'));
  const pick = (t) => { setTab(t); LS.set('bc.game.tab', t); };
  const g = v.games;
  return (
    <section role="dialog" aria-labelledby="games-h" className="g-panel pop" style={{ ...center, width: 'min(700px,calc(100vw - 24px))', maxHeight: 'calc(100vh - 32px)', overflow: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ width: 44, height: 44, borderRadius: 12, background: g.rival.look.shirt, border: '1px solid #D4DAE4', display: 'grid', placeItems: 'end center', overflow: 'hidden', flex: 'none' }}><Boneco look={g.rival.look} crop size={40} /></span>
        <div style={{ flex: 1 }}>
          <h2 id="games-h" className="fred" style={{ margin: 0, fontSize: 22, fontWeight: 600 }}>Mesa de jogos</h2>
          <span className="g-muted" style={{ fontSize: 13 }}>Adversário: {g.rival.name} ({g.rival.role}), que está livre agora.</span>
        </div>
        <CloseButton onClick={v.closeWin} label="Fechar mesa de jogos" />
      </div>
      {g.needYou && (
        <div role="alert" style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', padding: '10px 12px', borderRadius: 12, background: '#F2FBD9', border: '1px solid #D4DAE4' }}>
          <strong style={{ flex: 1, fontSize: 14 }}>{g.needYou.text}</strong>
          <button className="g-btn g-lime g-sm" onClick={g.needYou.go}>{g.needYou.label}</button>
        </div>
      )}
      {!g.needYou && g.working && <span className="g-muted" style={{ fontSize: 13 }}>{g.working} O jogo fica salvo enquanto você estiver nesta tela.</span>}
      <div role="tablist" aria-label="Jogos" style={{ display: 'flex', gap: 6 }}>
        <button role="tab" className="g-chip" aria-selected={tab === 'velha'} aria-pressed={tab === 'velha'} onClick={() => pick('velha')}>Jogo da Velha</button>
        <button role="tab" className="g-chip" aria-selected={tab === 'damas'} aria-pressed={tab === 'damas'} onClick={() => pick('damas')}>Damas</button>
      </div>
      {tab === 'velha' ? <Velha rival={g.rival} /> : <Damas rival={g.rival} />}
    </section>
  );
}
