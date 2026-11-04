import React from 'react';
import Boneco from '../Boneco.jsx';
import { auth } from '../engine/api.js';
import logo from '../assets/logo-dark.png';
import pattern from '../assets/pattern.webp';
import { AboutContent } from './About.jsx';

// Entrar / criar conta / esqueci a senha / nova senha — no estilo do estúdio.
const LOOKS = [
  { shirt: '#FF8FC0', acc: 'bone' },
  { shirt: '#D5F45B', acc: 'fones' },
  { shirt: '#FF9A3D', acc: 'oculos' },
];

// O servidor recusa cadastro em endereço público (só convite); aqui apenas não oferecemos a opção.
const SIGNUP_OPEN = ['localhost', '127.0.0.1'].includes(window.location.hostname);

function Field({ id, label, type = 'text', value, onChange, autoComplete, hint }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label className="g-label" htmlFor={id}>{label}</label>
      <input id={id} className="g-field" type={type} value={value} onChange={(e) => onChange(e.target.value)} autoComplete={autoComplete} required />
      {hint && <span className="g-muted" style={{ fontSize: 12 }}>{hint}</span>}
    </div>
  );
}

export default function AuthScreen({ onDone, resetToken }) {
  const [mode, setMode] = React.useState(resetToken ? 'reset' : 'login');
  const [f, setF] = React.useState({ name: '', email: '', password: '' });
  const [msg, setMsg] = React.useState(null);
  const [about, setAbout] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      if (mode === 'login') { await auth('login', { email: f.email, password: f.password }); onDone(); }
      else if (mode === 'signup') { await auth('signup', { name: f.name, email: f.email, password: f.password }); onDone(); }
      else if (mode === 'forgot') { const r = await auth('forgot', { email: f.email }); setMsg({ ok: true, text: r.message }); }
      else if (mode === 'reset') {
        await auth('reset', { token: resetToken, password: f.password });
        window.history.replaceState(null, '', '/');
        setMode('login'); setMsg({ ok: true, text: 'Senha alterada. Entre com a nova senha.' });
      }
    } catch (err) { setMsg({ ok: false, text: err.message }); }
    finally { setBusy(false); }
  };

  const title = { login: 'Entrar no estúdio', signup: 'Criar sua conta', forgot: 'Esqueci a senha', reset: 'Nova senha' }[mode];
  const cta = { login: 'Entrar', signup: 'Criar conta e entrar', forgot: 'Gerar link', reset: 'Salvar nova senha' }[mode];

  return (
    <div style={{ background: '#17234B', position: 'fixed', inset: 0, display: 'grid', placeItems: 'center', padding: 16, overflow: 'auto', fontFamily: 'Nunito Sans, system-ui, sans-serif' }}>
      {/* fundo suavizado: o lima puro em tela cheia cansa a vista */}
      <div aria-hidden="true" style={{ position: 'fixed', inset: 0, background: `url(${pattern}) center / cover no-repeat`, filter: 'saturate(.82) brightness(.97)' }} />
      <div aria-hidden="true" style={{ position: 'fixed', inset: 0, background: 'radial-gradient(ellipse at center, rgba(23,35,75,0) 55%, rgba(23,35,75,.16) 100%)' }} />
      <main className="g-panel" style={{ position: 'relative', width: 'min(440px,100%)', padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, justifyContent: 'center' }} aria-hidden="true">
          {LOOKS.map((l, k) => <Boneco key={k} look={l} anim={k === 1 ? 'wave' : 'idle'} size={70} />)}
        </div>
        <div style={{ textAlign: 'center' }}>
          <img src={logo} alt="Pivoo" width="168" style={{ display: 'block', margin: '0 auto' }} />
          <div style={{ fontSize: 14, fontWeight: 700, color: '#17234B', margin: '4px 0 10px' }}>Seu estúdio ganha vida.</div>
          <h1 className="fred" style={{ margin: '2px 0 0', fontSize: 26, fontWeight: 600 }}>{title}</h1>
        </div>
        {SIGNUP_OPEN && mode !== 'reset' && mode !== 'forgot' && (
          <div role="tablist" aria-label="Acesso" style={{ display: 'flex', gap: 6, justifyContent: 'center' }}>
            <button role="tab" className="g-chip" aria-selected={mode === 'login'} aria-pressed={mode === 'login'} onClick={() => { setMode('login'); setMsg(null); }}>Entrar</button>
            <button role="tab" className="g-chip" aria-selected={mode === 'signup'} aria-pressed={mode === 'signup'} onClick={() => { setMode('signup'); setMsg(null); }}>Criar conta</button>
          </div>
        )}
        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {mode === 'signup' && <Field id="a-name" label="Seu nome" value={f.name} onChange={set('name')} autoComplete="name" />}
          {mode !== 'reset' && <Field id="a-email" label="E-mail" type="email" value={f.email} onChange={set('email')} autoComplete="email" />}
          {mode !== 'forgot' && <Field id="a-pass" label={mode === 'reset' ? 'Nova senha' : 'Senha'} type="password" value={f.password} onChange={set('password')}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'} hint={mode === 'login' ? null : 'Pelo menos 10 caracteres.'} />}
          {msg && <div role={msg.ok ? 'status' : 'alert'} style={{ padding: '10px 12px', borderRadius: 12, fontSize: 13.5, border: '2px solid', background: msg.ok ? '#E3F5DC' : '#FFE1DC', borderColor: msg.ok ? '#2D7A3E' : '#9A2E22', color: msg.ok ? '#205C2E' : '#7A2218' }}>{msg.text}</div>}
          <button type="submit" className="g-btn g-lime" disabled={busy}>{busy ? 'Aguarde…' : cta}</button>
        </form>
        <div style={{ display: 'flex', justifyContent: 'center', gap: 14, flexWrap: 'wrap', fontSize: 13 }}>
          {mode === 'login' && <button className="g-btn g-quiet g-sm" onClick={() => { setMode('forgot'); setMsg(null); }}>Esqueci a senha</button>}
          {(mode === 'forgot' || mode === 'reset') && <button className="g-btn g-quiet g-sm" onClick={() => { setMode('login'); setMsg(null); }}>Voltar para entrar</button>}
        </div>
        {!SIGNUP_OPEN && mode === 'login' && <p className="g-muted" style={{ margin: 0, fontSize: 12, textAlign: 'center', lineHeight: 1.45 }}>Acesso por convite. Peça sua conta ao administrador.</p>}
        {mode === 'signup' && <p className="g-muted" style={{ margin: 0, fontSize: 12, textAlign: 'center', lineHeight: 1.45 }}>Contas novas começam no modo DEMO (sem custo, com imagens de exemplo). A produção com IA real é liberada com os planos de créditos.</p>}
        <button className="g-btn g-quiet g-sm" style={{ alignSelf: 'center' }} aria-expanded={about} onClick={() => setAbout(!about)}>Sobre e créditos</button>
        {about && <AboutContent />}
      </main>
    </div>
  );
}
