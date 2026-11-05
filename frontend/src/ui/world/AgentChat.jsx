import React from 'react';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { getJSON, post } from '../../engine/api.js';
import { StatusChip } from './InfoCard.jsx';

// Conversa com um agente (Fase 6, mundo Phaser). Reaproveita o "Conversar" roteirizado: a fala de dialogFor() abre a conversa;
// as perguntas vão para POST /api/chat (cotas, atalhos sem LLM e modelo pequeno ficam todos no servidor).
// O agente só fala: as ações reais ficam nos botões do topo. Estado do chat fica aqui, fora do loop do jogo;
// o App re-renderiza a cada tick, por isso o memo compara só os campos primitivos.
const logs = new Map(); // agente → mensagens desta sessão do navegador (só tela; o servidor guarda as 4 últimas trocas)
let seq = 0;
const msg = (who, text, extra) => ({ id: ++seq, who, text, ...extra });

function AgentChat(p) {
  const latest = React.useRef(p); latest.current = p;
  const input = React.useRef(null), list = React.useRef(null);
  const [items, setItems] = React.useState(() => logs.get(p.agentId) || [msg('agent', p.intro)]);
  const [text, setText] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [quota, setQuota] = React.useState(null);
  const [now, setNow] = React.useState(() => Date.now());
  const [waitUntil, setWaitUntil] = React.useState(0);

  React.useEffect(() => { logs.set(p.agentId, items); }, [p.agentId, items]);
  React.useEffect(() => { let on = true; getJSON('/api/chat/quota').then((q) => on && setQuota(q)).catch(() => {}); return () => { on = false; }; }, []);
  React.useEffect(() => { const el = list.current; if (el) el.scrollTop = el.scrollHeight; }, [items, busy]);
  // contagem do cooldown: só um timer enquanto há espera
  React.useEffect(() => {
    if (waitUntil <= Date.now()) return undefined;
    const id = setInterval(() => { const t = Date.now(); setNow(t); if (t >= waitUntil) clearInterval(id); }, 250);
    return () => clearInterval(id);
  }, [waitUntil]);

  const max = (quota && quota.max_chars) || 300;
  const blocked = quota && quota.blocked;
  const wait = Math.max(0, Math.ceil((waitUntil - now) / 1000));
  const why = blocked === 'quota_day' ? 'Limite de conversa de hoje atingido. Volta amanhã.'
    : blocked === 'quota_hour' ? 'Limite desta hora atingido. Tente mais tarde.'
      : wait ? `Aguarde ${wait} s para mandar outra.` : '';
  const canSend = !busy && !blocked && !wait && text.trim().length > 0 && text.length <= max;

  const send = async (e) => {
    e.preventDefault();
    if (!canSend) return;
    const q = text.trim(), L = latest.current;
    setText(''); setBusy(true);
    setItems((xs) => [...xs, msg('me', q)]);
    let r;
    try {
      r = await post('/api/chat', { agent: L.agentId, text: q, pid: L.pid, stage: L.stage, status: L.status, needs: L.needs ? L.needs.split(',') : [] });
    } catch {
      r = { ok: false, reply: 'Me perdi aqui no meio do trabalho. Tenta de novo daqui a pouco?', source: 'falha' };
    }
    setItems((xs) => [...xs, msg('agent', r.reply || '…', { source: r.source }), ...(r.notice ? [msg('agent', r.notice, { source: 'cota' })] : [])]);
    if (r.remaining != null) setQuota((qq) => ({ ...(qq || {}), ...r }));
    const cd = r.cooldown_s || 0;
    if (cd) { setWaitUntil(Date.now() + cd * 1000); setNow(Date.now()); }
    setBusy(false);
    requestAnimationFrame(() => input.current && input.current.focus());
  };

  return (
    <Sheet open onOpenChange={(open) => { if (!open) latest.current.onClose(); }}>
      <SheetContent side="right" className="pw-theme pw-chat" aria-describedby="pw-chat-desc"
        onOpenAutoFocus={(e) => { e.preventDefault(); if (input.current) input.current.focus(); }}
        onKeyDown={(e) => { if (e.key !== 'Escape') e.stopPropagation(); }}>
        <SheetHeader className="pw-chat-head">
          <SheetTitle className="pw-chat-title">{p.name} <span>· {p.role}</span></SheetTitle>
          <SheetDescription id="pw-chat-desc" className="pw-chat-desc">
            Conversa rápida: {p.name} explica e sugere, mas não executa nada. Use os botões para agir.
          </SheetDescription>
          {p.statusText && <StatusChip need={p.status === 'need'} active={p.status === 'work'}>{p.statusText}</StatusChip>}
          <div className="pw-chat-actions">
            {(p.actions || []).map((a, k) => (
              <button key={a.label} type="button" className={'pw-btn' + (k === 0 ? ' pw-btn-primary' : '')}
                onClick={() => latest.current.actions[k].act()}>{a.label}</button>
            ))}
          </div>
        </SheetHeader>

        <div ref={list} className="pw-chat-log" role="log" aria-live="polite" aria-relevant="additions" aria-label={`Conversa com ${p.name}`}>
          {items.map((m) => (
            <div key={m.id} className={'pw-msg ' + (m.who === 'me' ? 'pw-msg-me' : 'pw-msg-agent')}>
              <span className="sr-only">{m.who === 'me' ? 'Você: ' : p.name + ': '}</span>{m.text}
            </div>
          ))}
          {busy && (
            <div className="pw-msg pw-msg-agent pw-typing" aria-label={`${p.name} está digitando`}>
              <i /><i /><i /><span className="pw-typing-txt">digitando…</span>
            </div>
          )}
        </div>

        <form className="pw-chat-form" onSubmit={send}>
          <div className="pw-chat-row">
            <label htmlFor="pw-chat-in" className="sr-only">Mensagem para {p.name}</label>
            <input id="pw-chat-in" ref={input} className="pw-chat-input" value={text} maxLength={max} autoComplete="off"
              placeholder={blocked ? 'Conversa pausada' : `Pergunte algo para ${p.name}`} disabled={!!blocked}
              onChange={(e) => setText(e.target.value)} aria-describedby="pw-chat-meta" />
            <button type="submit" className="pw-btn pw-btn-primary" disabled={!canSend} aria-disabled={!canSend}>Enviar</button>
          </div>
          <p id="pw-chat-meta" className="pw-chat-meta">
            {why || (quota ? `${quota.remaining} mensage${quota.remaining === 1 ? 'm restante' : 'ns restantes'} hoje` : '')}
            {text.length > max * 0.8 && <span> · {text.length}/{max}</span>}
          </p>
        </form>
      </SheetContent>
    </Sheet>
  );
}

const same = (a, b) => ['agentId', 'name', 'role', 'intro', 'stage', 'status', 'statusText', 'pid', 'needs'].every((k) => a[k] === b[k])
  && (a.actions || []).map((x) => x.label).join('|') === (b.actions || []).map((x) => x.label).join('|');
export default React.memo(AgentChat, same);
