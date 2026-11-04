import React from 'react';
import {
  Activity, AlertCircle, ArrowRight, CheckCircle2, Clock3, Coins,
  Gauge, Play, Plus, Sparkles,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import Boneco from '../Boneco.jsx';

export const PROD_LABEL = { received: 'Preparando o produto', awaiting_references: 'Faltam fotos', validated: 'Direção', scripted: 'Direção', producing: 'Em produção',
  editing: 'Montando', awaiting_final_review: 'Pronto para revisar', completed: 'Exportada', paused: 'Pausada', failed: 'Falhou', cancelled: 'Cancelada' };
export const AGENT_STATE = { need: ['need', 'Precisa de você'], work: ['work', 'Trabalhando'], idle: ['wait', 'Livre'] };

export const Avatar = ({ look, size = 40 }) => (
  <span className="pv-avatar" aria-hidden="true" style={{ width: size, height: size, background: look.shirt + '55' }}><Boneco look={look} crop size={size - 4} /></span>
);

const STATUS_STYLE = {
  done: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  work: 'border-sky-200 bg-sky-50 text-sky-700',
  need: 'border-[#c7df55] bg-[#f1fad1] text-[#34420d]',
  wait: 'border-slate-200 bg-slate-50 text-slate-600',
};

export const Pill = ({ s, children }) => {
  const StatusIcon = s === 'done' ? CheckCircle2 : s === 'need' ? AlertCircle : s === 'work' ? Activity : Clock3;
  return <Badge variant="outline" className={`h-6 gap-1 rounded-full px-2 font-medium ${STATUS_STYLE[s] || STATUS_STYLE.wait}`}><StatusIcon className={s === 'work' ? 'animate-pulse' : ''} />{children}</Badge>;
};

const greet = () => { const h = new Date().getHours(); return h < 5 ? 'Boa madrugada' : h < 12 ? 'Bom dia' : h < 18 ? 'Boa tarde' : 'Boa noite'; };

function SectionHeading({ eyebrow, title, description, action }) {
  return (
    <div className="flex items-end justify-between gap-4">
      <div>
        {eyebrow && <div className="mb-1 text-[11px] font-semibold uppercase tracking-[.12em] text-muted-foreground">{eyebrow}</div>}
        <h3 className="m-0 text-base font-semibold tracking-[-.01em] text-foreground">{title}</h3>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export default function Central({ v }) {
  const name = v.account ? v.account.user.name.split(' ')[0] : '';
  const n = v.attn.length;
  const pl = v.pipeline;
  const progress = v.hasProd ? pl.progress : 0;

  return (
    <div className="pv-scroll">
      <div className="mx-auto flex max-w-[1180px] flex-col gap-8">
        <header className="flex flex-col gap-5 border-b border-border pb-7 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-border bg-white px-2.5 py-1 text-xs font-medium text-muted-foreground shadow-xs">
              <span className="size-1.5 rounded-full bg-emerald-500" />Workspace operacional
            </div>
            <h2 className="m-0 text-[clamp(1.65rem,3vw,2.25rem)] font-semibold leading-tight tracking-[-.035em] text-foreground">{greet()}{name ? `, ${name}` : ''}.</h2>
            <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-muted-foreground">
              {n ? (n === 1 ? 'Há uma decisão aguardando sua análise.' : `Há ${n} decisões aguardando sua análise.`) : v.hasProd ? 'Nada precisa de você agora. A equipe segue trabalhando.' : 'Sua equipe está pronta para transformar um produto em uma nova missão.'}
            </p>
          </div>
          {!v.hasProd && <Button className="h-10 bg-[var(--pivoo-ink)] px-4 text-white hover:bg-[#22305f]" onClick={() => { v.setView('missao'); v.newProd(); }}><Plus />Criar primeira missão</Button>}
        </header>

        <section aria-label="Visão geral" data-tour="overview" className="grid gap-3 sm:grid-cols-3">
          <Card size="sm" className="pv-metric-card">
            <CardHeader><CardDescription>Decisões pendentes</CardDescription><CardAction><span className="pv-metric-icon"><AlertCircle /></span></CardAction></CardHeader>
            <CardContent><div className="text-2xl font-semibold tracking-[-.03em]">{n}</div><p className="mt-1 text-xs text-muted-foreground">{n ? 'Requer sua atenção' : 'Tudo em dia'}</p></CardContent>
          </Card>
          <Card size="sm" className="pv-metric-card">
            <CardHeader><CardDescription>Missão em curso</CardDescription><CardAction><span className="pv-metric-icon"><Gauge /></span></CardAction></CardHeader>
            <CardContent><div className="text-2xl font-semibold tracking-[-.03em]">{progress}%</div><Progress value={progress} className="mt-2 h-1.5" /><p className="mt-2 truncate text-xs text-muted-foreground">{v.hasProd ? v.stageLabel : 'Nenhuma missão aberta'}</p></CardContent>
          </Card>
          <Card size="sm" className="pv-metric-card">
            <CardHeader><CardDescription>Consumo atual</CardDescription><CardAction><span className="pv-metric-icon"><Coins /></span></CardAction></CardHeader>
            <CardContent><div className="text-2xl font-semibold tracking-[-.03em]">{v.credits.spent}</div><p className="mt-1 text-xs text-muted-foreground">de {v.credits.budget} créditos previstos</p></CardContent>
          </Card>
        </section>

        <section aria-labelledby="central-attention" data-tour="needs-you" className="space-y-3">
          <SectionHeading eyebrow="Prioridades" title="Precisa de você" description="Aprovações, liberações de gasto e decisões da equipe aparecem aqui." action={n > 0 ? <Badge className="bg-[var(--pivoo-lime)] text-[var(--pivoo-ink)]">{n} {n === 1 ? 'pendência' : 'pendências'}</Badge> : null} />
          <Card className="gap-0 py-0">
            {n === 0 && (
              <div className="flex min-h-32 items-center gap-4 px-5 py-6">
                <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-emerald-50 text-emerald-700"><CheckCircle2 className="size-5" /></span>
                <div className="min-w-0 flex-1"><div className="font-semibold">{v.hasProd ? 'Tudo em dia' : 'Pronto para começar'}</div><p className="mt-1 text-sm text-muted-foreground">{v.hasProd ? 'Avisaremos quando uma decisão realmente precisar de você.' : 'Crie uma missão e deixe a equipe organizar o fluxo de produção.'}</p></div>
                {!v.hasProd && <Button variant="outline" onClick={() => { v.setView('missao'); v.newProd(); }}><Plus />Nova missão</Button>}
              </div>
            )}
            {v.attn.map((a, index) => (
              <div key={a.id} className={`flex flex-col gap-4 px-5 py-4 sm:flex-row sm:items-center ${index ? 'border-t border-border' : ''}`}>
                {a.room ? <Avatar look={a.room.look} /> : <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-amber-50 text-amber-700"><AlertCircle className="size-5" /></span>}
                <div className="min-w-0 flex-1"><div className="font-semibold">{a.title}{a.who ? ` · ${a.who}` : ''}</div><p className="mt-1 text-sm leading-relaxed text-muted-foreground">{a.text}</p></div>
                <Button className="h-9 shrink-0 bg-[var(--pivoo-lime)] text-[var(--pivoo-ink)] hover:bg-[var(--pivoo-lime-strong)]" onClick={a.room ? a.room.work : v.goNext}>{a.room ? 'Resolver' : 'Ver pausa'}<ArrowRight /></Button>
              </div>
            ))}
          </Card>
        </section>

        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.45fr)_minmax(300px,.85fr)]">
          <section aria-labelledby="central-mission" className="space-y-3">
            <SectionHeading eyebrow="Produção" title="Missão em curso" description="Progresso, próxima ação e orçamento em um só lugar." />
            <Card className="min-h-[248px]">
              {v.hasProd ? (<>
                <CardHeader className="border-b">
                  <CardTitle id="central-mission" className="text-lg font-semibold">{v.prodName}</CardTitle>
                  <CardDescription>{v.stageLabel} · {v.spentText}</CardDescription>
                  <CardAction><Pill s={pl.orchestrator.state}>{pl.orchestrator.label}</Pill></CardAction>
                </CardHeader>
                <CardContent className="flex flex-1 flex-col justify-between gap-6">
                  <div><div className="mb-2 flex items-center justify-between text-xs font-medium text-muted-foreground"><span>Progresso da missão</span><span>{pl.progress}%</span></div><Progress value={pl.progress} className="h-2" /></div>
                  <div className="rounded-xl border border-border bg-muted/45 p-4"><div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-[.08em] text-muted-foreground"><Sparkles className="size-3.5" />Próxima ação</div><div className="font-medium">{v.nextLong || 'A equipe está trabalhando sem depender de você.'}</div></div>
                  <div className="flex flex-wrap gap-2">{v.nextLabel && <Button className="bg-[var(--pivoo-lime)] text-[var(--pivoo-ink)] hover:bg-[var(--pivoo-lime-strong)]" onClick={v.goNext}>{v.nextLabel}<ArrowRight /></Button>}<Button variant="outline" onClick={() => v.setView('missao')}><Play />Ver fluxo</Button></div>
                </CardContent>
              </>) : (
                <CardContent className="flex flex-1 flex-col items-center justify-center py-12 text-center"><span className="mb-3 grid size-11 place-items-center rounded-xl bg-muted text-muted-foreground"><Sparkles className="size-5" /></span><div className="font-semibold">Sem missão aberta</div><p className="mt-1 max-w-sm text-sm text-muted-foreground">Comece com o produto; o PIVOO organiza direção, geração, revisão e entrega.</p><Button className="mt-5" onClick={() => { v.setView('missao'); v.newProd(); }}><Plus />Começar missão</Button></CardContent>
              )}
            </Card>
          </section>

          <section aria-labelledby="central-team" className="space-y-3">
            <SectionHeading eyebrow="Operação" title="Equipe agora" description="Status dos agentes em tempo real." action={<Button variant="ghost" size="sm" onClick={() => v.setView('equipe')}>Ver equipe<ArrowRight /></Button>} />
            <Card className="gap-0 py-0">
              {v.team.map((a, index) => { const [s, t] = AGENT_STATE[v.statuses[a.id]] || AGENT_STATE.idle; return (
                <button key={a.id} className={`flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/55 focus-visible:z-10 ${index ? 'border-t border-border' : ''}`} onClick={() => v.openStep(a.tab)}>
                  <Avatar look={a.look} size={36} /><span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold">{a.name}</span><span className="block truncate text-xs text-muted-foreground">{a.role}</span></span><Pill s={s}>{t}</Pill>
                </button>); })}
            </Card>
          </section>
        </div>

        <section aria-labelledby="central-recent" className="space-y-3">
          <SectionHeading eyebrow="Histórico" title="Missões recentes" description="Retome produções anteriores sem perder contexto." />
          <Card className="gap-0 py-0">
            {v.productions.length === 0 && <div className="px-5 py-10 text-center text-sm text-muted-foreground">Suas missões aparecerão aqui.</div>}
            {v.productions.slice(0, 6).map((p, index) => (
              <div key={p.id} className={`flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center ${index ? 'border-t border-border' : ''}`}>
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground"><Activity className="size-4" /></span>
                <div className="min-w-0 flex-1"><div className="truncate text-sm font-semibold">{p.name || p.id}</div><div className="mt-0.5 text-xs text-muted-foreground">{PROD_LABEL[p.status] || p.label}{p.mode === 'simulated' ? ' · DEMO' : ''} · {new Date(p.created_at).toLocaleDateString('pt-BR')}</div></div>
                {p.current ? <Pill s="done">Aberta</Pill> : <Button variant="outline" size="sm" onClick={() => { p.open(); v.setView('missao'); }}>Abrir</Button>}
              </div>
            ))}
          </Card>
        </section>
      </div>
    </div>
  );
}
