import React from 'react';
import { ArrowLeft, ArrowRight, Check, Eye, EyeOff, Loader2, MailCheck, CircleAlert, CircleCheck, KeyRound } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import Boneco from '../Boneco.jsx';
import { auth, authConfig } from '../engine/api.js';
import { ART } from '../landing/art.js';
import logo from '../assets/brand/wordmark-preto-laranja.svg';
import { AboutContent } from './About.jsx';
import { googleStart, GOOGLE_ERRORS } from './googleStart.js';
import './auth.css';

// Acesso ao Kiroo: entrar, criar conta, confirmar e-mail, esqueci a senha e nova senha (?reset=token).
// Mesma sessão de sempre (cookie HttpOnly do servidor Python); Google só aparece quando o servidor tem as credenciais.

// Quem decide se há cadastro é o servidor (STUDIO_SIGNUP: closed | invite | open), via GET /api/config.

const MIN_PASSWORD = 10;
const RESEND_S = 45;
const TEAM = [
  { id: 'nina', look: { shirt: '#FF8FC0', acc: 'bone' } },
  { id: 'theo', look: { shirt: '#FF5B2E', acc: 'fones' } },
  { id: 'iris', look: { shirt: '#FF9A3D', acc: 'oculos' } },
];
const COPY = {
  login: { title: 'Entrar no Kiroo', sub: 'Sua equipe está na sede, esperando o próximo produto.', cta: 'Entrar', busy: 'Entrando…' },
  signup: { title: 'Criar sua conta', sub: 'Monte seu estúdio em menos de um minuto. Começa em DEMO, sem custo.', cta: 'Criar conta', busy: 'Criando sua conta…' },
  forgot: { title: 'Esqueceu a senha?', sub: 'Informe o e-mail da conta. Enviamos um link para criar uma nova.', cta: 'Enviar link', busy: 'Enviando…' },
  sent: { title: 'Confira seu e-mail', sub: '' },
  reset: { title: 'Criar nova senha', sub: 'Escolha uma senha nova. Por segurança, as outras sessões serão encerradas.', cta: 'Salvar nova senha', busy: 'Salvando…' },
  verify: { title: 'Confirme seu e-mail', sub: '', cta: 'Confirmar', busy: 'Confirmando…' },
};

const sentence = (t) => (t ? t.charAt(0).toUpperCase() + t.slice(1) + (/[.!?…]$/.test(t) ? '' : '.') : '');

function Notice({ msg, id }) {
  if (!msg) return null;
  const Icon = msg.ok ? CircleCheck : CircleAlert;
  return (
    <div id={id} role={msg.ok ? 'status' : 'alert'} className="au-notice" data-tone={msg.ok ? 'ok' : 'error'}>
      <Icon aria-hidden="true" className="size-4 shrink-0" /><span>{msg.text}</span>
    </div>
  );
}

function Field({ id, label, aside, children, hint, hintId }) {
  return (
    <div className="au-field">
      <div className="flex items-baseline justify-between gap-3">
        <Label htmlFor={id} className="text-[13px] font-medium text-[var(--au-ink)]">{label}</Label>
        {aside}
      </div>
      {children}
      {hint && <div id={hintId} className="au-hint">{hint}</div>}
    </div>
  );
}

const inputCls = 'h-11 rounded-[12px] border-[var(--au-line-2)] bg-white px-3.5 text-[15px] md:text-[15px] shadow-[0_1px_0_rgba(14, 14, 16, .03)] placeholder:text-[#9AA0B4] focus-visible:border-[var(--au-ink)] focus-visible:ring-[3px] focus-visible:ring-[rgba(14, 14, 16, .12)]';

function PasswordInput({ id, value, onChange, autoComplete, invalid, describedBy, autoFocus }) {
  const [show, setShow] = React.useState(false);
  const [caps, setCaps] = React.useState(false);
  const onKey = (e) => setCaps(!!e.getModifierState?.('CapsLock'));
  return (
    <>
      <div className="relative">
        <Input id={id} type={show ? 'text' : 'password'} value={value} onChange={(e) => onChange(e.target.value)} onKeyUp={onKey} onKeyDown={onKey}
          autoComplete={autoComplete} required minLength={autoComplete === 'new-password' ? MIN_PASSWORD : undefined} maxLength={200}
          aria-invalid={invalid || undefined} aria-describedby={describedBy} autoFocus={autoFocus} className={inputCls + ' pr-12'} />
        <button type="button" className="au-eye" onClick={() => setShow(!show)} aria-label={show ? 'Ocultar senha' : 'Mostrar senha'} aria-pressed={show}>
          {show ? <EyeOff className="size-[18px]" /> : <Eye className="size-[18px]" />}
        </button>
      </div>
      {caps && <div className="au-hint text-[#8A4B00]" role="status">Caps Lock está ligado.</div>}
    </>
  );
}

function SubmitButton({ busy, children, busyLabel, disabled }) {
  return (
    <Button type="submit" disabled={busy || disabled} aria-busy={busy || undefined}
      className="au-primary h-11 w-full rounded-[12px] text-[15px] font-semibold">
      {busy ? <><Loader2 className="size-4 animate-spin" aria-hidden="true" />{busyLabel}</> : <>{children}<ArrowRight className="size-4 au-arrow" aria-hidden="true" /></>}
    </Button>
  );
}

function GoogleButton({ label, href, need }) {
  const [going, setGoing] = React.useState(false);
  return (
    <>
    <Button type="button" variant="outline" className="au-google h-11 w-full rounded-[12px] text-[15px] font-medium" aria-busy={going || undefined}
      disabled={!href || going} aria-describedby={need ? 'au-google-need' : undefined}
      onClick={() => { if (!href) return; setGoing(true); window.location.assign(href); }}>
        {going ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : (
          <svg viewBox="0 0 18 18" width="18" height="18" aria-hidden="true">
            <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z" />
            <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z" />
            <path fill="#FBBC05" d="M3.97 10.72A5.4 5.4 0 0 1 3.68 9c0-.6.1-1.18.29-1.72V4.95H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.05l3.01-2.33z" />
            <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z" />
          </svg>
        )}
        {going ? 'Abrindo o Google…' : label}
    </Button>
    {need && <p className="au-fine au-google-need" id="au-google-need">{need}</p>}
    </>
  );
}

// Código de 6 dígitos: um campo real (teclado numérico, autopreenchimento do SMS/e-mail) sob seis caixas visuais.
function CodeInput({ value, onChange, onComplete, invalid, describedBy }) {
  const ref = React.useRef(null);
  const [focused, setFocused] = React.useState(false);
  React.useEffect(() => { ref.current?.focus(); }, []);
  const set = (raw) => {
    const v = raw.replace(/\D/g, '').slice(0, 6);
    onChange(v);
    if (v.length === 6) onComplete?.(v);
  };
  return (
    <div className="au-code" data-invalid={invalid || undefined} onClick={() => ref.current?.focus()}>
      <input ref={ref} id="au-code" className="au-code-input" value={value} onChange={(e) => set(e.target.value)}
        onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
        inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]*" maxLength={6} aria-label="Código de 6 dígitos"
        aria-invalid={invalid || undefined} aria-describedby={describedBy} />
      {Array.from({ length: 6 }, (_, i) => (
        <span key={i} className="au-code-box" aria-hidden="true"
          data-filled={value[i] ? '' : undefined} data-active={focused && (i === Math.min(value.length, 5)) ? '' : undefined}>
          {value[i] || ''}
        </span>
      ))}
    </div>
  );
}

function Showcase() {
  const sede = ART.sede;
  return (
    <aside className="au-show" aria-hidden="true">
      <div className="au-show-frame">
        {sede ? <img src={sede} alt="" className="au-show-img" /> : (
          <div className="au-show-empty">
            {TEAM.map((t, k) => <Boneco key={t.id} look={t.look} anim={k === 1 ? 'wave' : 'idle'} size={96} />)}
          </div>
        )}
        <div className="au-show-shade" />
        <div className="au-show-card">
          <div className="au-show-faces">
            {['nina', 'theo', 'iris', 'lia', 'rui', 'beto'].map((id) => ART[id]
              ? <img key={id} src={ART[id]} alt="" />
              : null)}
          </div>
          <p className="au-show-title">Seu estúdio ganha vida.</p>
          <p className="au-show-text">Você traz o produto. A equipe de agentes planeja, gera, revisa e entrega o vídeo, e você aprova o que importa.</p>
        </div>
      </div>
    </aside>
  );
}

export default function AuthScreen({ onDone, resetToken, initialMode, onBack, signup = 'closed' }) {
  const params = React.useMemo(() => new URLSearchParams(window.location.search), []);
  const [cfg, setCfg] = React.useState({ signup, google: false, email: false });
  const [mode, setMode] = React.useState(resetToken ? 'reset' : initialMode === 'signup' && signup !== 'closed' ? 'signup' : 'login');
  const [f, setF] = React.useState({ name: '', email: '', password: '', code: '', invite: '', consent: false });
  const [msg, setMsg] = React.useState(() => (GOOGLE_ERRORS[params.get('erro')] ? { ok: false, text: GOOGLE_ERRORS[params.get('erro')] } : null));
  const [busy, setBusy] = React.useState(false);
  const [about, setAbout] = React.useState(false);
  const [sentInfo, setSentInfo] = React.useState(null);   // { sent: bool, text }
  const [cooldown, setCooldown] = React.useState(0);
  const headRef = React.useRef(null);
  const first = React.useRef(true);

  React.useEffect(() => {
    authConfig().then((c) => setCfg(c)).catch(() => {});
    if (params.has('erro')) window.history.replaceState(null, '', window.location.pathname);  // a mensagem já está na tela
  }, [params]);
  React.useEffect(() => { if (cfg.signup === 'closed' && mode === 'signup') setMode('login'); }, [cfg.signup, mode]);
  React.useEffect(() => { document.title = mode === 'signup' ? 'Kiroo — Criar conta' : 'Kiroo — Entrar'; }, [mode]);
  // a cada troca de etapa, o foco vai para o título (leitor de tela anuncia a etapa nova)
  React.useEffect(() => { if (first.current) { first.current = false; return; } headRef.current?.focus(); }, [mode]);
  React.useEffect(() => {
    if (cooldown <= 0) return undefined;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }));
  const go = (m) => { setMode(m); setMsg(null); setF((x) => ({ ...x, password: '', code: '' })); };
  const fail = (err) => setMsg({ ok: false, text: sentence(err.message) });
  const enter = () => { window.history.replaceState(null, '', '/'); onDone(); };

  const run = async (fn) => {
    if (busy) return;
    setBusy(true); setMsg(null);
    try { await fn(); } catch (err) { fail(err); } finally { setBusy(false); }
  };

  const submit = (e) => {
    e.preventDefault();
    run(async () => {
      if (mode === 'login') { await auth('login', { email: f.email, password: f.password }); enter(); }
      else if (mode === 'signup') {
        const r = await auth('signup', { name: f.name, email: f.email, password: f.password, invite: f.invite, consent: f.consent });
        setSentInfo({ sent: !!r.sent, text: r.message }); setCooldown(RESEND_S); go('verify');
      } else if (mode === 'forgot') {
        const r = await auth('forgot', { email: f.email });
        setSentInfo({ sent: !!r.sent, text: r.message }); go('sent');
      } else if (mode === 'reset') {
        await auth('reset', { token: resetToken, password: f.password });
        window.history.replaceState(null, '', '/');
        go('login'); setMsg({ ok: true, text: 'Senha alterada. Entre com a nova senha.' });
      } else if (mode === 'verify') { await verify(f.code); }
    });
  };
  const verify = async (code) => {
    try { await auth('verify', { code }); }
    catch (err) { setF((x) => ({ ...x, code: '' })); throw err; }  // campo limpo para digitar de novo
    setMsg({ ok: true, text: 'E-mail confirmado. Abrindo seu estúdio…' });
    setTimeout(enter, 650);
  };
  const resend = () => run(async () => {
    const r = await auth('resend');
    setSentInfo({ sent: !!r.sent, text: r.message }); setCooldown(RESEND_S);
    setMsg({ ok: !!r.sent, text: r.sent ? 'Enviamos um novo código.' : (r.message || 'Novo código gerado.') });
  });

  const copy = COPY[mode];
  const pwShort = mode !== 'login' && f.password.length > 0 && f.password.length < MIN_PASSWORD;
  const pwOk = f.password.length >= MIN_PASSWORD;
  const errInvalid = msg && !msg.ok;
  const showGoogle = cfg.google && (mode === 'login' || mode === 'signup');
  const gStart = googleStart({ mode, signup: cfg.signup, invite: f.invite, consent: f.consent });
  const showTabs = cfg.signup !== 'closed' && (mode === 'login' || mode === 'signup');

  let sub = copy.sub;
  if (mode === 'verify') sub = sentInfo?.sent
    ? <>Enviamos um código de 6 dígitos para <strong className="text-[var(--au-ink)]">{f.email}</strong>. Ele vale por 30 minutos.</>
    : sentInfo?.text ? <>{sentInfo.text}</>
    : <>O código de 6 dígitos para <strong className="text-[var(--au-ink)]">{f.email}</strong> foi gerado. O envio por e-mail ainda não está ativo neste estúdio: peça o código ao administrador ou confirme depois.</>;

  return (
    <div className="au">
      <div className="au-main">
        <header className="au-top">
          {onBack && mode !== 'reset' && mode !== 'verify'
            ? <button type="button" className="au-brand" onClick={onBack} aria-label="Kiroo: voltar para o início"><img src={logo} alt="" height="26" /></button>
            : <span className="au-brand"><img src={logo} alt="Kiroo" height="26" /></span>}
          {onBack && mode !== 'reset' && mode !== 'verify' && (
            <Button variant="ghost" className="h-10 rounded-[10px] px-3 text-[14px] text-[var(--au-ink-2)]" onClick={onBack}>
              <ArrowLeft aria-hidden="true" />Início
            </Button>
          )}
        </header>

        <main className="au-center" id="au-main">
          <div className="au-panel" key={mode}>
            {mode === 'verify' || mode === 'sent' ? (
              <div className="au-badge" aria-hidden="true"><MailCheck className="size-5" /></div>
            ) : mode === 'reset' || mode === 'forgot' ? (
              <div className="au-badge" aria-hidden="true"><KeyRound className="size-5" /></div>
            ) : (
              <div className="au-crew" aria-hidden="true">
                {TEAM.map((t, k) => <Boneco key={t.id} look={t.look} anim={k === 1 ? 'wave' : 'idle'} size={44} />)}
              </div>
            )}
            <h1 className="au-title" tabIndex={-1} ref={headRef}>{copy.title}</h1>
            {mode === 'sent'
              ? <p className="au-sub">{sentInfo?.sent
                ? <>Se houver uma conta com <strong className="text-[var(--au-ink)]">{f.email}</strong>, o link para criar uma nova senha já está a caminho. Ele vale por 30 minutos.</>
                : <>Se houver uma conta com <strong className="text-[var(--au-ink)]">{f.email}</strong>, o link foi gerado. O envio por e-mail ainda não está ativo neste estúdio: peça o link ao administrador.</>}</p>
              : sub && <p className="au-sub">{sub}</p>}

            {showTabs && (
              <div className="au-seg" role="group" aria-label="Tipo de acesso">
                <span className="au-seg-thumb" data-pos={mode === 'signup' ? 'r' : 'l'} aria-hidden="true" />
                <button type="button" aria-pressed={mode === 'login'} onClick={() => mode !== 'login' && go('login')}>Entrar</button>
                <button type="button" aria-pressed={mode === 'signup'} onClick={() => mode !== 'signup' && go('signup')}>Criar conta</button>
              </div>
            )}

            {showGoogle && mode === 'login' && (
              <>
                <GoogleButton label="Continuar com Google" href={gStart.href} />
                <div className="au-or"><span>ou com e-mail</span></div>
              </>
            )}

            {mode === 'sent' ? (
              <div className="au-form">
                <Button type="button" className="au-primary h-11 w-full rounded-[12px] text-[15px] font-semibold" onClick={() => go('login')}>
                  Voltar para entrar<ArrowRight className="size-4 au-arrow" aria-hidden="true" />
                </Button>
                <button type="button" className="au-link self-center" onClick={() => go('forgot')}>Usar outro e-mail</button>
              </div>
            ) : (
              <form className="au-form" onSubmit={submit} noValidate={mode === 'verify'} aria-describedby={msg ? 'au-msg' : undefined}>
                {mode === 'signup' && (
                  <Field id="au-name" label="Seu nome">
                    <Input id="au-name" value={f.name} onChange={(e) => set('name')(e.target.value)} autoComplete="name" maxLength={80}
                      placeholder="Como a equipe vai te chamar" className={inputCls} autoFocus />
                  </Field>
                )}
                {mode === 'signup' && cfg.signup === 'invite' && (
                  <Field id="au-invite" label="Código de convite">
                    <Input id="au-invite" value={f.invite} onChange={(e) => set('invite')(e.target.value)} autoComplete="off"
                      spellCheck={false} required className={inputCls} />
                  </Field>
                )}
                {(mode === 'login' || mode === 'signup' || mode === 'forgot') && (
                  <Field id="au-email" label="E-mail">
                    <Input id="au-email" type="email" value={f.email} onChange={(e) => set('email')(e.target.value)} autoComplete="email" required
                      inputMode="email" spellCheck={false} placeholder="voce@exemplo.com" className={inputCls}
                      aria-invalid={(errInvalid && mode !== 'signup') || undefined} autoFocus={mode !== 'signup'} />
                  </Field>
                )}
                {(mode === 'login' || mode === 'signup' || mode === 'reset') && (
                  <Field id="au-pass" label={mode === 'reset' ? 'Nova senha' : 'Senha'} hintId="au-pass-hint"
                    aside={mode === 'login' && <button type="button" className="au-link text-[13px]" onClick={() => go('forgot')}>Esqueceu a senha?</button>}
                    hint={mode !== 'login' && (
                      <span className="inline-flex items-center gap-1.5" data-ok={pwOk || undefined}>
                        {pwOk ? <Check className="size-3.5 text-[#1F7A3D]" aria-hidden="true" /> : <span className="au-dot" aria-hidden="true" />}
                        Pelo menos {MIN_PASSWORD} caracteres{pwShort ? ` (faltam ${MIN_PASSWORD - f.password.length})` : ''}
                      </span>
                    )}>
                    <PasswordInput id="au-pass" value={f.password} onChange={set('password')} autoFocus={mode === 'reset'}
                      autoComplete={mode === 'login' ? 'current-password' : 'new-password'} invalid={errInvalid && mode === 'login'}
                      describedBy={mode !== 'login' ? 'au-pass-hint' : undefined} />
                  </Field>
                )}
                {mode === 'signup' && (
                  <label className="au-consent" htmlFor="au-consent">
                    <input id="au-consent" type="checkbox" checked={f.consent} required
                      onChange={(e) => set('consent')(e.target.checked)} />
                    <span>Li e aceito os <a href="/termos" target="_blank" rel="noopener">Termos de Uso</a> e a{' '}
                      <a href="/privacidade" target="_blank" rel="noopener">Política de Privacidade</a>.</span>
                  </label>
                )}
                {mode === 'verify' && (
                  <CodeInput value={f.code} onChange={set('code')} invalid={errInvalid} describedBy={msg ? 'au-msg' : undefined}
                    onComplete={(c) => run(() => verify(c))} />
                )}

                <Notice msg={msg} id="au-msg" />

                {!(mode === 'verify' && msg?.ok) && (
                  <SubmitButton busy={busy} busyLabel={copy.busy}
                    disabled={(mode === 'verify' && f.code.length < 6) || ((mode === 'signup' || mode === 'reset') && !pwOk) || (mode === 'signup' && !f.consent)}>
                    {copy.cta}
                  </SubmitButton>
                )}

                {mode === 'verify' && !msg?.ok && (
                  <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
                    <button type="button" className="au-link" onClick={resend} disabled={cooldown > 0 || busy}>
                      {cooldown > 0 ? `Reenviar código em ${cooldown} s` : 'Reenviar código'}
                    </button>
                    <button type="button" className="au-link au-link-quiet" onClick={enter}>Confirmar depois</button>
                  </div>
                )}
                {(mode === 'forgot' || mode === 'reset') && (
                  <button type="button" className="au-link self-center" onClick={() => go('login')}><ArrowLeft className="size-3.5" aria-hidden="true" />Voltar para entrar</button>
                )}
              </form>
            )}

            {showGoogle && mode === 'signup' && (
              <>
                <div className="au-or"><span>ou</span></div>
                <GoogleButton label="Criar conta com Google" href={gStart.href} need={gStart.need} />
              </>
            )}

            {mode === 'login' && !cfg.signup && <p className="au-fine">Acesso por convite. Peça sua conta ao administrador do estúdio.</p>}
            {mode === 'signup' && <p className="au-fine">Contas novas começam no modo DEMO: sem custo, com imagens de exemplo. A produção com IA real é liberada com os planos de créditos.</p>}
          </div>
        </main>

        <footer className="au-foot">
          <button type="button" className="au-link au-link-quiet" aria-expanded={about} onClick={() => setAbout(!about)}>Sobre e créditos</button>
          {about && <div className="au-about"><AboutContent /></div>}
        </footer>
      </div>
      <Showcase />
    </div>
  );
}
