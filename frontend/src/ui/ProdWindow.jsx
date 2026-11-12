import React from 'react';
import Boneco from '../Boneco.jsx';
import { Spinner, CloseButton, FormatArt } from './bits.jsx';
import { formatPhotoUrl } from './direcao.js';
import { CONFIRM_LABEL, needsConfirmation, summaryRows } from './nextVideo.js';
import { ADD_LABEL, KEEP_LABEL, NO_BALANCE_TITLE, noBalanceRows } from './credits.js';
import { TopUp } from './TopUp.jsx';

// Janela da produção: uma aba por agente/etapa, com dados REAIS do motor.
const Locked = ({ children }) => <div className="g-card" style={{ padding: 18, font: '700 15px/1.4 Instrument Sans,sans-serif' }}>{children}</div>;
const Pill = ({ bg, children }) => <span style={{ font: '800 12px/1 Instrument Sans,sans-serif', padding: '4px 8px', borderRadius: 999, background: bg, border: '1px solid #E7E7E4', alignSelf: 'flex-start' }}>{children}</span>;
const Check = () => <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 8.5l3 3 7-7" /></svg>;
const Tag = ({ dark, children }) => <span style={{ position: 'absolute', top: 8, left: 8, font: '800 10.5px/1 Instrument Sans,sans-serif', padding: '4px 7px', borderRadius: 6, background: dark ? '#0E0E10' : '#F2F2EF', color: dark ? '#fff' : '#0E0E10', border: '1px solid #E7E7E4' }}>{children}</span>;
const cr = (n) => `${n} crédito${n === 1 ? '' : 's'}`;

function Gate({ title, credits, v, onGo, label, note }) {
  const c = v.credits;
  return (
    <div className="g-card" style={{ padding: 18, display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'center', background: '#FFFFFF' }}>
      <div style={{ flex: 1, minWidth: 240, display: 'flex', flexDirection: 'column', gap: 6 }}>
        <span className="g-label" style={{ color: '#3F5200' }}>Etapa paga</span>
        <strong className="fred" style={{ fontSize: 20, fontWeight: 600 }}>{title}</strong>
        <span style={{ fontSize: 14 }}>Estimativa: <strong>{cr(credits)}</strong> · Usado neste vídeo: {c.spent}{v.balanceText ? ' · ' + v.balanceText : ''}</span>
        <span className="g-muted" style={{ fontSize: 12.5 }}>Estimativa, não valor confirmado. {note}</span>
        {v.mode === 'simulated' && <span className="g-sim" style={{ alignSelf: 'flex-start' }}>modo DEMO: nada é cobrado</span>}
      </div>
      <button className="g-btn g-lime" onClick={onGo} disabled={!!v.busy}>{v.busy ? 'Enviando…' : label}</button>
    </div>
  );
}

function Media({ url, video, label, dark, alt }) {
  return (
    <div style={{ position: 'relative', width: 190, height: 338, borderRadius: 16, overflow: 'hidden', border: '1px solid #E7E7E4', background: '#0F1730', flex: 'none' }}>
      {url && !video && <img src={url} alt={alt} style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
      {url && video && <video src={url} controls muted loop playsInline preload="metadata" aria-label={alt} style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
      {!url && <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: '#fff', font: '700 13px/1.3 Instrument Sans,sans-serif', padding: 16, textAlign: 'center' }}>Ainda não existe</div>}
      <Tag dark={dark}>{label}</Tag>
    </div>
  );
}

function TabProduto({ v }) {
  const p = v.product;
  if (!p.editing) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div className="g-card" style={{ padding: 14, display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'center' }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {p.refs.map((r, k) => <a key={k} href={r.url} target="_blank" rel="noopener"><img src={r.url} alt={'Referência: ' + r.role} style={{ width: 70, height: 94, objectFit: 'cover', borderRadius: 10, border: '1px solid #E7E7E4' }} /></a>)}
          </div>
          <div style={{ flex: 1, minWidth: 220, display: 'flex', flexDirection: 'column', gap: 4 }}>
            <strong className="fred" style={{ fontSize: 18, fontWeight: 600 }}>{p.name}</strong>
            {p.variant && <span style={{ fontSize: 14, fontWeight: 700 }}>{p.variant}</span>}
            {p.link && <span className="g-muted" style={{ fontSize: 12, wordBreak: 'break-all' }}>{p.link}</span>}
          </div>
        </div>
        {p.issues.length > 0 && <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13.5, lineHeight: 1.5 }}>{p.issues.map((i, k) => <li key={k} style={{ color: i.blocking ? '#9A2E22' : '#5C3300' }}>{i.blocking ? 'Bloqueia: ' : 'Atenção: '}{i.message}</li>)}</ul>}
        {p.unknown.length > 0 && <span className="g-muted" style={{ fontSize: 13 }}>Não vamos afirmar: {p.unknown.join(', ')}.</span>}
        <div style={{ font: '800 14px/1.3 Instrument Sans,sans-serif', padding: '10px 12px', borderRadius: 12, background: '#E3F5DC', border: '2px solid #2D7A3E', color: '#205C2E' }}>Produto confirmado. A Nina já entregou a ficha.</div>
      </div>
    );
  }
  const d = p.draft;
  return (
    <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'flex-start' }}>
      <div style={{ flex: '999 1 420px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {p.created && p.issues.filter((i) => i.blocking).length > 0 && (
          <div role="alert" style={{ padding: 12, borderRadius: 12, background: '#FFE7C2', border: '2px solid #7A4300', fontSize: 13.5 }}>
            <strong style={{ color: '#5C3300' }}>A Nina precisa de fotos válidas.</strong> {p.issues.filter((i) => i.blocking).map((i) => i.message).join(' ')}
          </div>
        )}
        <span className="g-label">Fotos oficiais do produto</span>
        <label className="g-pick" style={{ padding: 16, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, cursor: 'pointer', borderStyle: 'dashed' }}>
          <strong style={{ fontSize: 15 }}>Escolher fotos</strong>
          <span className="g-muted" style={{ fontSize: 12.5 }}>JPG, PNG ou WEBP do produto. Frente, tampa e detalhe costumam bastar.</span>
          <input type="file" multiple accept="image/jpeg,image/png,image/webp,video/mp4" onChange={p.addFiles} style={{ position: 'absolute', opacity: 0, width: 1, height: 1 }} />
        </label>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))', gap: 10 }}>
          {p.files.map((f) => (
            <div key={f.k} className="g-card" style={{ padding: 6, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {f.isVideo ? <div style={{ aspectRatio: '1/1', borderRadius: 9, background: '#0F1730', color: '#fff', display: 'grid', placeItems: 'center', fontSize: 12 }}>vídeo · só contexto</div>
                : <img src={f.data} alt={'Sua foto ' + f.name} style={{ width: '100%', aspectRatio: '1/1', objectFit: 'cover', borderRadius: 9 }} />}
              {!f.isVideo && <select className="g-field" value={f.role} onChange={f.setRole} aria-label={'O que a foto ' + f.name + ' mostra'} style={{ minHeight: 36, padding: '4px 8px' }}>{p.roles.map(([id, l]) => <option key={id} value={id}>{l}</option>)}</select>}
              <button className="g-btn g-sm g-quiet" onClick={f.remove}>Remover</button>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label className="g-label" htmlFor="pattrs">O que aparece nas fotos <span className="g-muted">(opcional)</span></label>
          <textarea id="pattrs" className="g-field" rows={3} value={d.attrs} onChange={p.setDraft('attrs')} placeholder={'acessório: alça removível\ninscrição: texto vertical no corpo'} />
          <span className="g-muted" style={{ fontSize: 12 }}>Ajuda a não perder detalhes como acessórios, tampas ou inscrições.</span>
        </div>
      </div>
      <div style={{ flex: '1 1 280px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {!p.created && <>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}><label className="g-label" htmlFor="pname">Nome do produto</label><input id="pname" className="g-field" value={d.name} onChange={p.setDraft('name')} placeholder="Ex.: Organizador de mesa com divisórias" /></div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}><label className="g-label" htmlFor="pcat">Categoria <span className="g-muted">(opcional)</span></label><input id="pcat" className="g-field" value={d.category} onChange={p.setDraft('category')} placeholder="Ex.: organização e escritório" /></div>
          <details><summary style={{ font: '800 13px/1 Instrument Sans,sans-serif', minHeight: 30, display: 'flex', alignItems: 'center' }}>Informações do anúncio (opcional)</summary>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, paddingTop: 6 }}>
              <label className="g-label" htmlFor="pver">Comprovadas (vão para a legenda)</label><textarea id="pver" className="g-field" rows={2} value={d.verified} onChange={p.setDraft('verified')} placeholder="cor: azul-claro" />
              <label className="g-label" htmlFor="pcl">Alegações do vendedor (não serão afirmadas)</label><textarea id="pcl" className="g-field" rows={2} value={d.claims} onChange={p.setDraft('claims')} placeholder="capacidade: 900 ml" />
            </div></details>
          <div className="g-card" style={{ padding: 12, fontSize: 13, display: 'flex', gap: 8 }}><span aria-hidden="true">–</span><span className="g-muted">Importar fotos direto de um link de marketplace ainda não está disponível: por enquanto, as fotos vêm de você.</span></div>
          <button className="g-btn g-lime" onClick={p.confirm} disabled={!!v.busy}>{v.busy === 'produto' ? 'Enviando fotos…' : 'Confirmar e entregar ao Theo'}</button>
          {p.missing.length > 0 && <span className="g-muted" style={{ fontSize: 12.5 }}>Falta: {p.missing.join(', ')}.</span>}
        </>}
        {p.created && <button className="g-btn g-lime" onClick={p.resend} disabled={!!v.busy}>{v.busy ? 'Enviando…' : 'Enviar fotos e revalidar'}</button>}
      </div>
    </div>
  );
}

// "Seu próximo vídeo": o que será criado e quanto custa, ANTES de qualquer gasto.
function NextVideo({ v }) {
  if (!needsConfirmation(v.P)) return null;
  const sm = v.P.confirmation.summary;
  return (
    <section className="g-card" aria-labelledby="nv-title" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10, background: '#FFFFFF', border: '2px solid #0E0E10' }}>
      <span className="g-label" style={{ color: '#3F5200' }}>Antes de começar</span>
      <strong id="nv-title" className="fred" style={{ fontSize: 20, fontWeight: 600 }}>Seu próximo vídeo</strong>
      <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: '8px 16px', fontSize: 13.5 }}>
        {summaryRows(sm).map(([k, val]) => <div key={k}><dt className="g-label">{k}</dt><dd style={{ margin: 0, fontWeight: 800 }}>{val}</dd></div>)}
      </dl>
      <span style={{ font: '800 13.5px/1.4 Instrument Sans,sans-serif', color: '#205C2E' }}>{sm.no_extra_cost}</span>
      <span className="g-muted" style={{ fontSize: 12.5 }}>Sem confirmação, nada é gasto. Se uma geração falhar por erro técnico, ela não é cobrada.</span>
    </section>
  );
}

// Falta de saldo para um ajuste extra: a conta à vista e duas saídas. Nada foi cobrado; o vídeo está preservado.
function NoBalance({ v }) {
  const [open, setOpen] = React.useState(false);
  const n = v.noBalance;
  if (!n) return null;
  return (
    <div role="alert" style={{ padding: 12, borderRadius: 12, background: '#FFE7C2', border: '2px solid #7A4300', display: 'flex', flexDirection: 'column', gap: 8 }}>
      <strong style={{ color: '#5C3300' }}>{NO_BALANCE_TITLE}</strong>
      <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(130px,1fr))', gap: '6px 14px', fontSize: 13.5 }}>
        {noBalanceRows(n).map(([k, val]) => <div key={k}><dt className="g-label">{k}</dt><dd style={{ margin: 0, fontWeight: 800 }}>{val}</dd></div>)}
      </dl>
      <span style={{ fontSize: 13.5, lineHeight: 1.45 }}>Nada foi cobrado. Seu vídeo, as cenas e as aprovações continuam salvos e você pode aprovar e baixar o que já está pronto.</span>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button className="g-btn g-sm g-lime" onClick={v.keepAsIs}>{KEEP_LABEL}</button>
        <button className="g-btn g-sm" onClick={() => setOpen((o) => !o)} aria-expanded={open}>{ADD_LABEL}</button>
      </div>
      {open && <TopUp topup={n.topup} missingCc={n.missing_cc} onClose={() => setOpen(false)} />}
    </div>
  );
}

function TabDirecao({ v }) {
  const d = v.dir;
  if (d.locked) return <Locked>A direção abre depois que a Nina confirmar o produto.</Locked>;
  if (!d.ready) return <div className="g-card" style={{ padding: 18, display: 'flex', gap: 12, alignItems: 'center' }}><Spinner size={22} />O Theo está preparando a proposta… <button className="g-btn g-sm" onClick={d.load}>Tentar de novo</button></div>;
  const isDir = v.dirSub === 'dir';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div role="tablist" aria-label="Direção" style={{ display: 'flex', gap: 6 }}>
        <button role="tab" className="g-chip" aria-pressed={isDir} aria-selected={isDir} onClick={v.toDir}>1 · Como vamos apresentar</button>
        <button role="tab" className="g-chip" aria-pressed={!isDir} aria-selected={!isDir} onClick={v.toCenas}>2 · Plano de cenas</button>
      </div>
      {isDir ? (
        <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <div style={{ flex: '999 1 420px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div role="group" aria-label="Formato" style={{ display: 'grid', gridTemplateColumns: 'repeat(3,minmax(0,1fr))', gap: 10 }}>
              {d.formats.map((f) => (
                <button key={f.id} className="g-pick" aria-pressed={f.sel} onClick={f.pick} disabled={d.done || f.disabled} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <span style={{ height: 90, borderRadius: 10, background: '#F2F2EF', display: 'grid', placeItems: 'center', border: '1px solid #E7E7E4', overflow: 'hidden' }}>
                    <FormatArt hand={f.hand} person={f.person} src={formatPhotoUrl(f.id, import.meta.env.BASE_URL)} />
                  </span>
                  <span style={{ font: '800 14px/1.2 Instrument Sans,sans-serif' }}>{f.label}</span>
                  <span className="g-muted" style={{ font: '600 12.5px/1.3 Instrument Sans,sans-serif' }}>{f.desc}</span>
                </button>
              ))}
            </div>
            <span className="g-muted" style={{ fontSize: 12 }}>{d.basis}</span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <label className="g-label" htmlFor="req">Quer mudar alguma coisa?</label>
              <div style={{ display: 'flex', gap: 8 }}>
                <input id="req" className="g-field" placeholder="Ex.: movimentos lentos e enquadramento mais próximo do produto." value={d.reqText} onChange={d.onReq} disabled={d.done} />
                <button className="g-btn" onClick={d.addReq} disabled={d.done}>Pedir ao Theo</button>
              </div>
              {d.reqs.map((rq, k) => (
                <div key={k} style={{ display: 'flex', gap: 8, alignItems: 'center', font: '700 13px/1.3 Instrument Sans,sans-serif', padding: '6px 6px 6px 10px', borderRadius: 10, background: '#fff', border: '2px dashed #0E0E10' }}>
                  <span style={{ flex: 1 }}>Pedido: “{rq.text}”. O Theo aplica nas cenas.</span>
                  {!d.done && <button className="g-btn g-quiet g-sm" onClick={rq.remove}>Desfazer</button>}
                </div>
              ))}
              {d.warnings.map((w, k) => <span key={k} role="alert" style={{ fontSize: 12.5, color: '#5C3300' }}>{w}</span>)}
            </div>
          </div>
          <div style={{ flex: '1 1 260px', minWidth: 0 }} className="g-card">
            <dl style={{ margin: 0, padding: '6px 14px' }}>
              {d.rows.map((dr) => (
                <div key={dr.k} style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '9px 0', borderBottom: '2px dotted #E7E7E4' }}>
                  <dt className="g-label">{dr.k}</dt><dd style={{ margin: 0, font: '700 14px/1.35 Instrument Sans,sans-serif' }}>{dr.v}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      ) : (
        <>
          <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
            {d.scenes.map((sp) => (
              <li key={sp.index} className="g-card" style={{ padding: 12, display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
                <span className="fred" style={{ width: 44, height: 44, borderRadius: 12, background: '#0E0E10', color: '#FF5B2E', display: 'grid', placeItems: 'center', fontSize: 20, fontWeight: 600, flex: 'none' }}>{sp.index}</span>
                <div style={{ flex: 1, minWidth: 220, display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <strong style={{ fontSize: 15 }}>{sp.title}</strong>
                  <span className="g-muted" style={{ fontSize: 12.5 }}>{sp.index === 1 ? 'Referências: suas fotos. Esta cena fixa o visual das outras.' : 'Referências: suas fotos e a imagem aprovada da cena 1.'}</span>
                </div>
                <span style={{ font: '800 14px/1 Instrument Sans,sans-serif' }}>~5 s</span>
              </li>
            ))}
          </ol>
          <details style={{ fontSize: 13 }}>
            <summary style={{ font: '800 13px/1 Instrument Sans,sans-serif', minHeight: 30, display: 'flex', alignItems: 'center' }}>Ver instruções de geração</summary>
            {d.scenes.map((sp) => <pre key={sp.index} style={{ whiteSpace: 'pre-wrap', font: '12px/1.5 ui-monospace,monospace', background: '#fff', border: '1px solid #E7E7E4', borderRadius: 10, padding: 10 }}>{sp.image_prompt}</pre>)}
          </details>
          <span style={{ font: '800 14px/1 Instrument Sans,sans-serif' }}>Total planejado: ~15 s · Nada foi gasto até aqui.</span>
        </>
      )}
      <NextVideo v={v} />
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, borderTop: '2px dashed #D8CDB9', paddingTop: 12, flexWrap: 'wrap' }}>
        {isDir && <button className="g-btn" onClick={v.toCenas}>Ver plano de cenas</button>}
        {d.canApprove && <button className="g-btn g-lime" onClick={d.approve} disabled={!!v.busy}>{needsConfirmation(v.P) ? CONFIRM_LABEL : 'Aprovar e mandar para a Iris'}</button>}
        {d.working && <span className="g-muted" style={{ font: '700 13px/42px Instrument Sans,sans-serif', display: 'flex', gap: 8, alignItems: 'center' }}><Spinner size={18} />Escrevendo o roteiro…</span>}
        {d.done && !d.working && <span style={{ font: '800 13px/42px Instrument Sans,sans-serif', color: '#205C2E' }}>Direção e cenas aprovadas.</span>}
      </div>
    </div>
  );
}

function Slots({ list }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(min(200px,100%),1fr))', gap: 12 }}>
      {list.map((s) => (
        <div key={s.k} className="g-card" style={{ padding: 12, display: 'flex', gap: 12, alignItems: 'center' }}>
          <div style={{ width: 62, height: 110, borderRadius: 9, border: '1px solid #E7E7E4', background: '#0F1730', display: 'grid', placeItems: 'center', flex: 'none', overflow: 'hidden', opacity: s.status === 'fila' ? 0.5 : 1 }}>
            {s.url && !s.isVideo && <img src={s.url} alt={'Imagem gerada da cena ' + s.n} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />}
            {s.url && s.isVideo && <svg width="22" height="22" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="#FF5B2E" stroke="#0E0E10" strokeWidth="2" /><path d="M8 6.5l5 3.5-5 3.5z" fill="#0E0E10" /></svg>}
            {s.status === 'gerando' && <Spinner track="#ffffff33" color="#FF5B2E" />}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <strong style={{ fontSize: 14 }}>{s.isVideo ? 'Take' : 'Cena'} {s.n}</strong>
            <Pill bg={s.bg}>{s.label}</Pill>
            <span className="g-muted" style={{ fontSize: 12 }}>{s.sub}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function BudgetBox({ v }) {
  if (!v.budgetHit) return null;
  const pz = v.pause;
  const box = (title, text, actions) => (
    <div role="alert" style={{ padding: 12, borderRadius: 12, background: '#FFE7C2', border: '2px solid #7A4300', display: 'flex', flexDirection: 'column', gap: 8 }}>
      <strong style={{ color: '#5C3300' }}>{title}</strong>
      <span style={{ fontSize: 13.5, lineHeight: 1.45 }}>{text} Nada foi perdido: cenas, aprovações e versões continuam aqui.</span>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {actions}
        <button className="g-btn g-sm" onClick={v.dismissBudget}>Revisar o que já existe</button>
        <button className="g-btn g-sm" onClick={v.closeWin}>Continuar depois</button>
      </div>
    </div>
  );
  if (pz.kind === 'mensal') return box('Teto de gastos do mês atingido',
    `Neste mês já foram usados ${pz.monthSpent} de ${pz.monthCap} créditos e o próximo passo custaria cerca de ${pz.next} créditos. O teto vale para todas as produções do estúdio.`,
    v.confirmCap ? (
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', width: '100%', padding: 10, borderRadius: 10, background: '#fff', border: '1px solid #E7E7E4' }}>
        <span style={{ fontSize: 13.5, flex: '1 1 220px' }}>Confirmar teto de <strong>{v.confirmCap} créditos</strong> no mês (≈ US$ {v.confirmCapUsd.toFixed(2)} de custo real na sua conta Google, para todas as produções)?</span>
        <button className="g-btn g-sm g-lime" onClick={() => v.raiseMonthly(v.confirmCap)} disabled={!!v.busy}>{v.busy ? 'Aplicando…' : 'Confirmar'}</button>
        <button className="g-btn g-sm" onClick={v.cancelCap}>Cancelar</button>
      </div>
    ) : pz.capOptions.map((n) => <button key={n} className="g-btn g-sm g-lime" onClick={() => v.raiseMonthly(n)} disabled={!!v.busy}>Subir teto do mês para {n} créditos</button>));
  if (pz.kind === 'provedor') return box('A conta da IA ficou sem saldo',
    'A geração foi recusada porque os créditos pré-pagos da conta da API (Google AI Studio) acabaram. Não é um problema da cena e nenhuma tentativa foi gasta. Recarregue a conta e retome; ou encerre esta produção.',
    v.confirmCancel ? (
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', width: '100%', padding: 10, borderRadius: 10, background: '#fff', border: '1px solid #E7E7E4' }}>
        <span style={{ fontSize: 13.5, flex: '1 1 220px' }}>Encerrar esta produção? Ela sai da fila e não pode ser retomada; o que já foi gerado fica no histórico.</span>
        <button className="g-btn g-sm" onClick={v.cancelProd} disabled={!!v.busy}>Sim, encerrar</button>
        <button className="g-btn g-sm g-lime" onClick={v.keepProd}>Manter</button>
      </div>
    ) : <>
      <a className="g-btn g-sm" href="https://aistudio.google.com/projects" target="_blank" rel="noreferrer">Abrir o AI Studio (cobrança)</a>
      <button className="g-btn g-sm g-lime" onClick={v.resumeOnly} disabled={!!v.busy}>Já recarreguei: retomar</button>
      <button className="g-btn g-sm" onClick={v.cancelProd} disabled={!!v.busy}>Encerrar produção</button>
    </>);
  if (pz.kind === 'saldo') return box('Saldo insuficiente para continuar',
    `O saldo do estúdio é de ${pz.balance} créditos e o próximo passo custaria cerca de ${pz.next}. O estúdio pausou antes de gastar e tudo o que você já tem continua salvo.`,
    <>
      <button className="g-btn g-sm g-lime" onClick={v.dismissBudget}>{KEEP_LABEL}</button>
      <button className="g-btn g-sm" onClick={v.openCredits}>{ADD_LABEL}</button>
      <button className="g-btn g-sm" onClick={v.resumeOnly} disabled={!!v.busy}>Já adicionei: retomar</button>
    </>);
  if (pz.kind === 'outro') return box('Produção pausada', pz.reason || 'O estúdio pausou esta produção.',
    <button className="g-btn g-sm g-lime" onClick={v.resumeOnly} disabled={!!v.busy}>Retomar</button>);
  // Freio interno do Kiroo (orçamento operacional): nunca pede dinheiro nem upgrade ao cliente.
  return box('Estamos finalizando seu vídeo',
    'A equipe do Kiroo já foi avisada e avisaremos quando estiver pronto. Você não precisa fazer nada e nada a mais será cobrado por isso.',
    null);
}

function TabRevisao({ v }) {
  if (v.revLocked || !v.rev) return <><BudgetBox v={v} /><Locked>Nada para revisar ainda. O Rui chama você quando as imagens chegarem.</Locked></>;
  const cur = v.rev, m = cur.media;
  const url = m.view === 'ref' ? m.refUrl : m.view === 'video' ? m.vidUrl : m.imgUrl;
  return (
    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-start' }}>
      <div role="tablist" aria-label="Cenas" style={{ flex: '0 1 170px', display: 'flex', flexDirection: 'column', gap: 8, minWidth: 150 }}>
        <span className="g-label">{v.revKindLabel}</span>
        {v.revScenes.map((rs) => (
          <button key={rs.k} role="tab" aria-selected={rs.sel} className="g-pick" aria-pressed={rs.sel} onClick={rs.pick} style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '8px 10px' }}>
            <strong style={{ fontSize: 14 }}>Cena {rs.n}</strong><Pill bg={rs.bg}>{rs.label}</Pill>
          </button>
        ))}
      </div>
      <div style={{ flex: 'none', display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'center' }}>
        <div role="tablist" aria-label="Ver" style={{ display: 'flex', gap: 4 }}>
          {cur.viewTabs.map((vt) => <button key={vt.id} role="tab" aria-selected={vt.sel} className="g-chip" aria-pressed={vt.sel} onClick={vt.pick} disabled={vt.off} style={{ minHeight: 32, padding: '0 10px', fontSize: 12 }}>{vt.label}</button>)}
        </div>
        <div style={{ position: 'relative' }}>
          <Media url={url} video={m.view === 'video'} label={m.label} dark={m.view !== 'ref'} alt={m.label + ' da cena ' + cur.n} />
          {m.busy && <div role="status" style={{ position: 'absolute', inset: 0, borderRadius: 16, background: '#0F1730cc', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10, color: '#fff', textAlign: 'center', padding: 16, font: '800 14px/1.35 Instrument Sans,sans-serif' }}><Spinner size={28} track="#ffffff44" color="#FF5B2E" />{m.busyText}</div>}
        </div>
      </div>
      <div style={{ flex: '1 1 280px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: 12, borderRadius: 14, border: '1px solid #E7E7E4', background: cur.chk.bg }}>
          <span style={{ width: 40, height: 40, borderRadius: 10, background: '#6BAA75', border: '1px solid #E7E7E4', display: 'grid', placeItems: 'end center', overflow: 'hidden', flex: 'none' }}><Boneco look={v.ruiLook} crop size={36} /></span>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}><strong style={{ fontSize: 14 }}>{cur.chk.title}</strong><span style={{ fontSize: 13.5, lineHeight: 1.4 }}>{cur.chk.text}</span></div>
        </div>
        <div style={{ font: '700 13.5px/1.4 Instrument Sans,sans-serif' }}><strong>{cur.title}</strong><br /><span className="g-muted">{cur.sub}</span></div>
        <BudgetBox v={v} />
        {cur.limitHit && cur.canAct && <div style={{ padding: 12, borderRadius: 12, background: '#FFE1DC', border: '2px solid #9A2E22', fontSize: 13.5, lineHeight: 1.4 }}><strong style={{ color: '#7A2218' }}>{cur.maxTries} tentativas usadas nesta cena.</strong> Para não gastar sem controle, novas tentativas ficam bloqueadas. Aprove a melhor versão ou ajuste a direção com o Theo.</div>}
        {cur.failed && (
          <div role="alert" style={{ padding: 12, borderRadius: 12, background: '#FFE1DC', border: '2px solid #9A2E22', fontSize: 13.5, lineHeight: 1.4, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {cur.failBilling ? <>
              <span><strong style={{ color: '#7A2218' }}>A {cur.what} da cena {cur.n} não saiu: a conta da IA (Google AI Studio) ficou sem créditos pré-pagos.</strong> A cena está certa; o problema é o saldo da conta.</span>
              <span>Recarregue em <a href="https://aistudio.google.com/projects" target="_blank" rel="noreferrer">aistudio.google.com</a> e clique em Tentar de novo. Se a conta ainda estiver sem saldo, a produção pausa sem gastar tentativa.</span>
            </> : <>
              <span><strong style={{ color: '#7A2218' }}>A {cur.what} da cena {cur.n} não saiu.</strong> {cur.failText}</span>
              <span>Nada a aprovar ainda. Tentar de novo refaz só esta cena (custo estimado: {cr(cur.cost)}).</span>
            </>}
            <div><button className="g-btn g-lime g-sm" onClick={v.retryCur} disabled={!cur.canRetry || !!v.busy}>{v.busy === 'retry' ? 'Enviando…' : 'Tentar de novo'}</button></div>
          </div>
        )}
        {cur.canAct && !v.adjusting && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}><button className="g-btn g-lime" onClick={v.approveCur} disabled={!!v.busy}>Aprovar cena {cur.n}</button><button className="g-btn" onClick={v.openAdjust} disabled={cur.limitHit}>Pedir ajuste</button></div>}
        {cur.canAct && v.adjusting && (
          <div className="g-card" style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <span className="g-label">O que está errado?</span>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{v.issues.map((iss) => <button key={iss.label} className="g-chip" aria-pressed={iss.sel} onClick={iss.pick} style={{ minHeight: 34, fontSize: 12.5 }}>{iss.label}</button>)}</div>
            <input className="g-field" placeholder="Quer explicar melhor? (opcional)" value={v.adjText} onChange={v.onAdjText} aria-label="Detalhe do ajuste" />
            <div style={{ fontSize: 13, lineHeight: 1.45, padding: '8px 10px', borderRadius: 10, background: '#F2F2EF' }}>
              <strong>Refaz:</strong> só a {cur.what} da cena {cur.n} (tentativa {cur.nextTry} de {cur.maxTries}).<br />
              <strong>Preserva:</strong> as outras cenas, aprovações, direção e identidade.<br />
              <strong>Custo estimado:</strong> {cr(cur.cost)}.
            </div>
            {v.noBalance && v.noBalance.scene === cur.n && <NoBalance v={v} />}
            {v.confirmExtra && v.confirmExtra.scene === cur.n && (
              <div role="alert" style={{ padding: 10, borderRadius: 10, background: '#fff', border: '2px solid #7A4300', fontSize: 13.5, lineHeight: 1.4 }}>
                Os ajustes incluídos desta cena já foram usados. Este ajuste extra custa cerca de <strong>{v.confirmExtra.cost} créditos</strong>, reservados do saldo do estúdio. Autorizar?
              </div>
            )}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button className="g-btn g-lime g-sm" onClick={v.sendAdjust} disabled={v.noIssue || !!v.busy}>{v.confirmExtra && v.confirmExtra.scene === cur.n ? `Autorizar ${v.confirmExtra.cost} créditos e enviar` : `Enviar para ${cur.who}`}</button>
              <button className="g-btn g-sm" onClick={() => { v.cancelExtra(); v.closeAdjust(); }}>Cancelar</button>
            </div>
          </div>
        )}
        {cur.tries > 1 && <span className="g-muted" style={{ fontSize: 12.5 }}>Esta cena já teve {cur.tries} versões; as anteriores ficam guardadas no histórico.</span>}
        {cur.criteria.length > 0 && <details><summary style={{ font: '800 13px/1 Instrument Sans,sans-serif', minHeight: 30, display: 'flex', alignItems: 'center' }}>O que conferir</summary><ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 13, lineHeight: 1.6 }}>{cur.criteria.map((t) => <li key={t}>{t}</li>)}</ul></details>}
      </div>
    </div>
  );
}

// Estilo da montagem (Beto): transições, trilha e efeitos. Trocar depois de pronto só remonta (FFmpeg, sem custo).
function EditBox({ v, compact }) {
  const o = v.editOptions, e = v.edit;
  const [style, setStyle] = React.useState(e ? e.style : 'dinamico');
  const [music, setMusic] = React.useState(e ? e.music : 'auto');
  React.useEffect(() => { if (e) { setStyle(e.style); setMusic(e.music); } }, [e && e.style, e && e.music]);
  if (!o || !e) return null;
  const last = e.last || {};
  // montagens anteriores a este editor não têm registro de estilo: oferece remontar mesmo sem mudança
  const changed = style !== e.style || music !== e.music || (!compact && !last.edit_style);
  const st = o.styles.find((x) => x.id === style) || o.styles[0];
  const defTrack = o.music.find((m) => m.id === st.music);
  return (
    <div className="g-card" style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <strong style={{ fontSize: 14 }}>Edição do Beto</strong>
      <div role="radiogroup" aria-label="Estilo da montagem" style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {o.styles.map((x) => (
          <button key={x.id} role="radio" aria-checked={style === x.id} className="g-chip" aria-pressed={style === x.id}
            onClick={() => setStyle(x.id)}>{x.label}</button>
        ))}
      </div>
      <span className="g-muted" style={{ fontSize: 12.5 }}>{st.hint}.</span>
      {style !== 'limpo' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label className="g-label" htmlFor="ed-music">Trilha</label>
          <select id="ed-music" className="g-field" value={music} onChange={(ev) => setMusic(ev.target.value)}>
            <option value="auto">Do estilo{defTrack ? ' (' + defTrack.title + ')' : ''}</option>
            {o.music.map((m) => <option key={m.id} value={m.id}>{m.title}{m.bpm ? ' · ' + m.bpm + ' BPM' : ''}</option>)}
            <option value="none">Sem trilha (só efeitos)</option>
          </select>
        </div>
      )}
      {!compact && (
        <span className="g-muted" style={{ fontSize: 12, lineHeight: 1.45 }}>
          Músicas em alta têm direitos autorais e só podem ser usadas dentro da própria plataforma. Por isso o Beto entrega
          também uma versão sem música: escolha o som em alta no editor da Shopee Vídeo ao publicar. As trilhas do estúdio são
          geradas aqui e livres de direitos; trilhas suas entram pela pasta de músicas com a licença informada.
        </span>
      )}
      {last.edit_style && !compact && (
        <span style={{ fontSize: 12.5 }}>
          Montagem atual: <strong>{(o.styles.find((x) => x.id === last.edit_style) || {}).label || last.edit_style}</strong>
          {last.music ? ' · trilha ' + last.music.title : ' · sem trilha'}
          {last.sfx && last.sfx.length ? ' · ' + last.sfx.length + ' efeitos' : ''}
        </span>
      )}
      {changed && (
        <button className="g-btn g-sm g-lime" style={{ alignSelf: 'flex-start' }} onClick={() => v.setEdit(style, music)} disabled={!!v.busy}>
          {compact ? 'Usar este estilo' : 'Remontar com este estilo (sem custo)'}
        </button>
      )}
      <button className="g-btn g-sm" style={{ alignSelf: 'flex-start' }} onClick={v.openMusic}>Trilhas da Lia: escolher, enviar ou ajustar</button>
    </div>
  );
}

function TabEntrega({ v }) {
  if (v.entLocked) return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Locked>O Beto monta o vídeo quando os três takes estiverem aprovados.</Locked>
      <EditBox v={v} compact />
    </div>
  );
  if (v.entBuilding) return <div role="status" className="g-card" style={{ padding: 18, display: 'flex', gap: 12, alignItems: 'center', font: '800 15px/1.4 Instrument Sans,sans-serif' }}><Spinner size={24} />Montando seu vídeo com as cenas aprovadas. Pode circular pelo estúdio.</div>;
  const d = v.delivery || {};
  const capUrl = 'data:text/plain;charset=utf-8,' + encodeURIComponent(v.caption);
  return (
    <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'flex-start' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'center' }}>
        <Media url={d['final.mp4']} video label="Conteúdo gerado · vídeo final" dark alt="Vídeo final" />
      </div>
      <div style={{ flex: '1 1 320px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          {d['cover.jpg'] && <img src={d['cover.jpg']} alt="Capa gerada" style={{ width: 60, height: 106, objectFit: 'cover', borderRadius: 8, border: '1px solid #E7E7E4' }} />}
          <span className="g-muted" style={{ fontSize: 13 }}>Capa tirada do fim do vídeo.</span>
        </div>
        <EditBox v={v} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label className="g-label" htmlFor="cap">Legenda</label>
          <textarea id="cap" className="g-field" rows={4} value={v.caption} onChange={v.onCaption} style={{ resize: 'vertical' }} />
          <span className="g-muted" style={{ fontSize: 12 }}>O Beto escreve só com o que está na ficha e no que você confirmou. Nada de benefícios inventados.</span>
        </div>
        <div className="g-card" style={{ padding: 12, fontSize: 13, lineHeight: 1.45 }}>
          O vídeo não leva aviso na tela: a identificação de publicidade e de imagens geradas por IA está na legenda. Ao publicar, marque também o conteúdo como publicidade na Shopee e confira as regras atuais: isto não garante conformidade.
        </div>
        <div className="g-card" style={{ padding: 12, display: 'grid', gridTemplateColumns: 'repeat(2,minmax(0,1fr))', gap: '8px 14px', fontSize: 13.5 }}>
          <div><span className="g-label">Produto</span><br /><strong>{v.P && v.P.product.name}</strong></div>
          {v.P && v.P.product.variant && <div><span className="g-label">Variante</span><br /><strong>{v.P.product.variant}</strong></div>}
          <div><span className="g-label">Duração</span><br /><strong>~15 s · 3 cenas</strong></div>
          <div><span className="g-label">Usado neste vídeo</span><br /><strong>{v.credits.spent}</strong> <span className="g-muted">estimativa</span></div>
        </div>
        {!v.exported && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}><button className="g-btn g-lime" onClick={v.exportVideo} disabled={!!v.busy}>Exportar vídeo</button></div>}
        {v.exported && (
          <div role="status" style={{ padding: 12, borderRadius: 12, background: '#E3F5DC', border: '2px solid #2D7A3E', fontSize: 13.5, lineHeight: 1.45, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <strong style={{ color: '#205C2E' }}>Exportado.</strong> A publicação na Shopee Vídeo é manual: baixe os arquivos e envie pelo app.
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <a className="g-btn g-sm g-lime" href={d['final.mp4']} download>Baixar vídeo (MP4)</a>
              {d['final_sem_musica.mp4'] && <a className="g-btn g-sm" href={d['final_sem_musica.mp4']} download>Baixar sem música (para som da Shopee)</a>}
              <a className="g-btn g-sm" href={d['cover.jpg']} download>Baixar capa</a>
              <a className="g-btn g-sm" href={capUrl} download="legenda.txt">Baixar legenda</a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function ProdWindow({ v }) {
  return (
    <section role="dialog" aria-labelledby="prod-h" className="g-panel pop" style={{ position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', zIndex: 20, width: 'min(1000px,calc(100vw - 24px))', height: 'min(680px,calc(100vh - 24px))', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: '12px 14px 0', background: '#F2F2EF', borderBottom: '1px solid #E7E7E4', display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <h2 id="prod-h" className="fred" style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>{v.prodName}</h2>
          <span style={{ font: '800 12px/1 Instrument Sans,sans-serif', padding: '5px 9px', borderRadius: 999, background: '#0E0E10', color: '#fff' }}>{v.stageLabel}</span>
          {v.mode === 'simulated' && <span className="g-sim">modo DEMO</span>}
          <span style={{ flex: 1 }} />
          <span className="g-muted" style={{ font: '800 13px/1 Instrument Sans,sans-serif', fontVariantNumeric: 'tabular-nums' }}>{v.spentText}</span>
          <CloseButton onClick={v.closeWin} label="Fechar produção" />
        </div>
        <div role="tablist" aria-label="Etapas" style={{ display: 'flex', gap: 2, overflowX: 'auto', paddingBottom: 8 }}>
          {v.tabs.map((tb) => (
            <button key={tb.id} role="tab" className="g-tab" aria-selected={tb.sel} onClick={tb.pick} aria-label={tb.aria}>
              <span style={{ position: 'relative', width: 30, height: 30, borderRadius: 9, background: tb.bg, border: '1px solid #E7E7E4', display: 'grid', placeItems: 'end center', overflow: 'hidden', flex: 'none' }}><Boneco look={tb.look} crop size={26} /></span>
              <span>{tb.label}</span>
              <span aria-hidden="true" style={{ minWidth: 18, height: 18, borderRadius: 999, background: tb.dot, border: '1px solid #E7E7E4', font: '900 10px/14px Instrument Sans,sans-serif', textAlign: 'center', color: tb.dotInk, padding: '0 3px' }}>{tb.sym}</span>
            </button>
          ))}
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 18 }}>
        {v.tab === 'produto' && <TabProduto v={v} />}
        {v.tab === 'direcao' && <TabDirecao v={v} />}
        {v.tab === 'imagens' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {v.imgLocked && <Locked>A Iris entra quando você aprovar a direção e as cenas com o Theo.</Locked>}
            {v.imgGate && v.est && <Gate v={v} title="Criar 3 imagens, uma por cena" credits={v.est.images.credits} onGo={v.startImages} label="Gerar imagens" note="A cena 1 vem primeiro e define o visual das outras." />}
            {!v.imgLocked && !v.imgGate && <><Slots list={v.imgSlots} /><p className="g-muted" style={{ margin: 0, fontSize: 13 }}>Cada imagem leva cerca de 30 s. Você pode sair desta janela: o estúdio avisa quando terminar.</p></>}
          </div>
        )}
        {v.tab === 'revisao' && <TabRevisao v={v} />}
        {v.tab === 'videos' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {v.vidLocked && <Locked>A Lia anima as cenas depois que você aprovar as três imagens com o Rui.</Locked>}
            {v.vidGate && v.est && <Gate v={v} title="Animar as 3 cenas aprovadas" credits={v.est.videos.credits} onGo={v.startVideos} label="Gerar movimentos" note="Cada take leva cerca de um minuto." />}
            {v.vidProgress && <Slots list={v.vidSlots} />}
          </div>
        )}
        {v.tab === 'entrega' && <TabEntrega v={v} />}
      </div>
    </section>
  );
}
