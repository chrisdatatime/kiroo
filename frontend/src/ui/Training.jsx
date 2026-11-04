import React from 'react';
import Boneco from '../Boneco.jsx';
import { CloseButton } from './bits.jsx';
import { getJSON, post, readFile } from '../engine/api.js';

// Treinar agente: configuração versionada usada nas chamadas reais. Rascunho → teste → ativação. Não retreina modelo.
const TABS = [['jeito', 'Jeito de trabalhar'], ['refs', 'Referências'], ['exemplos', 'Exemplos e correções'], ['teste', 'Testar agente'], ['historico', 'Histórico']];
const TASKS = {
  nina: 'Conferir a ficha de uma garrafa térmica azul com duas fotos.', theo: 'Escrever a primeira cena de um vídeo de um copo com alça.', iris: 'Criar a imagem de abertura de um copo azul sobre a bancada.',
  lia: 'Animar a imagem de um copo sendo levantado da bancada.', rui: 'Conferir uma imagem em que a tampa do copo parece diferente da foto oficial.', beto: 'Montar três cenas de um produto de cozinha.', _marca: 'Escrever a primeira cena de um vídeo de produto.',
};
const money = (n) => 'US$ ' + Number(n || 0).toFixed(4).replace('.', ',');
const when = (s) => { try { return new Date(s).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }); } catch { return s; } };

function Field({ id, label, value, onChange, rows = 2 }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      <label className="g-label" htmlFor={id} style={{ textTransform: 'none', fontSize: 13.5, letterSpacing: 0, color: '#17234B' }}>{label}</label>
      <textarea id={id} className="g-field" rows={rows} value={value || ''} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

export default function TrainingWindow({ v }) {
  const [agent, setAgent] = React.useState(v.trainAgent);
  const [d, setD] = React.useState(null);
  const [tab, setTab] = React.useState('jeito');
  const [form, setForm] = React.useState(null);
  const [err, setErr] = React.useState('');
  const [msg, setMsg] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [ref, setRef] = React.useState({ title: '', use: '', text: '', file: null });
  const [ex, setEx] = React.useState({ kind: 'do', text: '', bad: '', good: '' });
  const [task, setTask] = React.useState(TASKS[v.trainAgent] || '');
  const [test, setTest] = React.useState(null);
  const [confirmPaid, setConfirmPaid] = React.useState(false);
  const [note, setNote] = React.useState('');
  const [compare, setCompare] = React.useState(null);

  const apply = (view) => { setD(view); setForm({ ...view.draft, edit_style: (view.draft.settings || {}).edit_style || '', music: (view.draft.settings || {}).music || {} }); };
  React.useEffect(() => { setD(null); setTest(null); setTask(TASKS[agent] || ''); getJSON('/api/training/' + agent).then(apply).catch((e) => setErr(e.message)); }, [agent]);
  const call = async (op, body = {}, done) => {
    setBusy(true); setErr(''); setMsg('');
    try { const r = await post(`/api/training/${agent}/${op}`, body); if (r.view) { apply(r.view); setTest(r.test); } else apply(r); if (done) done(); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const set = (k) => (val) => setForm((f) => ({ ...f, [k]: val }));
  const saveFields = () => call('save', form, () => setMsg('Rascunho salvo. Ele só passa a valer depois de testado e ativado.'));
  const who = agent === '_marca' ? { name: 'Base da marca', role: 'Regras compartilhadas', look: null } : v.team.find((a) => a.id === agent);

  return (
    <section role="dialog" aria-labelledby="tr-h" className="g-panel" style={{ position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', zIndex: 24, width: 'min(920px,calc(100vw - 24px))', height: 'min(720px,calc(100vh - 24px))', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <header style={{ padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 12, borderBottom: '2.5px solid #17234B', background: '#F6EEDD', flexWrap: 'wrap' }}>
        {who && who.look && <span aria-hidden="true" style={{ width: 48, height: 48, borderRadius: 12, background: who.look.shirt, border: '2px solid #17234B', overflow: 'hidden', display: 'grid', placeItems: 'end center' }}><Boneco look={who.look} crop size={42} /></span>}
        <div style={{ flex: 1, minWidth: 180 }}>
          <h2 id="tr-h" className="fred" style={{ margin: 0, fontSize: 20 }}>{agent === '_marca' ? 'Base da marca' : 'Treinar ' + (who ? who.name : '')}</h2>
          <span className="g-muted" style={{ fontSize: 12.5, fontWeight: 700 }}>{d ? d.usage : ''}</span>
        </div>
        {d && <span className="g-card" style={{ padding: '4px 10px', fontSize: 12.5, fontWeight: 800 }}>{d.active_version ? 'Ativa: versão ' + d.active_version : 'Ativa: padrão da função'}{d.dirty ? ' · rascunho pendente' : ''}</span>}
        <button className="g-btn g-sm" onClick={() => setAgent(agent === '_marca' ? v.trainAgent : '_marca')}>{agent === '_marca' ? 'Voltar ao agente' : 'Regras da marca'}</button>
        <CloseButton onClick={v.closeWin} label="Fechar treinamento" />
      </header>
      <div role="tablist" style={{ display: 'flex', gap: 4, padding: '8px 10px', flexWrap: 'wrap', borderBottom: '2px solid #E2D7C3' }}>
        {TABS.map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} className="g-tab" style={{ padding: '0 12px' }} onClick={() => setTab(id)}>{label}</button>)}
      </div>
      {(err || msg) && <div role={err ? 'alert' : 'status'} style={{ margin: '8px 14px 0', padding: '8px 12px', borderRadius: 10, fontSize: 13, fontWeight: 700, background: err ? '#FFE1DC' : '#E3F5DC' }}>{err || msg}</div>}
      <div style={{ flex: 1, overflowY: 'auto', padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {!d && !err && <p>Carregando…</p>}
        {d && tab === 'jeito' && form && (
          <>
            <Field id="f-goals" label={d.questions.goals} value={form.goals} onChange={set('goals')} />
            <Field id="f-pref" label={d.questions.preferences} value={form.preferences} onChange={set('preferences')} />
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{d.suggestions.map((s) => <button key={s} className="g-chip" onClick={() => set('preferences')((form.preferences ? form.preferences + '. ' : '') + s)}>+ {s}</button>)}</div>
            <Field id="f-rest" label={d.questions.restrictions} value={form.restrictions} onChange={set('restrictions')} />
            <Field id="f-qual" label={d.questions.quality} value={form.quality} onChange={set('quality')} />
            {agent === 'beto' && v.editOptions && (
              <label style={{ display: 'flex', flexDirection: 'column', gap: 5, fontWeight: 700, fontSize: 13.5 }}>Qual estilo de edição usar por padrão nas próximas produções?
                <select className="g-field" value={form.edit_style} onChange={(e) => set('edit_style')(e.target.value)}><option value="">O padrão do Pivoo</option>{v.editOptions.styles.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}</select>
              </label>
            )}
            {agent === 'lia' && (
              <fieldset className="g-card" style={{ padding: 10, display: 'grid', gap: 8 }}>
                <legend style={{ fontWeight: 800, padding: '0 6px' }}>Preferências musicais</legend>
                <Field id="m-fav" rows={1} label="Quais estilos você prefere?" value={form.music.favorites} onChange={(x) => set('music')({ ...form.music, favorites: x })} />
                <Field id="m-av" rows={1} label="Quais gêneros evitar?" value={form.music.avoid} onChange={(x) => set('music')({ ...form.music, avoid: x })} />
                <label style={{ fontSize: 13.5, fontWeight: 700 }}>Música com voz?{' '}
                  <select value={form.music.vocal || 'tanto_faz'} onChange={(e) => set('music')({ ...form.music, vocal: e.target.value })}><option value="tanto_faz">Tanto faz</option><option value="instrumental">Só instrumental</option><option value="voz">Com voz</option></select></label>
                <label style={{ fontSize: 13.5, fontWeight: 700 }}>Intensidade{' '}
                  <select value={form.music.energy || 'tanto_faz'} onChange={(e) => set('music')({ ...form.music, energy: e.target.value })}><option value="tanto_faz">Tanto faz</option><option value="baixa">Baixa</option><option value="media">Média</option><option value="alta">Alta</option></select></label>
              </fieldset>
            )}
            <details><summary style={{ cursor: 'pointer', fontWeight: 800 }}>Opções avançadas</summary>
              <div style={{ display: 'grid', gap: 10, marginTop: 8 }}>
                <Field id="f-role" label={d.questions.role} value={form.role} onChange={set('role')} />
                <Field id="f-tone" label={d.questions.tone} value={form.tone} onChange={set('tone')} />
                <p className="g-muted" style={{ margin: 0, fontSize: 12.5 }}>Ordem de prioridade: regras obrigatórias e fatos confirmados do produto; direção desta produção; orientações do agente; base da marca.</p>
              </div>
            </details>
            <div><button className="g-btn g-lime" disabled={busy} onClick={saveFields}>Salvar rascunho</button></div>
          </>
        )}
        {d && tab === 'refs' && (
          <>
            <p style={{ margin: 0, fontWeight: 700 }}>Tem algum exemplo do resultado que você espera? Os documentos são material de consulta: não mudam as regras do sistema.</p>
            {d.draft.refs.length === 0 && <p className="g-muted" style={{ margin: 0 }}>Nenhuma referência ainda.</p>}
            {d.draft.refs.map((r) => (
              <article key={r.id} className="g-card" style={{ padding: 10, display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}><strong>{r.title}</strong><div style={{ fontSize: 13 }}>Aproveitar: {r.use || 'não informado'}</div>{r.file && !r.text && <div className="g-muted" style={{ fontSize: 12 }}>Imagem guardada; só a nota acima é enviada aos modelos.</div>}</div>
                <button className="g-btn g-sm" onClick={() => call('ref_delete', { id: r.id })}>Excluir</button>
              </article>
            ))}
            <fieldset className="g-card" style={{ padding: 10, display: 'grid', gap: 8 }}>
              <legend style={{ fontWeight: 800, padding: '0 6px' }}>Nova referência</legend>
              <Field id="r-t" rows={1} label="Nome" value={ref.title} onChange={(x) => setRef({ ...ref, title: x })} />
              <Field id="r-u" rows={1} label="O que aproveitar nela?" value={ref.use} onChange={(x) => setRef({ ...ref, use: x })} />
              <Field id="r-x" rows={3} label="Texto ou exemplo aprovado (opcional se enviar arquivo)" value={ref.text} onChange={(x) => setRef({ ...ref, text: x })} />
              <input aria-label="Arquivo de referência" type="file" accept=".txt,.md,.csv,.png,.jpg,.jpeg,.webp" onChange={async (e) => { const f = e.target.files[0]; if (f) setRef({ ...ref, file: { name: f.name, data: await readFile(f) } }); }} />
              <div><button className="g-btn g-lime" disabled={busy} onClick={() => call('ref', ref, () => setRef({ title: '', use: '', text: '', file: null }))}>Adicionar ao rascunho</button></div>
            </fieldset>
          </>
        )}
        {d && tab === 'exemplos' && (
          <>
            {d.draft.guidelines.length > 0 && <h3 className="fred" style={{ margin: 0, fontSize: 15 }}>Orientações aprendidas</h3>}
            {d.draft.guidelines.map((g) => <article key={g.id} className="g-card" style={{ padding: 10, display: 'flex', gap: 10 }}><span style={{ flex: 1 }}>{g.text}</span><button className="g-btn g-sm" onClick={() => call('remove', { key: 'guidelines', id: g.id })}>Excluir</button></article>)}
            <h3 className="fred" style={{ margin: 0, fontSize: 15 }}>Exemplos</h3>
            {d.draft.examples.length === 0 && <p className="g-muted" style={{ margin: 0 }}>Nenhum exemplo ainda.</p>}
            {d.draft.examples.map((e) => (
              <article key={e.id} className="g-card" style={{ padding: 10, display: 'flex', gap: 10 }}>
                <div style={{ flex: 1, fontSize: 13.5 }}>{e.kind === 'compare' ? <><strong>Ruim:</strong> {e.bad}<br /><strong>Desejado:</strong> {e.good}</> : <><strong>{e.kind === 'do' ? 'Faça assim:' : 'Evite isso:'}</strong> {e.text}</>}</div>
                <button className="g-btn g-sm" onClick={() => call('remove', { key: 'examples', id: e.id })}>Excluir</button>
              </article>
            ))}
            <fieldset className="g-card" style={{ padding: 10, display: 'grid', gap: 8 }}>
              <legend style={{ fontWeight: 800, padding: '0 6px' }}>Novo exemplo</legend>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{[['do', 'Faça assim'], ['avoid', 'Evite isso'], ['compare', 'Ruim × desejado']].map(([k, l]) => <button key={k} className="g-chip" aria-pressed={ex.kind === k} onClick={() => setEx({ ...ex, kind: k })}>{l}</button>)}</div>
              {ex.kind === 'compare'
                ? <><Field id="e-b" label="Como ficou ruim?" value={ex.bad} onChange={(x) => setEx({ ...ex, bad: x })} /><Field id="e-g" label="Como deveria ficar?" value={ex.good} onChange={(x) => setEx({ ...ex, good: x })} /></>
                : <Field id="e-t" label="Descreva o exemplo" value={ex.text} onChange={(x) => setEx({ ...ex, text: x })} />}
              <div><button className="g-btn g-lime" disabled={busy} onClick={() => call('example', ex, () => setEx({ kind: ex.kind, text: '', bad: '', good: '' }))}>Adicionar ao rascunho</button></div>
            </fieldset>
          </>
        )}
        {d && tab === 'teste' && (
          <>
            <p style={{ margin: 0, fontSize: 13.5 }}><strong>Mudanças no rascunho:</strong> {d.dirty ? d.changes.join(', ') : 'nenhuma; o rascunho é igual à versão ativa.'}</p>
            <Field id="t-task" rows={2} label="Qual tarefa usar no teste? A mesma tarefa vai para a versão ativa e para o rascunho." value={task} onChange={setTask} />
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <button className="g-btn g-lime" disabled={busy} onClick={() => call('test', { task })}>Comparar os pedidos (grátis)</button>
              {d.can_execute && <>
                <button className="g-btn" disabled={busy || (v.mode !== 'simulated' && !confirmPaid)} onClick={() => call('test', { task, execute: true, confirm: confirmPaid })}>Executar com o modelo de texto</button>
                {v.mode === 'simulated'
                  ? <span className="g-sim">DEMO: simulado, sem custo</span>
                  : <label style={{ fontSize: 13, fontWeight: 700 }}><input type="checkbox" checked={confirmPaid} onChange={(e) => setConfirmPaid(e.target.checked)} /> Consumo estimado: até US$ 0,02 (duas chamadas). Respeita saldo e teto do mês.</label>}
              </>}
            </div>
            {!d.can_execute && <p className="g-muted" style={{ margin: 0, fontSize: 13 }}>Este agente não chama modelo, então o teste compara o que muda na configuração.</p>}
            <p className="g-muted" style={{ margin: 0, fontSize: 12.5 }}>O teste não gera imagem nem vídeo: mostra o pedido e, ao executar, como o modelo de texto responde. Não há nota de qualidade: a comparação é sua.</p>
            {test && (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: 10 }}>
                  {[['Versão ativa', test.current_prompt, test.current_result], ['Rascunho', test.draft_prompt, test.draft_result]].map(([t, pr, re]) => (
                    <div key={t} className="g-card" style={{ padding: 10, minWidth: 0 }}><strong>{t}</strong>
                      {re && <p style={{ whiteSpace: 'pre-wrap', fontSize: 13.5, margin: '6px 0' }}>{re}</p>}
                      <details open={!re}><summary style={{ cursor: 'pointer', fontSize: 12.5, fontWeight: 800 }}>Pedido enviado</summary><pre style={{ whiteSpace: 'pre-wrap', fontSize: 11.5, margin: '6px 0 0', maxHeight: 240, overflow: 'auto' }}>{pr}</pre></details>
                    </div>
                  ))}
                </div>
                {!!test.executed && <p style={{ margin: 0, fontSize: 13, fontWeight: 700 }}>{test.simulated ? 'Simulado: nenhum modelo foi chamado, sem custo.' : `Custo estimado ${money(test.estimated_cost_usd)} · registrado ${money(test.cost_usd)}`}</p>}
              </>
            )}
            <div className="g-card" style={{ padding: 10, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <input aria-label="Nota da versão" className="g-field" style={{ flex: 1, minWidth: 200 }} placeholder="Nota desta versão (opcional)" value={note} onChange={(e) => setNote(e.target.value)} />
              <button className="g-btn g-lime" disabled={busy || !d.dirty || !d.tested} onClick={() => call('activate', { note }, () => { setMsg('Versão ativada. Vale para as próximas produções; as que já começaram mantêm a versão delas.'); setNote(''); })}>Ativar esta versão</button>
              {d.dirty && <button className="g-btn" disabled={busy} onClick={() => call('discard')}>Descartar rascunho</button>}
              {d.dirty && !d.tested && <span className="g-muted" style={{ fontSize: 12.5 }}>Teste esta configuração para poder ativar.</span>}
            </div>
          </>
        )}
        {d && tab === 'historico' && (
          <>
            {d.versions.length === 0 && <p className="g-muted" style={{ margin: 0 }}>Ainda sem versões: está valendo o padrão da função.</p>}
            {d.versions.map((r) => (
              <article key={r.version} className="g-card" style={{ padding: 10, display: 'flex', gap: 10, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                <div style={{ flex: 1, minWidth: 220 }}>
                  <strong>Versão {r.version}{r.version === d.active_version ? ' (ativa)' : ''}</strong> <span className="g-muted" style={{ fontSize: 12 }}>{when(r.created_at)}</span>
                  {r.note && <div style={{ fontSize: 13 }}>{r.note}</div>}
                  <div style={{ fontSize: 13 }}>{r.changes.join(', ')}</div>
                  {compare === r.version && <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, margin: '6px 0 0' }}>{JSON.stringify({ objetivos: r.config.goals, preferencias: r.config.preferences, restricoes: r.config.restrictions, conferir: r.config.quality, orientacoes: r.config.guidelines.map((g) => g.text) }, null, 1)}</pre>}
                </div>
                <button className="g-btn g-sm" onClick={() => setCompare(compare === r.version ? null : r.version)}>{compare === r.version ? 'Ocultar' : 'Ver'}</button>
                {r.version !== d.active_version && <button className="g-btn g-sm" disabled={busy} onClick={() => call('restore', { version: r.version })}>Restaurar</button>}
              </article>
            ))}
            {d.active_version > 0 && <div><button className="g-btn g-sm" disabled={busy} onClick={() => call('restore', { version: 0 })}>Restaurar padrão da função</button></div>}
          </>
        )}
      </div>
    </section>
  );
}

// Depois de aprovar, reprovar ou corrigir: só esta produção, ou propor uma orientação permanente (com confirmação).
export function LearnPanel({ v }) {
  const l = v.learn;
  const [step, setStep] = React.useState('ask');
  const [text, setText] = React.useState(l.note || '');
  const [conflicts, setConflicts] = React.useState([]);
  const [err, setErr] = React.useState('');
  const url = `/api/training/${l.agent}/`;
  const propose = async () => { setErr(''); try { const r = await post(url + 'propose', { note: text, decision: l.decision }); setText(r.text); setConflicts(r.conflicts); setStep('confirm'); } catch (e) { setErr(e.message); } };
  const recheck = async () => { const r = await post(url + 'check', { text }); setConflicts(r.conflicts); };
  const save = async (extra = {}) => { setErr(''); try { await post(url + 'guideline', { text, production: l.pid, ...extra }); setStep('done'); } catch (e) { setErr(e.message); await recheck(); } };
  const blocking = conflicts.filter((c) => c.blocking), soft = conflicts.filter((c) => !c.blocking);
  const replaceable = soft.filter((c) => c.kind === 'guideline' || c.kind === 'example').map((c) => c.id);
  return (
    <section role="dialog" aria-labelledby="ln-h" className="g-panel popb" style={{ position: 'absolute', left: '50%', bottom: 18, transform: 'translateX(-50%)', zIndex: 26, width: 'min(600px,calc(100vw - 24px))', padding: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <h2 id="ln-h" className="fred" style={{ margin: 0, fontSize: 17 }}>{step === 'done' ? 'Orientação guardada no rascunho' : `Isso vale só aqui, ou ${l.name} deve aprender?`}</h2>
      {err && <div role="alert" style={{ padding: 8, borderRadius: 8, background: '#FFE1DC', fontSize: 13, fontWeight: 700 }}>{err}</div>}
      {step === 'ask' && <>
        <textarea aria-label="Sua observação" className="g-field" rows={2} placeholder="O que você quer que seja lembrado? (opcional para só esta produção)" value={text} onChange={(e) => setText(e.target.value)} />
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button className="g-btn" onClick={v.closeLearn}>Aplicar apenas nesta produção</button>
          <button className="g-btn g-lime" disabled={!text.trim()} onClick={propose}>Propor orientação permanente</button>
        </div>
      </>}
      {step === 'confirm' && <>
        <label style={{ fontSize: 13.5, fontWeight: 700 }}>Aprendizado proposto. Edite se quiser:
          <textarea className="g-field" rows={2} value={text} onChange={(e) => setText(e.target.value)} onBlur={recheck} style={{ marginTop: 4 }} /></label>
        {conflicts.map((c, k) => <p key={k} style={{ margin: 0, padding: 8, borderRadius: 8, background: c.blocking ? '#FFE1DC' : '#FFF3C9', fontSize: 13 }}><strong>{c.blocking ? 'Conflito com regra obrigatória:' : 'Conflito:'}</strong> “{c.with}”. {c.explain}</p>)}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {blocking.length === 0 && soft.length === 0 && <button className="g-btn g-lime" onClick={() => save()}>Confirmar</button>}
          {blocking.length === 0 && replaceable.length > 0 && <button className="g-btn g-lime" onClick={() => save({ replace: replaceable, keep_both: replaceable.length < soft.length })}>Substituir a anterior</button>}
          {blocking.length === 0 && soft.length > 0 && <button className="g-btn" onClick={() => save({ keep_both: true })}>Manter as duas</button>}
          <button className="g-btn" onClick={v.closeLearn}>Não salvar</button>
        </div>
      </>}
      {step === 'done' && <>
        <p style={{ margin: 0, fontSize: 14 }}>Ela só passa a valer depois de testada e ativada. Esta produção segue com a versão atual.</p>
        <div style={{ display: 'flex', gap: 8 }}><button className="g-btn g-lime" onClick={() => v.openTraining(l.agent)}>Testar e ativar</button><button className="g-btn" onClick={v.closeLearn}>Depois</button></div>
      </>}
    </section>
  );
}
