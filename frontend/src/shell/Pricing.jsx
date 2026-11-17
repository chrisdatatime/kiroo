import React from 'react';
import { Check, ChevronDown } from 'lucide-react';
import { getJSON, post } from '../engine/api.js';
import { usePhone } from '../hooks/use-phone.js';
import { Spinner } from '../ui/bits.jsx';
import { ANNUAL_TOGGLE, PRICING_COPY as C, PRICING_PATH, SUPPORT_EMAIL_FALLBACK } from '../config/appConfig.js';
import KirooAvatar from './KirooAvatar.jsx';
import { Spark } from './AccountMenu.jsx';
import {
  brl, creditsLine, faqFor, orderMessage, parseQty, phonePlans, planAction, returnState, shortDay, topupCheck, topupTotalCents,
} from './pricing.js';
import './pricing.css';

// Planos (/pricing, design `Precos` e `CelPrecos`). View `planos` do Shell. Os dados vêm de GET /api/payments/catalog
// (planos, avulso, assinatura atual); pagar abre o Checkout da Stripe, trocar de plano abre o Portal do cliente.
// Sem chave Mensal/Anual na v1 (`ANNUAL_TOGGLE`). As partes `*View` são puras (renderizadas nos testes).
const POLL_MS = 2000;
const POLL_MAX = 40;

function supportHref(cat) {
  const wa = cat && cat.plan && cat.plan.support && cat.plan.support.whatsapp;
  if (wa) return wa;
  if (cat && cat.contact && cat.contact.href) return cat.contact.href;
  return `mailto:${SUPPORT_EMAIL_FALLBACK}?subject=${encodeURIComponent('Planos do Kiroo')}`;
}

export function PlanCard({ p, cat, busy, onAction, phone }) {
  const act = planAction(p, cat.plan, cat.online);
  const sub = cat.plan && cat.plan.subscription;
  const id = `pr-plan-${p.code}`;
  const ending = act.kind === 'current' && sub && sub.cancel_at_period_end && sub.current_period_end;
  return (
    <article className={'pr-plan' + (p.highlight ? ' is-hl' : '')} aria-labelledby={id}>
      {p.highlight && <span className="pr-badge">Recomendado</span>}
      <header className="pr-plan-head">
        <h3 id={id}>{p.name}</h3>
        <p>{p.tagline}</p>
      </header>
      <div className="pr-plan-body">
        <div className="pr-price">
          <span className="pr-amt">{brl(p.price_cents)}</span>
          <span className="pr-per">cobrado<br />mensalmente</span>
        </div>
        {!phone && (
          <div className="pr-note">
            {ending ? `Termina em ${shortDay(sub.current_period_end)}` : p.contact_note
              ? <span className="pr-note-c">ou <a href={supportHref(cat)} target="_blank" rel="noopener noreferrer">fale com a gente</a></span>
              : p.note}
          </div>
        )}
        <div className="pr-cred"><Spark size={14} /><span><b>{creditsLine(p)}</b> por mês</span></div>
        <button type="button" className={'pr-btn' + (p.highlight && act.kind !== 'current' ? ' is-accent' : '') + (act.kind === 'current' ? ' is-current' : '')}
          disabled={act.disabled || !!busy} aria-busy={busy === `plan:${p.code}` || undefined}
          onClick={() => onAction(act.kind, p)}>
          {busy === `plan:${p.code}` ? 'Abrindo…' : act.label}
        </button>
        {!phone && <div className="pr-gap" />}
        {p.features_lead && !phone && <div className="pr-lead">{p.features_lead}</div>}
        <ul className="pr-feats">
          {p.features.map((f) => <li key={f.text}><Check size={14} strokeWidth={2.4} aria-hidden="true" /><span>{f.text}</span></li>)}
        </ul>
      </div>
    </article>
  );
}

export function TopupBox({ cat, raw, setRaw, busy, onBuy }) {
  const t = cat.topup;
  const n = parseQty(raw);
  const chk = topupCheck(n, t);
  const total = topupTotalCents(n, t);
  const showErr = raw !== '' && !chk.ok;
  return (
    <section className="pr-topup" aria-labelledby="pr-topup-t">
      <div className="pr-topup-head">
        <h3 id="pr-topup-t">{C.topupTitle}</h3>
        <span>{C.topupLead}</span>
      </div>
      <div className="pr-topup-body">
        <div className="pr-chips" role="group" aria-label="Quantidades rápidas">
          {(t.shortcuts || []).map((q) => (
            <button key={q} type="button" className="pr-chip" aria-pressed={n === q} onClick={() => setRaw(String(q))}>
              <Spark size={13} />{q.toLocaleString('pt-BR')} créditos
            </button>
          ))}
        </div>
        <label className="pr-qty">
          <span className="pr-qty-l">Outra quantidade</span>
          <input type="text" inputMode="numeric" autoComplete="off" value={raw} maxLength={6}
            onChange={(e) => setRaw(e.target.value.replace(/[^\d]/g, ''))}
            aria-invalid={showErr || undefined} aria-describedby="pr-qty-help" />
        </label>
        <p id="pr-qty-help" className={'pr-qty-help' + (showErr ? ' is-err' : '')} aria-live="polite">
          {showErr ? chk.error : `De ${t.min_credits} a ${t.max_credits.toLocaleString('pt-BR')} créditos, ${brl(t.unit_price_cents)} por crédito.`}
        </p>
        <div className="pr-pay">
          <span className="pr-pay-t">Você paga <b>{brl(total)}</b></span>
          <button type="button" className="pr-btn pr-btn-auto" disabled={!chk.ok || !cat.online || !!busy} onClick={() => onBuy(n)}
            aria-busy={busy === 'topup' || undefined}>
            {busy === 'topup' ? 'Abrindo…' : chk.ok ? `Comprar ${n.toLocaleString('pt-BR')} créditos` : 'Comprar créditos'}
          </button>
        </div>
      </div>
    </section>
  );
}

export function Faq({ phone }) {
  const items = faqFor(phone);
  if (phone) {
    return (
      <div className="pr-faq-list">
        {items.map((f) => (
          <details key={f.q} className="pr-det">
            <summary>{f.q}<ChevronDown size={18} aria-hidden="true" /></summary>
            {f.a.map((t) => <p key={t}>{t}</p>)}
          </details>
        ))}
      </div>
    );
  }
  const cols = [[], [], []];
  items.forEach((f, i) => cols[i % 3].push(f));
  return (
    <div className="pr-faq-grid">
      {cols.map((col, i) => (
        <div key={i} className="pr-faq-col">
          {col.map((f) => (
            <div key={f.q}><h4>{f.q}</h4>{f.a.map((t) => <p key={t}>{t}</p>)}</div>
          ))}
        </div>
      ))}
    </div>
  );
}

export function PricingView({ cat, user, phone, notice, err, busy, raw, setRaw, onPlan, onTopup, onStatement }) {
  const plans = phone ? phonePlans(cat.plans) : cat.plans;
  return (
    <div className="pr" data-phone={phone || undefined}>
      <section className="pr-card">
        <div className="pr-top">
          <div>
            <h2 className="pr-h1">{C.title}</h2>
            {ANNUAL_TOGGLE && cat.annual_enabled && <div className="pr-annual">Pagar mensalmente · anualmente</div>}
          </div>
          {!phone && (
            <nav className="pr-seg" aria-label="Planos e extrato">
              <button type="button" aria-current="page">Planos</button>
              <button type="button" onClick={onStatement}>Extrato</button>
            </nav>
          )}
        </div>
        {notice && <div role="status" className={'pr-notice is-' + notice.tone}>{notice.tone === 'wait' && <Spinner size={16} />}{notice.text}</div>}
        {err && <div role="alert" className="pr-notice is-bad">{err}</div>}
        {!cat.online && <div role="note" className="pr-notice is-off">{C.offline}</div>}
        <div className="pr-welcome">
          <span className="pr-welcome-av" aria-hidden="true"><KirooAvatar user={user || {}} size={phone ? 32 : 40} /></span>
          <div>
            <div className="pr-welcome-t">{C.welcomeTitle}</div>
            <div className="pr-welcome-s">{phone ? C.welcomeTextPhone(cat.welcome_credits) : C.welcomeText(cat.welcome_credits)}</div>
          </div>
        </div>
        <div className="pr-grid">
          {plans.map((p) => <PlanCard key={p.code} p={p} cat={cat} busy={busy} onAction={onPlan} phone={phone} />)}
        </div>
        {cat.topup && <TopupBox cat={cat} raw={raw} setRaw={setRaw} busy={busy} onBuy={onTopup} />}
        <p className="pr-foot">{C.footnote}</p>
        <section className="pr-faq" aria-labelledby="pr-faq-t">
          <h3 id="pr-faq-t" className="pr-h2">Tem perguntas?</h3>
          <Faq phone={phone} />
        </section>
        <div className="pr-support"><a className="pr-btn pr-btn-soft" href={supportHref(cat)} target="_blank" rel="noopener noreferrer">Contatar suporte</a></div>
      </section>
    </div>
  );
}

export default function Pricing({ v }) {
  const phone = usePhone();
  const [cat, setCat] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [busy, setBusy] = React.useState(null);
  const [raw, setRaw] = React.useState('100');
  const [notice, setNotice] = React.useState(null);

  const load = React.useCallback(() => getJSON('/api/payments/catalog').then(setCat).catch((e) => setErr(e.message)), []);
  React.useEffect(() => { load(); }, [load]);

  // volta do checkout (?compra=kpay_... / ?cancelado=1) ou do Portal (?plano=1): acompanha e limpa o endereço
  React.useEffect(() => {
    const r = returnState(window.location.search);
    if (r.order || r.canceled || r.portal) { try { window.history.replaceState(null, '', PRICING_PATH); } catch { /* sem history */ } }
    if (r.canceled) { setNotice({ tone: 'off', text: 'Pagamento cancelado. Nada foi cobrado.' }); return undefined; }
    if (!r.order) return undefined;
    let n = 0;
    let alive = true;
    setNotice(orderMessage(null));
    const tick = () => getJSON('/api/payments/' + r.order).then((p) => {
      if (!alive) return;
      const m = orderMessage(p);
      setNotice(m);
      if (m.tone !== 'wait' || ++n >= POLL_MAX) {
        load();
        if (v.refreshAccount) v.refreshAccount().catch(() => {});
        return;
      }
      setTimeout(tick, POLL_MS);
    }).catch(() => { if (alive) setNotice(null); });
    tick();
    return () => { alive = false; };
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const go = async (key, path, body) => {
    setBusy(key); setErr(null);
    try {
      const r = await post(path, body);
      if (r.redirect_url) window.location.assign(r.redirect_url);
      else setBusy(null);
    } catch (e) { setErr(e.message); setBusy(null); }
  };
  const onPlan = (kind, p) => {
    if (kind === 'subscribe') go(`plan:${p.code}`, '/api/payments/checkout', { kind: 'plan', plan: p.code });
    else if (kind === 'change') go(`plan:${p.code}`, '/api/payments/portal', { plan: p.code });
  };
  const onTopup = (n) => go('topup', '/api/payments/checkout', { kind: 'topup', credits: n });

  return (
    <div className="pv-scroll pr-scroll">
      {!cat ? (err ? <div role="alert" className="pr-notice is-bad">{err}</div> : <div className="pr-load" aria-busy="true"><Spinner /></div>) : (
        <PricingView cat={cat} user={v.account && v.account.user} phone={phone} notice={notice} err={err} busy={busy}
          raw={raw} setRaw={setRaw} onPlan={onPlan} onTopup={onTopup} onStatement={() => v.openSettings('creditos')} />
      )}
    </div>
  );
}
