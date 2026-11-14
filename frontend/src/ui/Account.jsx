import React from 'react';
import { Check, MessageCircle } from 'lucide-react';
import { auth, post } from '../engine/api.js';
import { canDelete, helpCard, initialOf, planName, planPerks, taxDocRow } from './prefs.js';
import './prefs.css';

// Minha conta (Preferências): identidade, plano, ajuda e dados editáveis (nome, senha, CPF/CNPJ para nota fiscal).
// `AccountView` é pura (testada por renderização); `AccountContent` guarda o estado e fala com a API.
function EditRow({ label, value, action, editing, children, onToggle }) {
  return (
    <div className="pf-rowline">
      <div>
        <div className="pf-k">{label}</div>
        <div className="pf-val">{value}</div>
        {editing && children}
      </div>
      <button type="button" className="pf-link" onClick={onToggle} aria-expanded={!!editing}>{editing ? 'Cancelar' : action}</button>
    </div>
  );
}

export function AccountView({ a, site, edit, setEdit, busy, msg, onSave, onVerify, onCode, codeSent, onLogout, onDelete, openPackages, del, setDel }) {
  const u = a.user, plan = a.plan || {};
  const perks = planPerks(plan), help = helpCard(plan, site), doc = taxDocRow(u.tax_doc);
  const Form = ({ field, label, type = 'text', placeholder, extra }) => (
    <form className="pf-form" onSubmit={(e) => { e.preventDefault(); onSave(field, new FormData(e.currentTarget)); }}>
      {extra}
      <input name="v" type={type} aria-label={label} placeholder={placeholder} defaultValue={field === 'name' ? u.name : ''} autoComplete={field === 'password' ? 'new-password' : 'off'} required={field !== 'tax'} />
      <button type="submit" className="pf-btn is-dark" disabled={busy}>Salvar</button>
    </form>
  );
  return (
    <div className="pf">
      <header className="pf-id">
        <div className="pf-avatar" aria-hidden="true">{initialOf(u)}</div>
        <div className="pf-id-main">
          <div className="pf-name">{u.name || 'Sem nome'}</div>
          <div className="pf-mail">
            <span>{u.email}</span>
            {u.email_verified
              ? <span className="pf-pill is-ok"><Check size={12} aria-hidden="true" /> Verificado</span>
              : <button type="button" className="pf-btn is-soft" onClick={onVerify}>Confirmar e-mail</button>}
          </div>
          {!u.email_verified && codeSent && (
            <form className="pf-form" onSubmit={(e) => { e.preventDefault(); onCode(new FormData(e.currentTarget).get('code')); }}>
              <input name="code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} aria-label="Código de 6 dígitos" placeholder="Código de 6 dígitos" required />
              <button type="submit" className="pf-btn is-dark" disabled={busy}>Confirmar</button>
            </form>
          )}
        </div>
        <button type="button" className="pf-btn" onClick={() => setEdit(edit === 'name' ? null : 'name')}>Editar perfil</button>
      </header>
      {msg && <div role="status" className={msg.ok ? 'pf-ok' : 'pf-err'}>{msg.text}</div>}
      <div className="pf-two">
        <section className="pf-card is-ink" aria-label="Seu plano">
          <div className="pf-k">Seu plano</div>
          <span className="pf-pill is-ink">{planName(plan)}</span>
          {perks.length > 0 && <ul className="pf-perks">{perks.map((p) => <li key={p}><Check size={16} color="#166534" aria-hidden="true" />{p}</li>)}</ul>}
          {a.payments && a.payments.online && <div><button type="button" className="pf-link" onClick={openPackages}>Ver pacotes</button></div>}
        </section>
        {help && (
          <section className="pf-card is-bg" aria-label="Precisa de ajuda?">
            <div className="pf-k">Precisa de ajuda?</div>
            <p>{help.text}</p>
            {help.kind === 'whatsapp'
              ? <div><a className="pf-btn is-dark" href={help.href} target="_blank" rel="noopener noreferrer"><MessageCircle size={16} aria-hidden="true" />{help.cta}</a></div>
              : (help.href ? <div><a className="pf-btn" href={help.href} target="_blank" rel="noopener noreferrer">{help.label}</a></div> : <p className="pf-t1">{help.label}</p>)}
          </section>
        )}
      </div>
      <div className="pf-rows">
        <EditRow label="Nome" value={u.name || 'Sem nome'} action="Alterar" editing={edit === 'name'} onToggle={() => setEdit(edit === 'name' ? null : 'name')}>
          <Form field="name" label="Novo nome" />
        </EditRow>
        {u.has_password !== false && (
          <EditRow label="Senha" value="••••••••••" action="Alterar" editing={edit === 'password'} onToggle={() => setEdit(edit === 'password' ? null : 'password')}>
            <form className="pf-form" onSubmit={(e) => { e.preventDefault(); onSave('password', new FormData(e.currentTarget)); }}>
              <input name="current" type="password" aria-label="Senha atual" placeholder="Senha atual" autoComplete="current-password" required />
              <input name="v" type="password" aria-label="Nova senha" placeholder="Nova senha (10+ caracteres)" autoComplete="new-password" minLength={10} required />
              <button type="submit" className="pf-btn is-dark" disabled={busy}>Salvar</button>
            </form>
          </EditRow>
        )}
        <EditRow label="CPF ou CNPJ para nota fiscal" value={doc.value} action={doc.action} editing={edit === 'tax'} onToggle={() => setEdit(edit === 'tax' ? null : 'tax')}>
          <Form field="tax" label="CPF ou CNPJ" placeholder="Somente números" />
        </EditRow>
      </div>
      <footer className="pf-foot">
        <button type="button" className="pf-btn" onClick={onLogout}>Sair</button>
        <button type="button" className="pf-link is-danger" onClick={() => setDel(!del)} aria-expanded={!!del}>Excluir conta</button>
      </footer>
      {del && <DeleteBox email={u.email} hasPassword={u.has_password !== false} busy={busy} onDelete={onDelete} onCancel={() => setDel(false)} />}
    </div>
  );
}

function DeleteBox({ email, hasPassword, busy, onDelete, onCancel }) {
  const [typed, setTyped] = React.useState('');
  const [pw, setPw] = React.useState('');
  const ok = canDelete(typed, email) && (!hasPassword || pw.length > 0);
  return (
    <section className="pf-del" role="alertdialog" aria-label="Excluir conta">
      <div className="pf-t1">Excluir conta para sempre</div>
      <p className="pf-muted">Apaga seus dados, vídeos e créditos. Não dá para desfazer. Digite <strong>{email}</strong> para confirmar.</p>
      <div className="pf-form">
        <input value={typed} onChange={(e) => setTyped(e.target.value)} aria-label="Digite seu e-mail para confirmar" placeholder={email} autoComplete="off" />
        {hasPassword && <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} aria-label="Sua senha" placeholder="Sua senha" autoComplete="current-password" />}
      </div>
      <div className="pf-form">
        <button type="button" className="pf-btn" onClick={onCancel}>Cancelar</button>
        <button type="button" className="pf-btn is-dark" style={{ background: '#B91C1C', borderColor: '#B91C1C' }} disabled={!ok || busy} onClick={() => onDelete(typed, pw)}>Excluir conta</button>
      </div>
    </section>
  );
}

export function AccountContent({ v }) {
  const a = v.account;
  const [edit, setEdit] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState(null);
  const [codeSent, setCodeSent] = React.useState(false);
  const [del, setDel] = React.useState(false);
  if (!a) return null;
  const run = async (fn, okText) => {
    setBusy(true); setMsg(null);
    try { await fn(); if (okText) setMsg({ ok: true, text: okText }); setEdit(null); if (v.refreshAccount) await v.refreshAccount(); }
    catch (e) { setMsg({ ok: false, text: e.message }); }
    finally { setBusy(false); }
  };
  const onSave = (field, fd) => {
    const val = String(fd.get('v') || '');
    if (field === 'name') return run(() => post('/api/account/name', { name: val }), 'Nome atualizado.');
    if (field === 'password') return run(() => post('/api/account/password', { current: String(fd.get('current') || ''), new: val }), 'Senha alterada.');
    return run(() => post('/api/account/tax-doc', { document: val }), val.trim() ? 'CPF/CNPJ salvo.' : 'CPF/CNPJ removido.');
  };
  return (
    <AccountView a={a} site={a.site} edit={edit} setEdit={setEdit} busy={busy} msg={msg} onSave={onSave} codeSent={codeSent}
      onVerify={() => run(async () => { await auth('resend'); setCodeSent(true); }, 'Enviamos um código para o seu e-mail.')}
      onCode={(code) => run(async () => { await auth('verify', { code: String(code || '') }); setCodeSent(false); }, 'E-mail confirmado.')}
      onLogout={v.logout} openPackages={() => v.openPrefs('buy')} del={del} setDel={setDel}
      onDelete={(typed, pw) => run(async () => { await post('/api/account/delete', { confirm: typed, password: pw, email: typed }); window.location.assign('/'); })} />
  );
}
