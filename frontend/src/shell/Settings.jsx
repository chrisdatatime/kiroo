import React from 'react';
import { BadgeCheck, Coins, Download, RotateCcw, Trash2, UserRound } from 'lucide-react';
import { auth, getJSON, post } from '../engine/api.js';
import { DeleteBox } from '../ui/Account.jsx';
import { Spinner } from '../ui/bits.jsx';
import { FEATURES, PRIVACY_EMAIL } from '../config/appConfig.js';
import KirooAvatar from './KirooAvatar.jsx';
import { Spark } from './AccountMenu.jsx';
import { displayName } from './accountMenu.js';
import { SETTINGS_TABS, balanceSentence, billingActions, originRows, profileChanges, statementLine } from './settings.js';
import '../ui/prefs.css';
import './settings.css';

// Configurações: abas centralizadas Perfil | Créditos (design `Conta` e `Creditos`). É uma tela (view `config`), não modal.
// As partes `*View` são puras (renderizadas nos testes); `Settings` busca os dados e fala com a API.
const TAB_ICONS = { perfil: UserRound, creditos: Coins };

export function SettingsTabs({ tab, onTab }) {
  return (
    <nav className="st-tabs" aria-label="Configurações">
      {SETTINGS_TABS.map((t) => {
        const Ic = TAB_ICONS[t.id];
        return (
          <button key={t.id} type="button" className="st-tab" aria-current={tab === t.id ? 'page' : undefined} onClick={() => onTab(t.id)}>
            <Ic size={16} aria-hidden="true" />{t.label}
          </button>
        );
      })}
    </nav>
  );
}

const Soon = () => <span className="st-soon">em breve</span>;

function Toggle({ label, desc, on }) {
  return (
    <div className="st-toggle-row">
      <span><span className="st-t1">{label}</span><span className="st-t2">{desc}</span></span>
      <span className="st-toggle-ctl">
        <input type="checkbox" role="switch" aria-label={label} defaultChecked={on} disabled className="st-switch" />
      </span>
    </div>
  );
}

// ------------------------------------------------------------------ Perfil
export function ProfileView({ a, busy, msg, onSave, onVerify, onCode, codeSent, pwOpen, setPwOpen, onPassword, del, setDel, onDelete }) {
  const u = a.user || {};
  const [form, setForm] = React.useState({ name: u.name || '', tax: '' });
  React.useEffect(() => { setForm({ name: u.name || '', tax: '' }); }, [u.name, u.tax_doc]);
  const changes = profileChanges(u, form);
  const dirty = Object.keys(changes).length > 0;
  return (
    <>
      <section className="st-card st-card-lg" aria-labelledby="st-me">
        <div className="st-id">
          <KirooAvatar user={u} size={72} />
          <div className="st-id-txt">
            <h2 id="st-me" className="st-h2">{displayName(a)}</h2>
            <div className="st-muted">{u.email}</div>
            <div className="st-tiny">Seu kiroo é sorteado quando a conta é criada.</div>
          </div>
        </div>
        {msg && <div role="status" className={msg.ok ? 'st-ok' : 'st-err'}>{msg.text}</div>}
        <form className="st-form" onSubmit={(e) => { e.preventDefault(); if (dirty) onSave(changes); }}>
          <label className="st-field"><span className="st-label">Nome</span>
            <span className="st-input"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} autoComplete="name" maxLength={80} required /></span>
          </label>
          <div className="st-field"><span className="st-label" id="st-mail">E-mail</span>
            <span className="st-input is-ro"><input value={u.email || ''} readOnly aria-labelledby="st-mail" />
              {u.email_verified
                ? <span className="st-verified"><BadgeCheck size={14} aria-hidden="true" />Verificado</span>
                : <span className="st-unverified">Não confirmado</span>}
            </span>
            {!u.email_verified && <span><button type="button" className="st-btn st-btn-sm" onClick={onVerify} disabled={busy}>Confirmar e-mail</button></span>}
            {!u.email_verified && codeSent && (
              <span className="st-inline">
                <input className="st-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} aria-label="Código de 6 dígitos" placeholder="Código de 6 dígitos"
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); onCode(e.currentTarget.value); } }} />
                <span className="st-tiny">Digite o código e aperte Enter.</span>
              </span>
            )}
          </div>
          <label className="st-field"><span className="st-label">CPF ou CNPJ</span>
            <span className="st-input"><input value={form.tax} onChange={(e) => setForm({ ...form, tax: e.target.value })} inputMode="numeric" autoComplete="off"
              placeholder={u.tax_doc || 'Somente números'} aria-describedby="st-tax-help" /></span>
            <span className="st-tiny" id="st-tax-help">Opcional. Usado só para a nota fiscal das suas compras. Sai do Kiroo junto com a conta; notas já emitidas seguem com a contabilidade pelo prazo legal.{u.tax_doc ? ' Deixe vazio para manter o atual.' : ''}</span>
          </label>
          <div><button type="submit" className="st-btn st-btn-dark" disabled={busy || !dirty}>Salvar alterações</button></div>
        </form>
      </section>

      <section className="st-card" aria-labelledby="st-sec">
        <h3 id="st-sec" className="st-h3">Segurança</h3>
        <div className="st-rows">
          <div className="st-row">
            <span><span className="st-t1">Login com Google</span><span className="st-t2">{u.google ? 'Conectado' : 'Não conectado'}</span></span>
            {u.google && (FEATURES.googleUnlink ? <button type="button" className="st-btn st-btn-sm">Desconectar</button>
              : <span className="st-row-act"><button type="button" className="st-btn st-btn-sm" disabled>Desconectar</button><Soon /></span>)}
          </div>
          <div className="st-row st-row-col">
            <div className="st-row-top">
              <span><span className="st-t1">Senha</span><span className="st-t2">{u.has_password === false ? 'Sem senha: você entra com o Google' : 'Definida'}</span></span>
              {u.has_password !== false && <button type="button" className="st-btn st-btn-sm" aria-expanded={pwOpen} onClick={() => setPwOpen(!pwOpen)}>{pwOpen ? 'Cancelar' : 'Trocar senha'}</button>}
            </div>
            {u.has_password === false && <span className="st-tiny">Para criar uma senha, use “Esqueci a senha” na tela de entrada.</span>}
            {pwOpen && (
              <form className="pf-form" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); onPassword(String(f.get('current') || ''), String(f.get('new') || '')); }}>
                <input name="current" type="password" aria-label="Senha atual" placeholder="Senha atual" autoComplete="current-password" required />
                <input name="new" type="password" aria-label="Nova senha" placeholder="Nova senha (10+ caracteres)" autoComplete="new-password" minLength={10} required />
                <button type="submit" className="st-btn st-btn-dark" disabled={busy}>Salvar senha</button>
              </form>
            )}
          </div>
        </div>
      </section>

      <section className="st-card" aria-labelledby="st-notif">
        <h3 id="st-notif" className="st-h3">Notificações por e-mail {!FEATURES.emailNotifications && <Soon />}</h3>
        <div className="st-rows st-rows-gap">
          <Toggle label="Vídeo pronto para aprovar" desc="Quando a equipe terminar uma produção." on />
          <Toggle label="Recibos de compra" desc="Confirmação de pagamento e créditos." on />
          <Toggle label="Novidades do Kiroo" desc="No máximo 1 por mês." on={false} />
        </div>
      </section>

      <section className="st-card" aria-labelledby="st-priv">
        <h3 id="st-priv" className="st-h3 st-h3-tight">Privacidade e dados</h3>
        <p className="st-muted st-p">Seus direitos pela LGPD. Dúvidas: <a href={`mailto:${PRIVACY_EMAIL}`}>{PRIVACY_EMAIL}</a></p>
        <div className="st-rows">
          <div className="st-row">
            <span><span className="st-t1">Exportar meus dados</span><span className="st-t2">Cópia da conta, produções e extrato.</span></span>
            <a className="st-btn st-btn-sm" href="/api/account/export" download><Download size={14} aria-hidden="true" />Exportar</a>
          </div>
          <div className="st-row is-danger">
            <span><span className="st-t1">Excluir conta</span><span className="st-t2">Apaga a conta e os dados pessoais, exceto o que a lei obriga a guardar.</span></span>
            <button type="button" className="st-btn st-btn-sm st-btn-danger" aria-expanded={!!del} onClick={() => setDel(!del)}><Trash2 size={14} aria-hidden="true" />Excluir</button>
          </div>
          {del && <DeleteBox email={u.email} hasPassword={u.has_password !== false} busy={busy} onDelete={onDelete} onCancel={() => setDel(false)} />}
        </div>
      </section>
    </>
  );
}

// ------------------------------------------------------------------ Créditos
export function CreditsTabView({ d, onPricing, onPortal, portalBusy, portalErr }) {
  const s = balanceSentence(d);
  const pay = billingActions(d);
  const rows = d.exempt ? [] : originRows(d.origins);
  const lines = (d.statement || []).map(statementLine);
  return (
    <>
      <section className="st-card st-card-lg" aria-labelledby="st-cred">
        <div className="st-cred-top">
          <div className="st-cred-title">
            <h2 id="st-cred" className="st-h2 st-h2-xl">Seus créditos</h2>
            <span className="st-chip" aria-label={d.exempt ? 'Isento' : `${d.balance} créditos`}><Spark />{d.exempt ? 'Isento' : d.balance}</span>
          </div>
          {!d.exempt && <button type="button" className="st-btn st-btn-accent" onClick={onPricing}>Planos e créditos</button>}
        </div>
        <h3 className="st-h3 st-h3-mt">Saldo</h3>
        {typeof s === 'string' ? <p className="st-muted st-p0">{s}</p> : <p className="st-muted st-p0">{s.lead} <b>{s.strong}</b>.</p>}
        <div className="st-origins">
          {rows.map((o) => (
            <div key={o.key} className="st-origin">
              <div className="st-origin-top">
                <span><span className="st-t1">{o.label}</span>{o.note && <span className="st-t2">{o.note}</span>}</span>
                <span className="st-t2"><b className="st-num">{o.left} / {o.received}</b> restantes</span>
              </div>
              <div className="st-bar" role="progressbar" aria-label={`${o.label}: ${o.left} de ${o.received} restantes`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={o.pct}>
                <i data-accent={o.accent || undefined} style={{ width: `${o.pct}%` }} />
              </div>
            </div>
          ))}
          {rows.length === 0 && !d.exempt && <p className="st-t2 st-origin-empty">Nenhum crédito recebido ainda.</p>}
          <div className="st-refund"><RotateCcw size={16} aria-hidden="true" />Se uma produção falhar por erro técnico, os créditos voltam automaticamente.</div>
        </div>
        <div className="st-pay">
          <div><div className="st-t1">Pagamentos</div><div className="st-t2">Pix ou cartão, pela Stripe.</div></div>
          <span className="st-row-act">
            {pay.manage && <button type="button" className="st-btn st-btn-sm" onClick={onPortal} disabled={portalBusy}>Gerenciar assinatura</button>}
            {FEATURES.receipts && pay.receipts ? <button type="button" className="st-btn st-btn-sm" onClick={onPortal} disabled={portalBusy}>Recibos</button>
              : <><button type="button" className="st-btn st-btn-sm" disabled>Recibos</button>{!FEATURES.receipts && <Soon />}</>}
          </span>
        </div>
        {portalErr && <div role="alert" className="st-err">{portalErr}</div>}
      </section>

      <section className="st-card" aria-labelledby="st-ext">
        <div className="st-ext-head">
          <h3 id="st-ext" className="st-h3 st-h3-tight">Extrato</h3>
          <a className="st-btn st-btn-sm" href="/api/credits/statement.csv" download><Download size={14} aria-hidden="true" />Baixar CSV</a>
        </div>
        {lines.length === 0 ? <p className="st-t2 st-p">Sem lançamentos ainda.</p> : (
          <table className="st-table">
            <caption className="sr-only">Movimentações de créditos</caption>
            <thead className="sr-only"><tr><th scope="col">Data</th><th scope="col">Descrição</th><th scope="col">Créditos</th></tr></thead>
            <tbody>
              {lines.map((l) => (
                <tr key={l.id}>
                  <td className="st-date">{l.date}</td>
                  <td>{l.title}{l.status && <span className="st-status">{l.status}</span>}</td>
                  <td className="st-amt" data-tone={l.tone}>{l.amount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}

function CreditsTab({ v }) {
  const [d, setD] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [pErr, setPErr] = React.useState(null);
  React.useEffect(() => { getJSON('/api/credits').then(setD).catch((e) => setErr(e.message)); }, []);
  if (err) return <div role="alert" className="st-err">{err}</div>;
  if (!d) return <div className="st-load" aria-busy="true"><Spinner /></div>;
  const portal = async () => {
    setBusy(true); setPErr(null);
    try { const r = await post('/api/payments/portal', {}); if (r.redirect_url) { window.location.assign(r.redirect_url); return; } }
    catch (e) { setPErr(e.message); }
    setBusy(false);
  };
  return <CreditsTabView d={d} onPricing={v.openPricing} onPortal={portal} portalBusy={busy} portalErr={pErr} />;
}

function ProfileTab({ v }) {
  const a = v.account;
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState(null);
  const [codeSent, setCodeSent] = React.useState(false);
  const [pwOpen, setPwOpen] = React.useState(false);
  const [del, setDel] = React.useState(false);
  if (!a) return null;
  const run = async (fn, okText) => {
    setBusy(true); setMsg(null);
    try { await fn(); if (okText) setMsg({ ok: true, text: okText }); if (v.refreshAccount) await v.refreshAccount(); }
    catch (e) { setMsg({ ok: false, text: e.message }); }
    finally { setBusy(false); }
  };
  return (
    <ProfileView a={a} busy={busy} msg={msg} codeSent={codeSent} pwOpen={pwOpen} setPwOpen={setPwOpen} del={del} setDel={setDel}
      onSave={(c) => run(async () => {
        if (c.name) await post('/api/account/name', { name: c.name });
        if (c.tax) await post('/api/account/tax-doc', { document: c.tax });
      }, 'Alterações salvas.')}
      onPassword={(current, next) => run(async () => { await post('/api/account/password', { current, new: next }); setPwOpen(false); }, 'Senha alterada.')}
      onVerify={() => run(async () => { await auth('resend'); setCodeSent(true); }, 'Enviamos um código para o seu e-mail.')}
      onCode={(code) => run(async () => { await auth('verify', { code: String(code || '') }); setCodeSent(false); }, 'E-mail confirmado.')}
      onDelete={(typed, pw) => run(async () => { await post('/api/account/delete', { confirm: typed, password: pw, email: typed }); window.location.assign('/'); })} />
  );
}

export default function Settings({ v }) {
  const tab = v.cfgTab === 'creditos' ? 'creditos' : 'perfil';
  return (
    <div className="pv-scroll st-scroll">
      <div className="st-page">
        <SettingsTabs tab={tab} onTab={v.setCfgTab} />
        {tab === 'perfil' ? <ProfileTab v={v} /> : <CreditsTab v={v} />}
      </div>
    </div>
  );
}
