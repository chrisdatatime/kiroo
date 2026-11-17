import React from 'react';
import { Check, ChevronDown, CircleHelp, Coins, FileText, LogOut, Moon, UserRound } from 'lucide-react';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuRadioGroup, DropdownMenuRadioItem,
  DropdownMenuSeparator, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet';
import KirooAvatar from './KirooAvatar.jsx';
import {
  appearanceLabel, appearanceOptions, balanceLong, balanceShort, creditItems, displayName, legalLinks, nextIndex,
  supportHref, videosApprox,
} from './accountMenu.js';
import './accountMenu.css';

// Estrela de crédito (✦) do design, em SVG para não depender de fonte.
export const Spark = ({ size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className="am-spark"><path d="M12 2l2.2 7.8L22 12l-7.8 2.2L12 22l-2.2-7.8L2 12l7.8-2.2z" fill="currentColor" /></svg>
);

// Ações do menu (as mesmas no popover e na gaveta).
function useActions(v) {
  return {
    profile: () => v.openSettings('perfil'),
    statement: () => v.openSettings('creditos'),
    pricing: () => v.openPricing(),
    receipts: () => v.openReceipts(),
    logout: () => v.logout(),
  };
}

// Desktop: popover com submenus (Radix: setas, Esc, clique fora, foco e aria-expanded). Fecha ao escolher qualquer item.
export function AccountMenu({ v, children, side = 'top', align = 'start' }) {
  const a = useActions(v);
  const user = (v.account && v.account.user) || {};
  const [theme, setTheme] = React.useState('light');
  const credits = creditItems();
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>{children}</DropdownMenuTrigger>
      <DropdownMenuContent side={side} align={align} sideOffset={8} className="am" aria-label="Conta">
        <div className="am-head">
          <KirooAvatar user={user} size={40} />
          <div className="am-head-txt">
            <strong title={user.email}>{user.email || displayName(v.account)}</strong>
            {v.wallet && <span><Spark size={11} />{balanceLong(v.wallet)}</span>}
          </div>
        </div>
        <DropdownMenuSeparator className="am-sep" />
        <DropdownMenuItem className="am-item" onSelect={a.profile}><UserRound aria-hidden="true" /><span>Perfil</span></DropdownMenuItem>
        <DropdownMenuSub>
          <DropdownMenuSubTrigger className="am-item"><Coins aria-hidden="true" /><span>Créditos</span></DropdownMenuSubTrigger>
          <DropdownMenuSubContent className="am am-subm" sideOffset={10}>
            {credits.map((c) => (
              <DropdownMenuItem key={c.id} className="am-item am-plain" disabled={!!c.soon}
                onSelect={c.id === 'statement' ? a.statement : c.id === 'pricing' ? a.pricing : c.id === 'receipts' && !c.soon ? a.receipts : undefined}>
                <span>{c.label}</span>{c.soon && <small className="am-soon">em breve</small>}
              </DropdownMenuItem>
            ))}
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        <DropdownMenuSub>
          <DropdownMenuSubTrigger className="am-item"><Moon aria-hidden="true" /><span>Aparência</span><small className="am-val">{appearanceLabel(theme)}</small></DropdownMenuSubTrigger>
          <DropdownMenuSubContent className="am am-subm" sideOffset={10}>
            <DropdownMenuRadioGroup value={theme} onValueChange={setTheme}>
              {appearanceOptions().map((o) => <DropdownMenuRadioItem key={o.id} value={o.id} className="am-item am-plain">{o.label}</DropdownMenuRadioItem>)}
            </DropdownMenuRadioGroup>
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        <DropdownMenuSub>
          <DropdownMenuSubTrigger className="am-item"><FileText aria-hidden="true" /><span>Legal</span></DropdownMenuSubTrigger>
          <DropdownMenuSubContent className="am am-subm" sideOffset={10}>
            {legalLinks(v.landingUrl).map((l) => (
              <DropdownMenuItem key={l.id} className="am-item am-plain" asChild><a href={l.href} target="_blank" rel="noopener noreferrer">{l.label}</a></DropdownMenuItem>
            ))}
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        <DropdownMenuSeparator className="am-sep" />
        <DropdownMenuItem className="am-item" asChild><a href={supportHref(v.account)}><CircleHelp aria-hidden="true" /><span>Ajuda e suporte</span></a></DropdownMenuItem>
        <DropdownMenuItem className="am-item" onSelect={a.logout}><LogOut aria-hidden="true" /><span>Sair</span></DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

// Linha da conta no rodapé do menu lateral: avatar kiroo + nome + ✦ saldo. Abre o popover.
export const AccountRow = React.forwardRef(function AccountRow({ v, ...props }, ref) {
  const user = (v.account && v.account.user) || {};
  const bal = balanceShort(v.wallet);
  return (
    <button ref={ref} type="button" className="am-row" data-tour="account" aria-label={`${displayName(v.account)}${bal ? `, ${balanceLong(v.wallet)}` : ''}. Menu da conta`} {...props}>
      <KirooAvatar user={user} size={32} />
      <span className="am-row-name">{displayName(v.account)}</span>
      {bal && <span className="am-row-bal" title="Créditos"><Spark />{bal}</span>}
    </button>
  );
});

// Celular: gaveta inferior. Seções com aria-expanded; setas sobem e descem entre os itens; Esc e o fundo fecham.
export function AccountDrawer({ v, open, onOpenChange }) {
  const a = useActions(v);
  const user = (v.account && v.account.user) || {};
  const [sec, setSec] = React.useState(null);
  const listRef = React.useRef(null);
  const close = () => onOpenChange(false);
  const run = (fn) => () => { close(); fn(); };
  const toggle = (id) => setSec((s) => (s === id ? null : id));
  const onKeyDown = (e) => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key) || !listRef.current) return;
    const items = Array.from(listRef.current.querySelectorAll('[data-am-item]:not([disabled])'));
    const i = items.indexOf(document.activeElement);
    const j = nextIndex(i < 0 ? -1 : i, items.length, i < 0 && e.key === 'ArrowUp' ? 'End' : e.key);
    if (j >= 0) { e.preventDefault(); items[j].focus(); }
  };
  const vids = videosApprox(v.wallet);
  const section = ({ id, icon: Icon, label, value, children }) => (
    <>
      <button type="button" data-am-item className="am-item am-dr-item" aria-expanded={sec === id} aria-controls={`am-sec-${id}`} onClick={() => toggle(id)}>
        <Icon aria-hidden="true" /><span>{label}</span>{value && <small className="am-val">{value}</small>}<ChevronDown className="am-chev" aria-hidden="true" />
      </button>
      {sec === id && <div id={`am-sec-${id}`} className="am-dr-sub">{children}</div>}
    </>
  );
  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) setSec(null); onOpenChange(o); }}>
      <SheetContent side="bottom" showCloseButton={false} className="am-drawer" onKeyDown={onKeyDown}>
        <span className="am-grip" aria-hidden="true" />
        <div className="am-head">
          <KirooAvatar user={user} size={44} />
          <div className="am-head-txt">
            <SheetTitle className="am-dr-title">{displayName(v.account)}</SheetTitle>
            <SheetDescription className="am-dr-desc"><Spark size={11} />{[balanceLong(v.wallet), vids].filter(Boolean).join(' · ')}</SheetDescription>
          </div>
        </div>
        {v.wallet && !v.wallet.exempt && (
          <div className="am-dr-cta"><button type="button" data-am-item className="am-buy" onClick={run(a.pricing)}>Comprar créditos</button></div>
        )}
        <div className="am-sep am-sep-dr" role="separator" />
        <div ref={listRef} className="am-dr-list" role="group" aria-label="Conta">
          <button type="button" data-am-item className="am-item am-dr-item" onClick={run(a.profile)}><UserRound aria-hidden="true" /><span>Perfil</span></button>
          {section({ id: 'creditos', icon: Coins, label: 'Créditos e extrato', children: creditItems().map((c) => (
            <button key={c.id} type="button" data-am-item className="am-item am-plain am-dr-item" disabled={!!c.soon}
              onClick={c.id === 'statement' ? run(a.statement) : c.id === 'pricing' ? run(a.pricing) : c.id === 'receipts' && !c.soon ? run(a.receipts) : undefined}>
              <span>{c.label}</span>{c.soon && <small className="am-soon">em breve</small>}
            </button>
          )) })}
          {section({ id: 'aparencia', icon: Moon, label: 'Aparência', value: appearanceLabel('light'), children: appearanceOptions().map((o) => (
            <button key={o.id} type="button" data-am-item aria-pressed={o.id === 'light'} className="am-item am-plain am-dr-item">{o.label}{o.id === 'light' && <Check className="am-check" aria-hidden="true" />}</button>
          )) })}
          {section({ id: 'legal', icon: FileText, label: 'Legal', children: legalLinks(v.landingUrl).map((l) => (
            <a key={l.id} data-am-item className="am-item am-plain am-dr-item" href={l.href} target="_blank" rel="noopener noreferrer">{l.label}</a>
          )) })}
          <a data-am-item className="am-item am-dr-item" href={supportHref(v.account)}><CircleHelp aria-hidden="true" /><span>Ajuda e suporte</span></a>
          <button type="button" data-am-item className="am-item am-dr-item" onClick={run(a.logout)}><LogOut aria-hidden="true" /><span>Sair</span></button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
