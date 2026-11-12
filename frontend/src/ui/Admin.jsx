import React from 'react';
import { CircleAlert, KeyRound, ShieldAlert } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { Spinner } from './bits.jsx';
import { getJSON, post } from '../engine/api.js';
import { auditLine, checkCredits, confirmSpec, isReauthError, newIdemKey, parseCredits, usd } from './admin.js';
import { TurnstileBox } from './Auth.jsx';
import { captchaMessage } from './turnstile.js';
import './admin.css';

// Aba Administrador (só aparece para administrador da plataforma; o servidor responde 404 para os demais em
// /api/admin/*). Tudo que muda algo passa por um modal com o resumo do efeito; ações sensíveis pedem login recente.
// Apagar conta e criar/remover administrador NÃO existem aqui: só pela CLI.

const when = (iso) => {
  try { return new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' }); }
  catch { return iso; }
};
const TABS = [['contas', 'Contas'], ['convites', 'Convites'], ['metricas', 'Métricas'], ['auditoria', 'Auditoria']];

export function AdminContent({ v }) {
  const [ov, setOv] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [tab, setTab] = React.useState('contas');
  const [pending, setPending] = React.useState(null);   // ação esperando confirmação
  const [secret, setSecret] = React.useState(null);     // código de convite / link de senha: mostrado uma vez
  const [tick, setTick] = React.useState(0);            // recarrega listas depois de uma ação
  const loadOv = React.useCallback(() => getJSON('/api/admin/overview').then(setOv).catch((e) => setErr(e.message)), []);
  React.useEffect(() => { loadOv(); }, [loadOv, tick]);

  const ask = (action, { account, input = {}, path, body = {}, after }) => {
    const self = !!(account && ov && account.id === ov.me.id);
    // a chave nasce com a intenção: repetir o envio (duplo clique, reautenticação) usa a mesma
    const key = (action === 'grant' || action === 'adjust') ? newIdemKey() : undefined;
    setPending({ action, account, input, path, body: { ...body, ...(key ? { idempotency_key: key } : {}) }, after,
      spec: confirmSpec(action, account, input, { self }) });
  };
  const done = (res, p) => {
    setPending(null); setTick((t) => t + 1);
    if (p.after) p.after(res);
  };

  if (err) return <div role="alert" className="adm-alert">{err}</div>;
  if (!ov) return <div style={{ display: 'grid', placeItems: 'center', padding: 30 }}><Spinner /></div>;
  return (
    <div className="pref-stack adm">
      <div className="adm-note" role="note">
        <ShieldAlert size={16} aria-hidden="true" />
        <span>Área do administrador da plataforma. Toda ação fica registrada na auditoria (quem, quando, antes e depois, motivo e IP).
          Créditos: até {ov.limits.max_grant} por lançamento e {ov.limits.daily_cap} por dia (hoje restam {ov.limits.left_today}); acima disso, só pela CLI.
          Apagar conta e criar administrador: só pela CLI.</span>
      </div>
      <div role="tablist" aria-label="Seções do administrador" style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {TABS.map(([id, label]) => (
          <button key={id} role="tab" className="g-chip" aria-selected={tab === id} aria-pressed={tab === id} onClick={() => setTab(id)}>{label}</button>
        ))}
      </div>
      {secret && <SecretBox secret={secret} onClose={() => setSecret(null)} />}
      {tab === 'contas' && <Accounts ov={ov} ask={ask} tick={tick} setSecret={setSecret} />}
      {tab === 'convites' && <Invites ask={ask} tick={tick} setSecret={setSecret} />}
      {tab === 'metricas' && <Metrics />}
      {tab === 'auditoria' && <Audit tick={tick} />}
      {pending && <Confirm p={pending} ov={ov} onClose={() => setPending(null)} onDone={done} onReauth={loadOv} />}
    </div>
  );
}

function SecretBox({ secret, onClose }) {
  const [copied, setCopied] = React.useState(false);
  const copy = () => navigator.clipboard?.writeText(secret.value).then(() => setCopied(true)).catch(() => {});
  return (
    <div className="g-card adm-secret" role="status">
      <strong>{secret.label}</strong>
      <code>{secret.value}</code>
      <span className="g-muted">{secret.notice} Não cole em chat ou ticket público.</span>
      <div style={{ display: 'flex', gap: 8 }}>
        <button className="g-btn g-sm" onClick={copy}>{copied ? 'Copiado' : 'Copiar'}</button>
        <button className="g-btn g-sm" onClick={onClose}>Já copiei, esconder</button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ confirmação (+ reautenticação)
function Confirm({ p, ov, onClose, onDone, onReauth }) {
  const { spec } = p;
  const [reason, setReason] = React.useState('');
  const [typed, setTyped] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState(null);
  const [needAuth, setNeedAuth] = React.useState(!ov.reauth.ok);
  const okEmail = !spec.typeEmail || typed.trim().toLowerCase() === spec.typeEmail.toLowerCase();
  const okReason = !spec.reason || reason.trim().length >= 3;
  const go = async () => {
    setBusy(true); setMsg(null);
    try {
      const res = await post(p.path, { ...p.body, reason: reason.trim(), ...(spec.typeEmail ? { confirm_email: typed.trim() } : {}) });
      onDone(res, p);
    } catch (e) {
      if (isReauthError(e)) setNeedAuth(true);
      setMsg(e.message);
    } finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="adm-confirm pw-theme" onKeyDown={(e) => { if (e.key !== 'Escape') e.stopPropagation(); }}>
        <DialogTitle>{spec.title}</DialogTitle>
        <DialogDescription className="sr-only">Confira o efeito antes de confirmar.</DialogDescription>
        {spec.financial && <div className="adm-warn"><CircleAlert size={16} aria-hidden="true" />Efeito financeiro: esta ação muda saldo, custo ou limite de gasto.</div>}
        {spec.self && <div className="adm-warn adm-self"><ShieldAlert size={16} aria-hidden="true" />Você está alterando a SUA conta. Fica em destaque na auditoria.</div>}
        <ul className="adm-summary">{spec.lines.map((l) => <li key={l}>{l}</li>)}</ul>
        {needAuth
          ? <Reauth ov={ov} onOk={() => { setNeedAuth(false); setMsg(null); onReauth(); }} />
          : (
            <form onSubmit={(e) => { e.preventDefault(); if (okEmail && okReason && !busy) go(); }} className="adm-form">
              <label className="adm-field">
                <span>Motivo {spec.reason ? '(obrigatório)' : '(opcional)'}</span>
                <input className="adm-input" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} autoFocus />
              </label>
              {spec.typeEmail && (
                <label className="adm-field">
                  <span>Para confirmar, digite o e-mail da conta: <strong>{spec.typeEmail}</strong></span>
                  <input className="adm-input" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} />
                </label>
              )}
              {msg && <div role="alert" className="adm-alert">{msg}</div>}
              <div className="adm-actions">
                <button type="button" className="g-btn g-sm" onClick={onClose}>Cancelar</button>
                <button type="submit" className="g-btn g-sm g-lime" disabled={busy || !okEmail || !okReason}>{busy ? 'Enviando…' : 'Confirmar'}</button>
              </div>
            </form>
          )}
      </DialogContent>
    </Dialog>
  );
}

function Reauth({ ov, onOk }) {
  const [pw, setPw] = React.useState('');
  const [captcha, setCaptcha] = React.useState('');
  const [tickC, setTickC] = React.useState(0);
  const [msg, setMsg] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  if (!ov.me.has_password) {
    return (
      <div className="adm-reauth">
        <p style={{ margin: 0 }}><KeyRound size={15} aria-hidden="true" /> Confirme que é você: sua conta entra pelo Google. Entre de novo com o Google e volte a esta aba
          (vale {ov.reauth.minutes} minutos).</p>
        {ov.google_enabled
          ? <a className="g-btn g-sm g-lime" href="/api/auth/google/start">Entrar de novo com o Google</a>
          : <p className="g-muted" style={{ margin: 0 }}>O login com Google está desligado neste ambiente: use a CLI.</p>}
      </div>
    );
  }
  const go = async (e) => {
    e.preventDefault(); setBusy(true); setMsg(null);
    try { await post('/api/admin/reauth', { password: pw, captcha }); setPw(''); onOk(); }
    catch (err) { setMsg(captchaMessage(err.data?.code) || err.message); }
    finally { setBusy(false); if (ov.turnstile) { setCaptcha(''); setTickC((t) => t + 1); } }
  };
  return (
    <form className="adm-reauth" onSubmit={go}>
      <p style={{ margin: 0 }}><KeyRound size={15} aria-hidden="true" /> Confirme sua senha para continuar (vale {ov.reauth.minutes} minutos).</p>
      <input className="adm-input" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} aria-label="Sua senha" autoFocus />
      {ov.turnstile && <TurnstileBox siteKey={ov.turnstile} resetKey={tickC} onToken={setCaptcha} onFail={(c) => setMsg(captchaMessage(c))} />}
      {msg && <div role="alert" className="adm-alert">{msg}</div>}
      <button type="submit" className="g-btn g-sm g-lime" disabled={busy || !pw || (ov.turnstile && !captcha)}>Confirmar senha</button>
    </form>
  );
}

// ------------------------------------------------------------------ contas
function Accounts({ ov, ask, tick, setSecret }) {
  const [d, setD] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [q, setQ] = React.useState('');
  const [open, setOpen] = React.useState(null);
  React.useEffect(() => { getJSON('/api/admin/accounts').then(setD).catch((e) => setErr(e.message)); }, [tick]);
  if (err) return <div role="alert" className="adm-alert">{err}</div>;
  if (!d) return <Spinner />;
  const list = d.accounts.filter((a) => !q || (a.email + ' ' + a.name + ' ' + a.workspace.name).toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="adm-list">
      <input className="adm-input" placeholder="Buscar por e-mail, nome ou estúdio" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar conta" />
      <p className="g-muted" style={{ margin: 0, fontSize: 12.5 }}>Teto da plataforma: {usd(ov.limits.platform_cap_usd)}/mês. O teto efetivo de cada estúdio é o menor entre o dele e o da plataforma.</p>
      {list.map((a) => (
        <div key={a.id} className="g-card adm-acc">
          <button type="button" className="adm-acc-head" aria-expanded={open === a.id} onClick={() => setOpen(open === a.id ? null : a.id)}>
            <span className="adm-acc-who"><strong>{a.email}</strong>{a.admin && <span className="adm-tag">ADMIN</span>}{a.id === ov.me.id && <span className="adm-tag">você</span>}
              <span className="g-muted">{a.name} · {a.workspace.name}</span></span>
            <span className="adm-acc-cols">
              <span>{a.mode === 'real' ? 'REAL' : 'DEMO'}</span>
              <span>real {a.allow_real ? 'liberado' : 'bloqueado'}</span>
              <span>teto {usd(a.monthly_cap_usd)}</span>
              <span>saldo {a.exempt ? 'isento' : a.balance}</span>
              <span>reservado {a.held}</span>
              <span>e-mail {a.email_verified ? 'confirmado' : 'pendente'}</span>
            </span>
          </button>
          {open === a.id && <AccountActions a={a} ov={ov} ask={ask} setSecret={setSecret} tick={tick} />}
        </div>
      ))}
      {list.length === 0 && <p className="g-muted">Nenhuma conta encontrada.</p>}
    </div>
  );
}

function AccountActions({ a, ov, ask, setSecret, tick }) {
  const base = `/api/admin/accounts/${a.id}`;
  const [cap, setCap] = React.useState(String(a.monthly_cap_usd));
  const [cr, setCr] = React.useState('');
  const [crErr, setCrErr] = React.useState(null);
  const [stmt, setStmt] = React.useState(null);
  const credit = (kind) => {
    const n = parseCredits(cr);
    const e = checkCredits(kind, n, ov.limits);
    setCrErr(e);
    if (!e) ask(kind, { account: a, input: { credits: n }, path: `${base}/${kind}`, body: { credits: n }, after: () => setCr('') });
  };
  const download = (data) => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url; link.download = `kiroo-conta-${a.id}.json`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  React.useEffect(() => { if (stmt) getJSON(`${base}/statement`).then(setStmt).catch(() => {}); }, [tick]);   // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="adm-acc-body">
      <section>
        <h4>Modo real e teto</h4>
        <div className="adm-row">
          {a.allow_real
            ? <button className="g-btn g-sm" onClick={() => ask('deny-real', { account: a, path: `${base}/deny-real` })}>Bloquear modo real</button>
            : <button className="g-btn g-sm" onClick={() => ask('allow-real', { account: a, path: `${base}/allow-real` })}>Liberar modo real</button>}
          <button className="g-btn g-sm" disabled={a.mode === 'simulated'} onClick={() => ask('set-mode', { account: a, input: { mode: 'simulated' }, path: `${base}/set-mode`, body: { mode: 'simulated' } })}>Modo DEMO</button>
          <button className="g-btn g-sm" disabled={a.mode === 'real' || !a.allow_real} title={a.allow_real ? '' : 'Libere o modo real antes'} onClick={() => ask('set-mode', { account: a, input: { mode: 'real' }, path: `${base}/set-mode`, body: { mode: 'real' } })}>Modo REAL</button>
        </div>
        <div className="adm-row">
          <label className="adm-inline">Teto mensal (US$)
            <input className="adm-input adm-num" inputMode="decimal" value={cap} onChange={(e) => setCap(e.target.value)} />
          </label>
          <button className="g-btn g-sm" onClick={() => { const n = Number(cap.replace(',', '.')); ask('set-cap', { account: a, input: { usd: n }, path: `${base}/set-cap`, body: { usd: n } }); }}>Definir teto</button>
          <span className="g-muted">máx. {usd(ov.limits.platform_cap_usd)} (plataforma)</span>
        </div>
      </section>
      <section>
        <h4>Créditos</h4>
        <div className="adm-row">
          <label className="adm-inline">Créditos
            <input className="adm-input adm-num" inputMode="decimal" value={cr} onChange={(e) => setCr(e.target.value)} placeholder="ex.: 50 ou -10" />
          </label>
          <button className="g-btn g-sm" onClick={() => credit('grant')}>Conceder</button>
          <button className="g-btn g-sm" onClick={() => credit('adjust')}>Ajustar (aceita negativo)</button>
        </div>
        {crErr && <div role="alert" className="adm-alert">{crErr}</div>}
        <button className="g-btn g-sm" onClick={() => (stmt ? setStmt(null) : getJSON(`${base}/statement`).then(setStmt).catch(() => {}))}>{stmt ? 'Esconder extrato' : 'Ver extrato'}</button>
        {stmt && (
          <ul className="adm-stmt">
            {stmt.statement.length === 0 && <li className="g-muted">Sem lançamentos.</li>}
            {stmt.statement.map((e) => (
              <li key={e.id}><span className="g-muted">{when(e.at)}</span><span style={{ flex: 1 }}>{e.label}{e.note ? ' — ' + e.note : ''}</span>
                <strong>{e.amount_cc > 0 ? '+' : ''}{e.amount}</strong></li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h4>Acesso e dados</h4>
        <div className="adm-row">
          <button className="g-btn g-sm" disabled={a.email_verified} onClick={() => ask('verify-email', { account: a, path: `${base}/verify-email` })}>Confirmar e-mail à mão</button>
          <button className="g-btn g-sm" onClick={() => ask('reset-link', { account: a, path: `${base}/reset-link`, after: (r) => setSecret({ label: 'Link de nova senha (30 min, uso único)', value: r.link, notice: r.notice }) })}>Gerar link de nova senha</button>
          <button className="g-btn g-sm" onClick={() => ask('export', { account: a, path: `${base}/export`, after: download })}>Exportar dados</button>
        </div>
        <p className="g-muted" style={{ margin: 0, fontSize: 12 }}>Apagar a conta: só pela CLI (<code>studio admin delete-user</code>).</p>
      </section>
    </div>
  );
}

// ------------------------------------------------------------------ convites
function Invites({ ask, tick, setSecret }) {
  const [d, setD] = React.useState(null);
  const [days, setDays] = React.useState('7');
  const [email, setEmail] = React.useState('');
  const [note, setNote] = React.useState('');
  React.useEffect(() => { getJSON('/api/admin/invites').then(setD).catch(() => setD({ invites: [] })); }, [tick]);
  const n = Number(days);
  const okDays = Number.isInteger(n) && n >= 1 && n <= 30;
  return (
    <div className="adm-list">
      <div className="g-card adm-acc-body">
        <h4>Novo convite</h4>
        <div className="adm-row">
          <label className="adm-inline">Validade (1 a 30 dias)<input className="adm-input adm-num" inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value)} /></label>
          <label className="adm-inline">Só para o e-mail (opcional)<input className="adm-input" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
          <label className="adm-inline">Nota<input className="adm-input" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} /></label>
          <button className="g-btn g-sm g-lime" disabled={!okDays} onClick={() => ask('create-invite', { input: { days: n, email: email.trim() }, path: '/api/admin/invites',
            body: { days: n, email: email.trim(), note },
            after: (r) => { setSecret({ label: 'Código do convite', value: r.code, notice: r.notice }); setEmail(''); setNote(''); } })}>Criar convite</button>
        </div>
      </div>
      {!d ? <Spinner /> : (
        <ul className="adm-stmt">
          {d.invites.length === 0 && <li className="g-muted">Nenhum convite.</li>}
          {d.invites.map((i) => (
            <li key={i.id}>
              <span className="g-muted">{i.id}</span>
              <span style={{ flex: 1 }}>{i.state} · expira {when(i.expires_at)}{i.email ? ' · ' + i.email : ''}{i.note ? ' · ' + i.note : ''}</span>
              {i.state === 'válido' && <button className="g-btn g-sm" onClick={() => ask('revoke-invite', { input: { id: i.id }, path: `/api/admin/invites/${i.id}/revoke` })}>Revogar</button>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ métricas (Parte A)
function Metrics() {
  const [days, setDays] = React.useState(30);
  const [m, setM] = React.useState(null);
  React.useEffect(() => { setM(null); getJSON(`/api/admin/metrics?days=${days}`).then(setM).catch(() => setM({ error: true })); }, [days]);
  return (
    <div className="adm-list">
      <div style={{ display: 'flex', gap: 6 }}>
        {[[7, '7 dias'], [30, '30 dias'], [90, '90 dias'], [0, 'Tudo']].map(([d, l]) => (
          <button key={d} className="g-chip" aria-pressed={days === d} onClick={() => setDays(d)}>{l}</button>
        ))}
      </div>
      {!m ? <Spinner /> : m.error ? <div className="adm-alert">Não foi possível carregar as métricas.</div> : (
        <>
          {[['real', 'Real'], ['simulated', 'DEMO (custo equivalente estimado)']].map(([k, title]) => <MetricBlock key={k} title={title} b={m[k]} />)}
          {m.outside_productions.length > 0 && (
            <div className="g-card adm-acc-body">
              <h4>Fora das produções</h4>
              <table className="adm-table"><tbody>
                {m.outside_productions.map((r) => <tr key={r.key}><td>{r.label}</td><td>{r.provider}</td><td>{r.calls} chamadas</td><td>{usd(r.usd)}</td></tr>)}
              </tbody></table>
            </div>
          )}
          <p className="g-muted" style={{ margin: 0, fontSize: 12 }}>Só agregados: sem e-mail, nome, produto ou id. Também em <code>studio admin metrics</code>.</p>
        </>
      )}
    </div>
  );
}

function MetricBlock({ title, b }) {
  const pct = b.interrupted_by_ops_budget_pct;
  return (
    <div className="g-card adm-acc-body">
      <h4>{title}</h4>
      <div className="adm-kpis">
        <div><span className="g-label">Custo médio por vídeo entregue</span><strong>{usd(b.avg_cost_per_delivered_usd)}</strong><span className="g-muted">{b.delivered} entregues de {b.productions}</span></div>
        <div><span className="g-label">Interrompidas por orçamento operacional</span><strong>{pct === null ? '—' : pct + '%'}</strong><span className="g-muted">{b.interrupted_by_ops_budget} produções</span></div>
        <div><span className="g-label">Tentativas médias por cena</span><strong>{b.avg_attempts_per_scene ?? '—'}</strong>
          <span className="g-muted">{Object.entries(b.avg_attempts_per_scene_by_kind).map(([k, x]) => `${k}: ${x ?? '—'}`).join(' · ')}</span></div>
      </div>
      {[['Custo por operação', b.by_operation], ['Custo por provedor', b.by_provider]].map(([h, rows]) => (
        <table key={h} className="adm-table">
          <caption>{h}</caption>
          <thead><tr><th>Item</th><th>Chamadas</th><th>Falhas</th><th>Total</th><th>Média</th></tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={5} className="g-muted">Nada no período.</td></tr>}
            {rows.map((r) => <tr key={r.key}><td>{r.label}</td><td>{r.calls}</td><td>{r.failed}</td><td>{usd(r.usd)}</td><td>{usd(r.avg_usd)}</td></tr>)}
          </tbody>
        </table>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ auditoria (somente leitura)
function Audit({ tick }) {
  const [rows, setRows] = React.useState(null);
  const [more, setMore] = React.useState(true);
  React.useEffect(() => { getJSON('/api/admin/audit?limit=100').then((d) => { setRows(d.entries); setMore(d.entries.length === 100); }).catch(() => setRows([])); }, [tick]);
  const loadMore = () => {
    const last = rows[rows.length - 1];
    getJSON(`/api/admin/audit?limit=100&before=${last.id}`).then((d) => { setRows([...rows, ...d.entries]); setMore(d.entries.length === 100); });
  };
  if (!rows) return <Spinner />;
  return (
    <div className="adm-list">
      <p className="g-muted" style={{ margin: 0, fontSize: 12.5 }}>Somente leitura. O banco recusa editar ou apagar linhas desta trilha.</p>
      <ul className="adm-stmt">
        {rows.length === 0 && <li className="g-muted">Nenhuma ação registrada.</li>}
        {rows.map((e) => (
          <li key={e.id} className={e.self_action ? 'adm-self-row' : undefined}>
            <span className="g-muted" style={{ width: 96, flex: 'none' }}>{when(e.at)}</span>
            <span style={{ flex: 1 }}>
              <strong>{auditLine(e)}</strong>{e.self_action && <span className="adm-tag">PRÓPRIA CONTA</span>}
              <span className="g-muted"> — por {e.actor_email || e.actor_kind}{e.target_email ? ' em ' + e.target_email : ''}{e.ip ? ' · IP ' + e.ip : ''}</span>
              {e.reason && <span className="g-muted"> · motivo: {e.reason}</span>}
              {e.error && <span className="g-muted"> · {e.error}</span>}
              {(e.before || e.after) && <span className="adm-diff">{e.before ? JSON.stringify(e.before) : '—'} → {e.after ? JSON.stringify(e.after) : '—'}</span>}
            </span>
          </li>
        ))}
      </ul>
      {more && rows.length > 0 && <button className="g-btn g-sm" onClick={loadMore}>Carregar mais</button>}
      <p className="g-muted" style={{ margin: 0, fontSize: 12 }}>Também em <code>studio admin audit</code>.</p>
    </div>
  );
}
