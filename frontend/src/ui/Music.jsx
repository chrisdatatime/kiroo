import React from 'react';
import { CloseButton } from './bits.jsx';
import { getJSON, post, readFile } from '../engine/api.js';

// Trilhas, na sala da Lia. Em alta é só referência; o que entra no vídeo vem da Biblioteca Kiroo ou de Minhas músicas.
// A Lia guarda a escolha; o Beto aplica a trilha uma única vez, na montagem.
const MODES = [['auto', 'Escolha por mim'], ['pick', 'Quero escolher'], ['mine', 'Usar minha música'], ['none', 'Sem música']];
const secs = (n) => { const s = Math.round(n || 0); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };

function Track({ t, sel, onPick, onFav, children }) {
  return (
    <article className="g-card" style={{ padding: 10, display: 'grid', gap: 6, background: sel ? '#FFFFFF' : '#fff' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <strong style={{ flex: 1, minWidth: 140 }}>{t.title}</strong>
        <button className="g-btn g-sm" aria-pressed={!!t.favorite} onClick={onFav}>{t.favorite ? 'Favorita' : 'Favoritar'}</button>
        {onPick && <button className={sel ? 'g-btn g-sm g-lime' : 'g-btn g-sm'} onClick={onPick}>{sel ? 'Escolhida' : 'Escolher'}</button>}
      </div>
      <div className="g-muted" style={{ fontSize: 12.5, fontWeight: 700 }}>{[t.mood, t.genre, t.energy && 'energia ' + t.energy, t.bpm && Math.round(t.bpm) + ' BPM', t.duration_s && secs(t.duration_s)].filter(Boolean).join(' · ')}</div>
      <div style={{ fontSize: 12.5 }}>Origem: {t.origin} · Uso: {t.license || t.usage_terms}</div>
      {t.reason && <div style={{ fontSize: 13, fontWeight: 700 }}>{t.reason}</div>}
      <audio controls preload="none" src={'/api/music/file/' + t.id} style={{ width: '100%', height: 36 }} aria-label={'Prévia de ' + t.title} />
      {children}
    </article>
  );
}

export default function MusicWindow({ v }) {
  const P = v.P;
  const [lib, setLib] = React.useState(null);
  const [tab, setTab] = React.useState('kiroo');
  const [sug, setSug] = React.useState([]);
  const cur = (P && P.edit && P.edit.music_choice) || { mode: 'auto', track_id: null, start_s: 0, volume_db: null, fade_in_s: 0.3, fade_out_s: 0.8, beat_sync: true };
  const [choice, setChoice] = React.useState(cur);
  const [err, setErr] = React.useState(''); const [msg, setMsg] = React.useState(''); const [busy, setBusy] = React.useState(false);
  const [up, setUp] = React.useState({ title: '', collection: '', mood: '', bpm: '', reference_url: '', authorized: false, file: null });
  const load = () => getJSON('/api/music').then(setLib).catch((e) => setErr(e.message));
  React.useEffect(() => {
    load();
    post('/api/music/suggest', { category: P ? P.product.category : '', name: P ? P.product.name : '', style: P && P.edit ? P.edit.style : 'dinamico' }).then((r) => setSug(r.items)).catch(() => {});
  }, []);
  const fav = async (t) => { await post('/api/music/favorite', { id: t.id, on: !t.favorite }); load(); };
  const pick = (t) => { setChoice({ ...choice, mode: t.source === 'mine' ? 'mine' : 'pick', track_id: t.id, start_s: t.start_s || 0 }); };
  const apply = async () => {
    setBusy(true); setErr(''); setMsg('');
    try {
      let body = choice;
      if (choice.mode === 'auto' && sug[0]) body = { ...choice, mode: 'pick', track_id: sug[0].id };
      await post(`/api/productions/${P.id}/music`, body);
      setMsg(v.delivery && v.delivery['final.mp4'] ? 'Remontando com a nova trilha. As cenas continuam as mesmas, sem custo de geração.' : 'Trilha guardada. O Beto aplica na montagem.');
      v.afterMusic(body);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const send = async () => {
    setBusy(true); setErr(''); setMsg('');
    try {
      const data = await readFile(up.file);
      const t = await post('/api/music/upload', { ...up, name: up.file.name, data, file: undefined });
      setUp({ title: '', collection: '', mood: '', bpm: '', reference_url: '', authorized: false, file: null }); await load(); pick({ ...t, source: 'mine' }); setMsg('Música guardada no seu espaço privado.');
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const selected = lib && choice.track_id ? [...lib.kiroo, ...lib.mine].find((t) => t.id === choice.track_id) : null;
  const video = v.delivery && v.delivery['final.mp4'];

  return (
    <section role="dialog" aria-labelledby="mu-h" className="g-panel" style={{ position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', zIndex: 24, width: 'min(920px,calc(100vw - 24px))', height: 'min(720px,calc(100vh - 24px))', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <header style={{ padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 10, borderBottom: '1px solid #E7E7E4', background: '#F2F2EF' }}>
        <h2 id="mu-h" className="fred" style={{ margin: 0, fontSize: 20, flex: 1 }}>Trilhas da Lia</h2>
        <CloseButton onClick={v.closeWin} label="Fechar trilhas" />
      </header>
      {(err || msg) && <div role={err ? 'alert' : 'status'} style={{ margin: '8px 14px 0', padding: '8px 12px', borderRadius: 10, fontSize: 13, fontWeight: 700, background: err ? '#FFE1DC' : '#E3F5DC' }}>{err || msg}</div>}
      <div style={{ flex: 1, overflowY: 'auto', padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {P ? (
          <div className="g-card" style={{ padding: 10, display: 'grid', gap: 8 }}>
            <strong>Trilha de “{P.product.name.slice(0, 50)}”</strong>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{MODES.map(([m, l]) => <button key={m} className="g-chip" aria-pressed={choice.mode === m} onClick={() => { setChoice({ ...choice, mode: m, track_id: m === 'none' || m === 'auto' ? null : choice.track_id }); if (m === 'mine') setTab('mine'); if (m === 'pick') setTab('kiroo'); }}>{l}</button>)}</div>
            {choice.mode === 'auto' && (sug.length ? <p style={{ margin: 0, fontSize: 13.5 }}>Sugestão: <strong>{sug[0].title}</strong>. {sug[0].reason}</p> : <p style={{ margin: 0, fontSize: 13.5 }}>Sem sugestão disponível.</p>)}
            {choice.mode === 'platform' && <p style={{ margin: 0, fontSize: 13.5 }}>O vídeo sai sem trilha. Adicione “{choice.platform_title}” no editor da plataforma, se ela estiver disponível lá para sua conta.</p>}
            {selected && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 8, fontSize: 13, fontWeight: 700 }}>
                <span style={{ gridColumn: '1/-1' }}>Selecionada: {selected.title}</span>
                <label>Início do trecho: {secs(choice.start_s)}<input type="range" min="0" max={Math.max(0, (selected.duration_s || 32) - 5)} step="0.5" value={choice.start_s || 0} onChange={(e) => setChoice({ ...choice, start_s: +e.target.value })} style={{ width: '100%' }} /></label>
                <label>Volume: {choice.volume_db == null ? 'padrão do estilo' : choice.volume_db + ' dB'}<input type="range" min="-24" max="-3" step="1" value={choice.volume_db == null ? -9 : choice.volume_db} onChange={(e) => setChoice({ ...choice, volume_db: +e.target.value })} style={{ width: '100%' }} /></label>
                <label>Fade-in: {choice.fade_in_s}s<input type="range" min="0" max="3" step="0.1" value={choice.fade_in_s} onChange={(e) => setChoice({ ...choice, fade_in_s: +e.target.value })} style={{ width: '100%' }} /></label>
                <label>Fade-out: {choice.fade_out_s}s<input type="range" min="0" max="4" step="0.1" value={choice.fade_out_s} onChange={(e) => setChoice({ ...choice, fade_out_s: +e.target.value })} style={{ width: '100%' }} /></label>
                <label style={{ gridColumn: '1/-1' }}><input type="checkbox" checked={choice.beat_sync} disabled={!selected.bpm} onChange={(e) => setChoice({ ...choice, beat_sync: e.target.checked })} /> Sincronizar cortes com a batida{selected.bpm ? '' : ' (informe o BPM da música para ativar)'}</label>
              </div>
            )}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <button className="g-btn g-lime" disabled={busy} onClick={apply}>{video ? 'Aplicar e remontar (sem custo)' : 'Usar nesta produção'}</button>
              <span className="g-muted" style={{ fontSize: 12.5 }}>A escolha desta produção tem prioridade sobre sugestões automáticas.</span>
            </div>
            {video && <video src={video} controls style={{ width: 200, maxWidth: '100%', borderRadius: 10, border: '1px solid #E7E7E4' }} aria-label="Prévia do vídeo com a trilha" />}
            <p className="g-muted" style={{ margin: 0, fontSize: 12.5 }}>O formato atual não tem narração, então a redução da música durante a fala ainda não tem efeito.</p>
          </div>
        ) : <p style={{ margin: 0 }}>Abra uma produção para aplicar uma trilha. Você já pode ouvir e organizar as músicas.</p>}

        <div role="tablist" style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {[['alta', 'Em alta'], ['kiroo', 'Biblioteca Kiroo'], ['mine', 'Minhas músicas']].map(([id, l]) => <button key={id} role="tab" aria-selected={tab === id} className="g-tab" style={{ padding: '0 12px' }} onClick={() => setTab(id)}>{l}</button>)}
          <span style={{ flex: 1 }} />
          <button className="g-btn g-sm" onClick={() => v.openTraining('lia')}>Preferências musicais</button>
        </div>
        {!lib && !err && <p>Carregando…</p>}
        {lib && tab === 'alta' && (
          <>
            <p style={{ margin: 0, fontSize: 13.5 }}><strong>Curadoria manual</strong>{lib.trends.updated_at ? `, atualizada em ${lib.trends.updated_at}` : ''}. Não há integração com as plataformas. Estar em alta não comprova autorização de uso comercial, e estas faixas nunca são incorporadas pelo Kiroo.</p>
            {lib.trends.items.length === 0 && <p className="g-card" style={{ margin: 0, padding: 12 }}>Nenhuma tendência cadastrada. O Kiroo não inventa rankings: a lista só aparece quando alguém faz a curadoria com fonte e data.</p>}
            {lib.trends.items.map((t, k) => (
              <article key={k} className="g-card" style={{ padding: 10, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
                <div style={{ flex: 1, minWidth: 200 }}><strong>{t.title}</strong>{t.artist ? ' · ' + t.artist : ''}<div className="g-muted" style={{ fontSize: 12.5, fontWeight: 700 }}>{t.platform} · {t.region} · fonte: {t.source} · verificado em {t.checked_at}</div></div>
                {P && <button className="g-btn g-sm" onClick={() => setChoice({ ...choice, mode: 'platform', track_id: null, platform_title: t.title })}>Exportar sem trilha e adicionar lá</button>}
              </article>
            ))}
          </>
        )}
        {lib && tab === 'kiroo' && lib.kiroo.map((t) => <Track key={t.id} t={{ ...t, reason: (sug.find((s) => s.id === t.id) || {}).reason }} sel={choice.track_id === t.id} onPick={P ? () => pick(t) : null} onFav={() => fav(t)} />)}
        {lib && tab === 'mine' && (
          <>
            <fieldset className="g-card" style={{ padding: 10, display: 'grid', gap: 8 }}>
              <legend style={{ fontWeight: 800, padding: '0 6px' }}>Enviar música</legend>
              <input aria-label="Arquivo de áudio" type="file" accept=".mp3,.wav,.m4a,.aac,.ogg,.flac" onChange={(e) => setUp({ ...up, file: e.target.files[0] || null })} />
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 8 }}>
                <input aria-label="Nome" className="g-field" placeholder="Nome" value={up.title} onChange={(e) => setUp({ ...up, title: e.target.value })} />
                <input aria-label="Coleção" className="g-field" placeholder="Coleção" value={up.collection} onChange={(e) => setUp({ ...up, collection: e.target.value })} />
                <input aria-label="Clima" className="g-field" placeholder="Clima" value={up.mood} onChange={(e) => setUp({ ...up, mood: e.target.value })} />
                <input aria-label="BPM" className="g-field" placeholder="BPM (se souber)" inputMode="numeric" value={up.bpm} onChange={(e) => setUp({ ...up, bpm: e.target.value.replace(/\D/g, '') })} />
              </div>
              <input aria-label="Link de referência" className="g-field" placeholder="Link de referência (só anotação: o Kiroo não baixa áudio de links)" value={up.reference_url} onChange={(e) => setUp({ ...up, reference_url: e.target.value })} />
              <label style={{ fontSize: 13.5, fontWeight: 700 }}><input type="checkbox" checked={up.authorized} onChange={(e) => setUp({ ...up, authorized: e.target.checked })} /> Tenho autorização para usar esta música em vídeos comerciais.</label>
              <div><button className="g-btn g-lime" disabled={busy || !up.file || !up.authorized} onClick={send}>Enviar</button></div>
            </fieldset>
            {lib.mine.length === 0 && <p className="g-muted" style={{ margin: 0 }}>Nenhuma música enviada. Só a sua conta vê as músicas daqui.</p>}
            {lib.mine.map((t) => (
              <Track key={t.id} t={t} sel={choice.track_id === t.id} onPick={P ? () => pick(t) : null} onFav={() => fav(t)}>
                <div style={{ fontSize: 12.5 }}>{t.collection ? 'Coleção: ' + t.collection + ' · ' : ''}{t.reference_url ? 'Referência: ' + t.reference_url : ''}</div>
                <div><button className="g-btn g-sm" onClick={async () => { await post('/api/music/delete', { id: t.id }); if (choice.track_id === t.id) setChoice({ ...choice, mode: 'auto', track_id: null }); load(); }}>Excluir</button></div>
              </Track>
            ))}
          </>
        )}
      </div>
    </section>
  );
}
