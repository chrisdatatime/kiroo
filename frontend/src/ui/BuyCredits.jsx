import React from 'react';
import { Check, Copy, CreditCard, Lock, Minus, Plus, QrCode, ShieldCheck, X } from 'lucide-react';
import { getJSON, post } from '../engine/api.js';
import { usePhone } from '../hooks/use-phone.js';
import { Spinner } from './bits.jsx';
import {
  barSummary, brl, buyLabel, cardBlock, checkoutBody, clampCustom, customHint, customTotalCents, defaultSelection, docValid,
  isFinal, maskDoc, moveSelection, phoneOrder, planCards, statusOf, stepCustom,
} from './buy.js';
import './buy.css';
import './buyv2.css';

// "Comprar créditos" v2 (modal próprio, aberto pelas Preferências; desktop e celular).
//   1. Planos: Free (só conta sem compra paga) + Inicial | Pro | Escala. Os pagos são rádios de verdade (setas, Enter,
//      Espaço); o selecionado sobe e ganha borda e sombra (só transform/sombra/cor animam: o layout não pula).
//   2. Pagamento: Pix (QR + copia e cola, polling do NOSSO servidor) ou cartão na fatura hospedada do Asaas.
//   "Comprar avulso" (rodapé) abre a quantidade livre e segue para o mesmo pagamento.
// O preço exibido vem do catálogo do servidor; o pedido leva só o pacote ou a quantidade (`checkoutBody`).
const POLL_MS = 3000;

function returnId() {
  try { const id = new URLSearchParams(window.location.search).get('compra'); return /^kpay_[0-9a-f]{10}$/.test(id || '') ? id : null; }
  catch { return null; }
}

const XIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#8A877F" strokeWidth="2" strokeLinecap="round" aria-hidden="true" className="bv-ic"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" /></svg>
);
const CheckIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#166534" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="bv-ic"><path d="M3 8.5l3 3 7-7" /></svg>
);

export function BuyCreditsContent({ v, Title = 'h1' }) {
  const phone = usePhone();
  const [cat, setCat] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [step, setStep] = React.useState('plans');      // plans | avulso | pay
  const [pkg, setPkg] = React.useState('pro');
  const [kind, setKind] = React.useState('pacotes');    // o que vai para o pagamento: pacotes | avulso
  const [custom, setCustom] = React.useState(100);
  const [method, setMethod] = React.useState('pix');
  const [doc, setDoc] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [order, setOrder] = React.useState(null);     // {payment, pix?, redirect_url?}
  const [copied, setCopied] = React.useState(false);

  const load = React.useCallback(() => getJSON('/api/payments/catalog').then((c) => {
    setCat(c);
    setPkg((cur) => ((c.packages || []).some((p) => p.code === cur) ? cur : defaultSelection(c)));
  }).catch((e) => setErr(e.message)), []);
  React.useEffect(() => { load(); }, [load]);

  // voltou da fatura do cartão (?compra=kpay_...): acompanha aquela compra e limpa o endereço
  React.useEffect(() => {
    const id = returnId();
    if (!id) return;
    try { window.history.replaceState(null, '', window.location.pathname); } catch { /* ignore */ }
    getJSON('/api/payments/' + id).then((p) => setOrder({ payment: p })).catch(() => {});
  }, []);

  const pid = order && order.payment && order.payment.id;
  const pst = order && order.payment && order.payment.status;
  const rootRef = React.useRef(null);
  React.useEffect(() => {   // trocar de etapa começa do topo
    const body = rootRef.current && rootRef.current.closest('.bvd-body');
    if (body) body.scrollTop = 0;
  }, [pid, pst, step]);
  React.useEffect(() => {
    if (!pid || isFinal(pst)) return undefined;
    const t = setInterval(() => {
      getJSON('/api/payments/' + pid).then((p) => setOrder((o) => (o && o.payment.id === p.id ? { ...o, payment: p } : o))).catch(() => {});
    }, POLL_MS);
    return () => clearInterval(t);
  }, [pid, pst]);

  const wallet = v.wallet;
  const head = (
    <header className="bv-head">
      <Title className="bv-h1">Comprar créditos</Title>
      <div className="bv-head-r">
        {wallet && <span className="bv-bal">Saldo <strong>{wallet.exempt ? 'isento' : `${wallet.balance} créditos`}</strong></span>}
        <button type="button" className="bv-close" onClick={v.closeWin} aria-label="Fechar"><X size={16} strokeWidth={1.8} aria-hidden="true" /></button>
      </div>
    </header>
  );

  if (!cat) return <div className="bv" ref={rootRef}>{head}{err ? <div role="alert" className="buy-err">{err}</div> : <div className="bv-load"><Spinner /></div>}</div>;

  if (order) {
    return <div className="bv" ref={rootRef}>{head}<OrderView order={order} copied={copied} setCopied={setCopied} onBack={() => { setOrder(null); setCopied(false); setStep('plans'); load(); }} v={v} /></div>;
  }

  const sel = kind === 'pacotes' ? cat.packages.find((p) => p.code === pkg) : null;
  const goPay = (k) => { setKind(k); setErr(null); setStep('pay'); };

  return (
    <div className="bv" ref={rootRef}>
      {head}
      {cat.negative_balance && <div role="alert" className="buy-warn">{cat.negative_balance}</div>}
      {step === 'plans' && <Plans cat={cat} pkg={pkg} setPkg={setPkg} phone={phone} onBuy={() => goPay('pacotes')} onAvulso={() => setStep('avulso')} />}
      {step === 'avulso' && <Avulso cat={cat} custom={custom} setCustom={setCustom} onBack={() => setStep('plans')} onNext={() => goPay('avulso')}
        onPack={(code) => { setPkg(code); setStep('plans'); }} />}
      {step === 'pay' && (
        <Pay cat={cat} sel={sel} custom={custom} kind={kind} method={method} setMethod={setMethod} doc={doc} setDoc={setDoc}
          busy={busy} err={err} onBack={() => { setErr(null); setStep(kind === 'avulso' ? 'avulso' : 'plans'); }}
          onPay={async () => {
            setBusy(true); setErr(null);
            // cartão: abre a aba já no clique (senão o navegador bloqueia a janela aberta depois do await)
            const win = method === 'card' ? window.open('', '_blank') : null;
            try {
              const r = await post('/api/payments/checkout', checkoutBody({ tab: kind, pkg, custom, method, doc: cat.needs_document ? doc : '' }));
              setOrder(r);
              if (r.redirect_url) {
                if (win) { win.opener = null; win.location.href = r.redirect_url; } else window.location.assign(r.redirect_url);
              }
              if (cat.needs_document) load();
            } catch (e) {
              if (win) win.close();
              setErr(e.message);
            } finally { setBusy(false); }
          }} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------- 1. planos
export function Plans({ cat, pkg, setPkg, phone, onBuy, onAvulso }) {
  const { cards } = planCards(cat);
  const shown = phone ? phoneOrder(cards) : cards;
  const codes = cat.packages.map((p) => p.code);
  const selCard = cards.find((c) => c.code === pkg);
  const refs = React.useRef({});
  const [kb, setKb] = React.useState(false);   // anel de foco só quando a navegação é pelo teclado (Tab/setas)
  const onKey = (e, code) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setPkg(code); return; }
    const next = moveSelection(codes, code, e.key);
    if (next !== code) { e.preventDefault(); setPkg(next); const el = refs.current[next]; if (el) el.focus(); }
  };
  return (
    <>
      <div role="radiogroup" aria-label="Pacotes de créditos" className="bv-grid" data-n={cards.length} data-kb={kb ? '' : undefined}
        onKeyUp={() => setKb(true)} onPointerDown={() => setKb(false)}>
        {shown.map((c) => (c.kind === 'free'
          ? <FreeCard key="free" c={c} compact={phone} />
          : <PackCard key={c.code} c={c} selected={pkg === c.code} compact={phone && pkg !== c.code}
              onSelect={() => setPkg(c.code)} onKey={(e) => onKey(e, c.code)} onBuy={onBuy} refFn={(el) => { refs.current[c.code] = el; }} />))}
      </div>
      <footer className="bv-foot">
        <span>Precisa de outra quantidade? <button type="button" className="bv-link" onClick={onAvulso}>Comprar avulso</button></span>
        <span className="bv-secure"><Lock size={12} strokeWidth={1.6} aria-hidden="true" />Pix ou cartão · pagamento seguro via Asaas</span>
      </footer>
      {phone && selCard && (
        <div className="bv-bar">
          <span className="bv-bar-sum">{barSummary(selCard)}</span>
          <button type="button" className="bv-btn is-sel bv-bar-btn" onClick={onBuy}>Comprar</button>
        </div>
      )}
    </>
  );
}

function PackCard({ c, selected, compact, onSelect, onKey, onBuy, refFn }) {
  const id = 'bv-' + c.code;
  return (
    <div className={'bv-card' + (selected ? ' is-sel' : '') + (compact ? ' is-compact' : '')} onClick={onSelect}>
      {c.badge && <span className="bv-badge">{c.badge}</span>}
      <div className="bv-card-in">
        <input ref={refFn} type="radio" className="bv-radio" name="bv-pack" id={id} checked={selected} tabIndex={selected ? 0 : -1}
          onChange={onSelect} onKeyDown={onKey} aria-describedby={id + '-price'} />
        <label htmlFor={id} className="bv-label">
          <span className="bv-row">
            <span className="bv-name">{c.name}</span>
            {c.current && <span className="bv-tag">Seu plano atual</span>}
          </span>
          <span className="bv-num"><strong>{c.credits.toLocaleString('pt-BR')}</strong><span>créditos</span></span>
          {c.savings_pct > 0 && <span className="bv-save">Economize {c.savings_pct}%</span>}
        </label>
        <div className="bv-more" aria-hidden={compact || undefined}>
          <div className="bv-more-in">
            <ul className="bv-feats">
              {c.features.map((f) => <li key={f.text} className={f.strong ? 'is-strong' : undefined}><CheckIcon />{f.text}</li>)}
            </ul>
          </div>
        </div>
        <div className="bv-grow" />
        <div className="bv-price" id={id + '-price'}>
          <strong>{brl(c.price_cents)}</strong>
          <span>{brl(c.per_credit_cents)} por crédito</span>
        </div>
        <button type="button" className={'bv-btn' + (selected ? ' is-sel' : '')} tabIndex={selected ? 0 : -1}
          onClick={(e) => { e.stopPropagation(); onSelect(); onBuy(); }}>{buyLabel(c, selected)}</button>
      </div>
    </div>
  );
}

function FreeCard({ c, compact }) {
  return (
    <div className={'bv-card is-free' + (compact ? ' is-compact' : '')} aria-label={`${c.name}: seu plano atual, ${c.credits} créditos de boas-vindas`}>
      <div className="bv-card-in">
        <span className="bv-row"><span className="bv-name">{c.name}</span><span className="bv-tag">Seu plano atual</span></span>
        <span className="bv-num"><strong>{c.credits}</strong><span>créditos</span></span>
        <span className="bv-tagline">{c.tagline}</span>
        <div className="bv-more">
          <div className="bv-more-in">
            <ul className="bv-feats is-off">{c.missing.map((t) => <li key={t}><XIcon />{t}</li>)}</ul>
          </div>
        </div>
        <div className="bv-grow" />
        <div className="bv-price"><strong>R$ 0</strong><span>{c.price_note}</span></div>
        <button type="button" className="bv-btn is-off" disabled>Seu plano atual</button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- avulso
function Avulso({ cat, custom, setCustom, onBack, onNext, onPack }) {
  const c = cat.custom;
  const hint = customHint(custom, cat);
  const amount = customTotalCents(custom, c);
  return (
    <section className="bv-panel" aria-label="Créditos avulsos">
      <h2 className="bv-h2">Quantos créditos?</h2>
      <div className="buy-stepper" role="group" aria-label="Quantidade de créditos">
        <button type="button" className="buy-step" aria-label={`Menos ${c.step_credits} créditos`} disabled={custom <= c.min_credits} onClick={() => setCustom((n) => stepCustom(n, -1, c))}><Minus size={18} /></button>
        <output className="buy-qty" aria-live="polite"><strong>{custom.toLocaleString('pt-BR')}</strong><span>créditos</span></output>
        <button type="button" className="buy-step" aria-label={`Mais ${c.step_credits} créditos`} disabled={custom >= c.max_credits} onClick={() => setCustom((n) => stepCustom(n, 1, c))}><Plus size={18} /></button>
      </div>
      <div className="buy-chips" role="group" aria-label="Atalhos">
        {(c.shortcuts || []).map((n) => (
          <button key={n} type="button" className="buy-chip" aria-pressed={custom === n} onClick={() => setCustom(clampCustom(n, c))}>{n}</button>
        ))}
      </div>
      <div className="buy-total"><span>{brl(c.unit_price_cents)} por crédito</span><strong>{brl(amount)}</strong></div>
      <p className="buy-note">Mínimo {c.min_credits}, de {c.step_credits} em {c.step_credits}, até {c.max_credits.toLocaleString('pt-BR')} créditos por compra.</p>
      {hint && <div className="buy-hint"><span>{hint}</span><button type="button" className="buy-link" onClick={() => onPack(c.hint_package)}>Ver pacote</button></div>}
      <div className="bv-actions">
        <button type="button" className="bv-btn" onClick={onBack}>Voltar aos pacotes</button>
        <button type="button" className="bv-btn is-sel" disabled={amount <= 0} onClick={onNext}>Continuar · {brl(amount)}</button>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- 2. pagamento
function Pay({ cat, sel, custom, kind, method, setMethod, doc, setDoc, busy, err, onBack, onPay }) {
  const credits = sel ? sel.credits : custom;
  const amount = sel ? sel.price_cents : customTotalCents(custom, cat.custom);
  const cardWhy = cardBlock(amount, cat.card);
  const needDoc = cat.needs_document;
  const canPay = amount > 0 && (!needDoc || docValid(doc)) && !busy && !(method === 'card' && cardWhy);
  return (
    <section className="bv-panel" aria-label="Pagamento">
      <div className="bv-sum">
        <span>{sel ? `Pacote ${sel.name}` : 'Créditos avulsos'}<strong>{credits.toLocaleString('pt-BR')} créditos</strong></span>
        <strong className="bv-sum-price">{brl(amount)}</strong>
      </div>
      <h2 className="bv-h2">Como você quer pagar?</h2>
      <div role="radiogroup" aria-label="Forma de pagamento" className="buy-methods">
        <button type="button" role="radio" aria-checked={method === 'pix'} className="buy-method" onClick={() => setMethod('pix')}>
          <QrCode size={18} aria-hidden="true" /><span><strong>Pix</strong><small>Confirma na hora</small></span>
        </button>
        <button type="button" role="radio" aria-checked={method === 'card'} className="buy-method" onClick={() => setMethod('card')}>
          <CreditCard size={18} aria-hidden="true" /><span><strong>Cartão</strong><small>Página segura do Asaas</small></span>
        </button>
      </div>
      {method === 'card' && cardWhy && <p role="alert" className="buy-warn">{cardWhy}</p>}
      {needDoc && (
        <label className="buy-doc">
          <span className="bv-k">CPF ou CNPJ de quem paga</span>
          <input value={doc} onChange={(e) => setDoc(maskDoc(e.target.value))} autoComplete="off" spellCheck={false}
            placeholder="000.000.000-00" aria-invalid={doc.length > 0 && !docValid(doc)} aria-describedby="buy-doc-why" />
          <small id="buy-doc-why">{doc.length > 0 && !docValid(doc) ? 'Confira os números: CPF ou CNPJ inválido.' : 'Pedido só na primeira compra (exigência do Asaas). Não guardamos o número.'}</small>
        </label>
      )}
      {err && <div role="alert" className="buy-err">{err}</div>}
      <div className="bv-actions">
        <button type="button" className="bv-btn" onClick={onBack} disabled={busy}>{kind === 'avulso' ? 'Voltar' : 'Trocar pacote'}</button>
        <button type="button" className="bv-btn is-sel" disabled={!canPay} onClick={onPay}>
          {busy ? 'Gerando cobrança…' : method === 'pix' ? `Pagar ${brl(amount)} com Pix` : `Pagar ${brl(amount)} no cartão`}
        </button>
      </div>
      <p className="buy-fine"><ShieldCheck size={14} aria-hidden="true" /> Pagamento processado pelo Asaas. O saldo entra assim que o pagamento é confirmado.</p>
    </section>
  );
}

function OrderView({ order, copied, setCopied, onBack, v }) {
  const p = order.payment;
  const st = statusOf(p.status);
  const pix = order.pix;
  const copy = async () => {
    try { await navigator.clipboard.writeText(pix.payload); setCopied(true); setTimeout(() => setCopied(false), 2500); }
    catch { setCopied(false); }
  };
  return (
    <section className="bv-panel">
      <div className={'buy-status is-' + st.tone} role="status" aria-live="polite">
        {st.tone === 'wait' ? <Spinner size={18} /> : st.tone === 'ok' ? <Check size={18} aria-hidden="true" /> : null}
        <span>{st.label}</span>
      </div>
      <div className="buy-order-sum"><span>{p.credits.toLocaleString('pt-BR')} créditos</span><strong>{p.amount}</strong></div>
      {p.status === 'paid' && (
        <div className="buy-done">
          <strong>{p.credits.toLocaleString('pt-BR')} créditos adicionados.</strong>
          {p.balance && <span>Saldo agora: {p.balance} créditos.</span>}
          <div className="buy-row">
            <button type="button" className="bv-btn is-sel" onClick={v.closeWin}>Voltar ao estúdio</button>
            <button type="button" className="bv-btn" onClick={() => v.openPrefs('credits')}>Ver extrato</button>
          </div>
        </div>
      )}
      {pix && p.status === 'pending' && (
        <div className="buy-pix">
          {pix.image && <img className="buy-qr" src={'data:image/png;base64,' + pix.image} alt="QR Code do Pix" width="220" height="220" />}
          <ol className="buy-steps">
            <li>Abra o app do seu banco e escolha pagar com Pix.</li>
            <li>Leia o QR Code ou use o código copia e cola.</li>
            <li>Esta tela atualiza sozinha quando o pagamento for confirmado.</li>
          </ol>
          <label className="bv-k" htmlFor="buy-pix-code">Pix copia e cola</label>
          <div className="buy-copy">
            <input id="buy-pix-code" readOnly value={pix.payload || ''} onFocus={(e) => e.target.select()} />
            <button type="button" className="bv-btn" onClick={copy}>{copied ? <><Check size={15} aria-hidden="true" /> Copiado</> : <><Copy size={15} aria-hidden="true" /> Copiar</>}</button>
          </div>
        </div>
      )}
      {!pix && p.status === 'pending' && p.method === 'card' && (
        <div className="buy-pix">
          <p className="buy-note">Conclua o pagamento na página segura do Asaas. Esta tela atualiza sozinha quando o cartão for aprovado.</p>
          {(order.redirect_url || p.invoice_url) && <a className="bv-btn buy-cta-link" href={order.redirect_url || p.invoice_url} target="_blank" rel="noopener noreferrer">Abrir a página de pagamento</a>}
        </div>
      )}
      {isFinal(p.status) && p.status !== 'paid' && <p className="buy-note">Nada foi creditado por esta cobrança. Você pode gerar outra.</p>}
      <button type="button" className="bv-btn bv-self" onClick={onBack}>{p.status === 'paid' ? 'Comprar mais' : 'Escolher outro pagamento'}</button>
    </section>
  );
}
