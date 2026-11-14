import React from 'react';
import { Check, Copy, CreditCard, Minus, Plus, QrCode, ShieldCheck } from 'lucide-react';
import { getJSON, post } from '../engine/api.js';
import { Spinner } from './bits.jsx';
import { brl, cardBlock, checkoutBody, clampCustom, customHint, customTotalCents, docValid, isFinal, maskDoc, statusOf, stepCustom, videosFor } from './buy.js';
import './buy.css';

// "Comprar créditos" (aba `buy` das Preferências; desktop e celular). Pacotes | Avulso, Pix (QR + copia e cola, com
// polling do NOSSO servidor) ou cartão na fatura hospedada do Asaas (nenhum dado de cartão passa pelo Kiroo).
// O preço exibido vem do catálogo do servidor; o pedido leva só o pacote ou a quantidade (`checkoutBody`).
const POLL_MS = 3000;

function returnId() {
  try { const id = new URLSearchParams(window.location.search).get('compra'); return /^kpay_[0-9a-f]{10}$/.test(id || '') ? id : null; }
  catch { return null; }
}

export function BuyCreditsContent({ v }) {
  const [cat, setCat] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [tab, setTab] = React.useState('pacotes');
  const [pkg, setPkg] = React.useState('pro');
  const [custom, setCustom] = React.useState(100);
  const [method, setMethod] = React.useState('pix');
  const [doc, setDoc] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [order, setOrder] = React.useState(null);     // {payment, pix?, redirect_url?}
  const [copied, setCopied] = React.useState(false);

  const load = React.useCallback(() => getJSON('/api/payments/catalog').then((c) => {
    setCat(c);
    const hl = (c.packages || []).find((p) => p.highlight);
    if (hl) setPkg((cur) => (c.packages.some((p) => p.code === cur) ? cur : hl.code));
  }).catch((e) => setErr(e.message)), []);
  React.useEffect(() => { load(); }, [load]);

  // voltou da fatura do cartão (?compra=kpay_...): acompanha aquela compra e limpa o endereço
  React.useEffect(() => {
    const id = returnId();
    if (!id) return;
    try { window.history.replaceState(null, '', window.location.pathname); } catch { /* ignore */ }
    getJSON('/api/payments/' + id).then((p) => setOrder({ payment: p })).catch(() => {});
  }, []);

  // polling do nosso servidor enquanto a compra está aberta (o servidor confere no Asaas)
  const pid = order && order.payment && order.payment.id;
  const pst = order && order.payment && order.payment.status;
  // trocar de tela (escolha → QR → confirmado) começa do topo: a rolagem do modal não fica no rodapé
  const rootRef = React.useRef(null);
  React.useEffect(() => {
    const body = rootRef.current && rootRef.current.closest('.pref-body');
    if (body) body.scrollTop = 0;
  }, [pid, pst]);
  React.useEffect(() => {
    if (!pid || isFinal(pst)) return undefined;
    const t = setInterval(() => {
      getJSON('/api/payments/' + pid).then((p) => setOrder((o) => (o && o.payment.id === p.id ? { ...o, payment: p } : o))).catch(() => {});
    }, POLL_MS);
    return () => clearInterval(t);
  }, [pid, pst]);

  if (err) return <div role="alert" className="buy-err">{err}</div>;
  if (!cat) return <div style={{ display: 'grid', placeItems: 'center', padding: 30 }}><Spinner /></div>;

  const c = cat.custom;
  const sel = tab === 'pacotes' ? cat.packages.find((p) => p.code === pkg) : null;
  const credits = sel ? sel.credits : custom;
  const amount = sel ? sel.price_cents : customTotalCents(custom, c);
  const cardWhy = cardBlock(amount, cat.card);
  const needDoc = cat.needs_document;
  const docOk = !needDoc || docValid(doc);
  const canPay = amount > 0 && docOk && !busy && !(method === 'card' && cardWhy);
  const hint = tab === 'avulso' ? customHint(custom, cat) : null;
  const wallet = v.wallet;

  const pay = async () => {
    setBusy(true); setErr(null);
    // cartão: abre a aba já no clique (senão o navegador bloqueia a janela aberta depois do await)
    const win = method === 'card' ? window.open('', '_blank') : null;
    try {
      const r = await post('/api/payments/checkout', checkoutBody({ tab, pkg, custom, method, doc: needDoc ? doc : '' }));
      setOrder(r);
      if (r.redirect_url) {
        if (win) { win.opener = null; win.location.href = r.redirect_url; } else window.location.assign(r.redirect_url);
      }
      if (needDoc) load();
    } catch (e) {
      if (win) win.close();
      setErr(e.message);
    } finally { setBusy(false); }
  };

  if (order) return <div ref={rootRef}><OrderView order={order} copied={copied} setCopied={setCopied} onBack={() => { setOrder(null); setCopied(false); load(); }} v={v} /></div>;

  return (
    <div className="buy" ref={rootRef}>
      <div className="buy-top">
        <div>
          <div className="buy-k">Seu saldo</div>
          <div className="buy-bal">{wallet ? (wallet.exempt ? 'Isento' : `${wallet.balance} créditos`) : '—'}</div>
        </div>
        <div className="buy-rate">1 vídeo = <strong>{cat.video_price_credits} créditos</strong></div>
      </div>
      {cat.negative_balance && <div role="alert" className="buy-warn">{cat.negative_balance}</div>}

      <div role="tablist" aria-label="Tipo de compra" className="buy-seg">
        {[['pacotes', 'Pacotes'], ['avulso', 'Avulso']].map(([id, label]) => (
          <button key={id} role="tab" type="button" aria-selected={tab === id} className="buy-seg-btn" onClick={() => setTab(id)}>{label}</button>
        ))}
      </div>

      {tab === 'pacotes' ? (
        <div role="radiogroup" aria-label="Pacotes de créditos" className="buy-packs">
          {cat.packages.map((p) => (
            <button key={p.code} type="button" role="radio" aria-checked={pkg === p.code} className={'buy-pack' + (p.highlight ? ' is-hl' : '')} onClick={() => setPkg(p.code)}>
              <span className="buy-pack-head">
                <span className="buy-pack-name">{p.name}</span>
                {p.highlight && <span className="buy-badge">Mais escolhido</span>}
              </span>
              <span className="buy-pack-cr"><strong>{p.credits.toLocaleString('pt-BR')}</strong> créditos</span>
              <span className="buy-pack-vid">rende até {p.videos} vídeos</span>
              <span className="buy-pack-foot">
                <span className="buy-price">{brl(p.price_cents)}</span>
                {p.savings_pct > 0 && <span className="buy-save">Economize {p.savings_pct}%</span>}
              </span>
              <span className="buy-radio" aria-hidden="true">{pkg === p.code && <Check size={14} />}</span>
            </button>
          ))}
        </div>
      ) : (
        <div className="buy-custom">
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
          <div className="buy-total">
            <span>{brl(c.unit_price_cents)} por crédito · rende até {videosFor(custom, cat.video_price_credits)} vídeos</span>
            <strong>{brl(amount)}</strong>
          </div>
          <p className="buy-note">Mínimo {c.min_credits}, de {c.step_credits} em {c.step_credits}, até {c.max_credits.toLocaleString('pt-BR')} créditos por compra.</p>
          {hint && <div className="buy-hint"><span>{hint}</span><button type="button" className="buy-link" onClick={() => { setTab('pacotes'); setPkg(c.hint_package); }}>Ver pacote</button></div>}
        </div>
      )}

      <section className="buy-pay" aria-label="Pagamento">
        <div className="buy-k">Como você quer pagar?</div>
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
            <span className="buy-k">CPF ou CNPJ de quem paga</span>
            <input value={doc} onChange={(e) => setDoc(maskDoc(e.target.value))} autoComplete="off" spellCheck={false}
              placeholder="000.000.000-00" aria-invalid={doc.length > 0 && !docValid(doc)} aria-describedby="buy-doc-why" />
            <small id="buy-doc-why">{doc.length > 0 && !docValid(doc) ? 'Confira os números: CPF ou CNPJ inválido.' : 'Pedido só na primeira compra (exigência do Asaas). Não guardamos o número.'}</small>
          </label>
        )}
      </section>

      {err && <div role="alert" className="buy-err">{err}</div>}
      <div className="buy-dock">
        <div className="buy-dock-sum"><span>{credits.toLocaleString('pt-BR')} créditos</span><strong>{brl(amount)}</strong></div>
        <button type="button" className="pw-btn pw-btn-primary buy-cta" disabled={!canPay} onClick={pay}>
          {busy ? 'Gerando cobrança…' : method === 'pix' ? `Pagar ${brl(amount)} com Pix` : `Pagar ${brl(amount)} no cartão`}
        </button>
      </div>
      <p className="buy-fine"><ShieldCheck size={14} aria-hidden="true" /> Pagamento processado pelo Asaas. O saldo entra assim que o pagamento é confirmado.</p>
    </div>
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
    <div className="buy">
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
            <button type="button" className="pw-btn pw-btn-primary" onClick={v.closeWin}>Voltar ao estúdio</button>
            <button type="button" className="pw-btn" onClick={() => v.openPrefs('credits')}>Ver extrato</button>
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
          <label className="buy-k" htmlFor="buy-pix-code">Pix copia e cola</label>
          <div className="buy-copy">
            <input id="buy-pix-code" readOnly value={pix.payload || ''} onFocus={(e) => e.target.select()} />
            <button type="button" className="pw-btn" onClick={copy}>{copied ? <><Check size={15} aria-hidden="true" /> Copiado</> : <><Copy size={15} aria-hidden="true" /> Copiar</>}</button>
          </div>
        </div>
      )}
      {!pix && p.status === 'pending' && p.method === 'card' && (
        <div className="buy-pix">
          <p className="buy-note">Conclua o pagamento na página segura do Asaas. Esta tela atualiza sozinha quando o cartão for aprovado.</p>
          {(order.redirect_url || p.invoice_url) && <a className="pw-btn buy-cta-link" href={order.redirect_url || p.invoice_url} target="_blank" rel="noopener noreferrer">Abrir a página de pagamento</a>}
        </div>
      )}
      {isFinal(p.status) && p.status !== 'paid' && <p className="buy-note">Nada foi creditado por esta cobrança. Você pode gerar outra.</p>}
      <button type="button" className="pw-btn" onClick={onBack}>{p.status === 'paid' ? 'Comprar mais' : 'Escolher outro pagamento'}</button>
    </div>
  );
}
