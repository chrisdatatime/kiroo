import React from 'react';
import { AlertCircle, ArrowRight, Camera, Check, ChevronRight, Clock3, Image as ImageIcon, Loader2, Lock, MoreHorizontal, Play, Plus, UploadCloud } from 'lucide-react';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Avatar } from './Central.jsx';
import {
  ERROR_NOTE, FILTERS, TABLE_ROWS, agoLabel, countsOf, estimateLabel, filterCounts, filterProductions, firstName, firstSteps, greeting,
  needsYou, productName, relativeDate, showHowItWorks, showWelcome, statusOf, stepsVisible, summaryLine, teamSummary, thumbOf,
} from './inicio.js';
import { lockText, platformLogo, sceneThumb } from '../ui/falFlow.js';
import { usePhone } from '../hooks/use-phone.js';
import './inicio.css';

// Início (a antiga "Central"): saudação, o que precisa de você, criar vídeo, equipe e produções recentes.
// Dados e estados vêm do viewModel do App (v); a regra de cada texto/número fica em inicio.js (testada).

// Imagem opcional: some em vez de mostrar o ícone de imagem quebrada.
function Img({ src, ...rest }) {
  const [bad, setBad] = React.useState(false);
  React.useEffect(() => { setBad(false); }, [src]);
  if (!src || bad) return null;
  return <img src={src} alt="" onError={() => setBad(true)} {...rest} />;
}

export const Badge = ({ s, children }) => <span className="in-badge" data-tone={s.tone}><i aria-hidden="true" />{children || s.label}</span>;

const photoOf = (v) => { const r = v.P && v.P.sheet && v.P.sheet.references; const x = (r || []).find((y) => y && y.url); return x ? x.url : null; };
const aiTitleOf = (p, v) => (p.current && v.P && v.P.fal ? v.P.fal.title : '');
// % real: só existe para a produção aberta (esteira da missão fal).
const liveProgress = (p, v) => (p.current && v.falMission && v.falMission.status && v.falMission.status.kind === 'running' ? v.falMission.progress : null);
const sceneName = (v, id) => ((v.falNew && v.falNew.scenes.find((x) => x.id === id)) || {}).label || '';
const platName = (v, id) => ((v.falNew && v.falNew.platforms.find((x) => x.id === id)) || {}).label || '';

function useRows(v) {
  return React.useMemo(() => v.productions.map((p) => ({ p, st: statusOf(p), name: productName(p, aiTitleOf(p, v)),
    thumb: thumbOf(p, photoOf(v), sceneThumb), pct: liveProgress(p, v) })), [v.productions, v.P, v.falMission]);   // eslint-disable-line react-hooks/exhaustive-deps
}
const openProd = (v, p) => { p.open(); v.setView('missao'); };

// ---------------------------------------------------------------- "precisa de você"
function NeedsYou({ v, rows }) {
  const n = needsYou(v.productions);
  if (!n.first) return null;
  const row = rows.find((r) => r.p.id === n.first.id);
  const p = row.p;
  const meta = [sceneName(v, p.scene), platName(v, p.platform)].filter(Boolean).join(' · ');
  return (
    <section className="in-need" aria-labelledby="in-need-h" data-tour="needs-you">
      <span className="in-need-thumb" aria-hidden="true"><Img src={row.thumb} /><Play size={18} /></span>
      <div className="in-need-body">
        <div className="in-need-top"><Badge s={row.st}>{row.st.key === 'aprovacao' ? 'Aguardando sua aprovação' : row.st.label}</Badge><span className="in-muted">{agoLabel(p.created_at)}</span>
          {n.extra > 0 && <button type="button" className="in-link" onClick={() => v.setView('missao')}>+{n.extra} aguardando</button>}</div>
        <h2 id="in-need-h">{row.name}</h2>
        {meta && <p className="in-muted">{meta}</p>}
      </div>
      <div className="in-need-act">
        <button type="button" className="in-btn" onClick={() => openProd(v, p)}>Ver detalhes</button>
        <button type="button" className="in-btn in-btn-accent" onClick={() => openProd(v, p)}><Play size={16} aria-hidden="true" />{row.st.action}</button>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- "Criar novo vídeo" (mesmo envio do modal Nova produção)
function CreateCard({ v, phone }) {
  const f = v.falNew;
  const galleryRef = React.useRef(null), cameraRef = React.useRef(null);
  const [over, setOver] = React.useState(false);
  if (!f) {   // motor sem o fluxo foto + cenário: o cartão vira um convite que abre o modal de sempre
    return (
      <section className="in-card in-create" aria-labelledby="in-create-h" data-tour="new-mission-card">
        <h2 id="in-create-h">Criar novo vídeo</h2>
        <p className="in-muted">Comece pelo produto; o Kiroo cuida do resto.</p>
        <button type="button" className="in-btn in-btn-ink" onClick={v.newProd}><Plus size={16} aria-hidden="true" />Nova produção</button>
      </section>
    );
  }
  const pickAny = () => galleryRef.current && galleryRef.current.click();
  const drop = (e) => { e.preventDefault(); setOver(false); const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]; if (file && !f.busy) f.pickFile(file); };
  const cost = v.offer && v.offer.cc > 0 ? `Custa ${v.offer.credits} ${v.offer.credits === '1' ? 'crédito' : 'créditos'}` : (f.demo ? 'Demonstração: nada é cobrado' : '');
  const bal = v.wallet && !v.wallet.exempt && v.offer && v.offer.cc > 0 ? ` · saldo ${v.wallet.balance}` : '';
  return (
    <section className="in-card in-create" aria-labelledby="in-create-h" data-tour="new-mission-card">
      <h2 id="in-create-h">Criar novo vídeo</h2>
      <p className="in-muted">Uma foto vira um vídeo vertical de 15 s com narração, título e legenda.</p>
      <input ref={galleryRef} type="file" accept="image/jpeg,image/png,image/webp,image/*" className="in-file" onChange={f.pick} aria-label="Foto do produto (galeria)" disabled={f.busy} />
      <input ref={cameraRef} type="file" accept="image/*" capture="environment" className="in-file" onChange={f.pick} aria-label="Foto do produto (câmera)" disabled={f.busy} />
      <div className="in-steps">
        <div className="in-step in-step-photo">
          <h3><b>1</b>Foto do produto</h3>
          {f.file ? (
            <div className="in-photo"><img src={f.file.data} alt={'Sua foto: ' + f.file.name} />
              <button type="button" className="in-btn" onClick={pickAny} disabled={f.busy}><Camera size={16} aria-hidden="true" />Trocar foto</button></div>
          ) : phone ? (
            <div className="in-photo-btns">
              <button type="button" className="in-btn in-btn-lg" onClick={() => cameraRef.current && cameraRef.current.click()} disabled={f.busy}><Camera size={20} aria-hidden="true" />Tirar foto</button>
              <button type="button" className="in-btn in-btn-lg" onClick={pickAny} disabled={f.busy}><ImageIcon size={20} aria-hidden="true" />Galeria</button>
            </div>
          ) : (
            <div className={'in-drop' + (over ? ' is-over' : '')} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={drop}>
              <span className="in-drop-ic" aria-hidden="true"><UploadCloud size={22} /></span>
              <strong>Arraste a foto do produto</strong>
              <span className="in-muted">ou <button type="button" className="in-link" onClick={pickAny} disabled={f.busy}>escolha um arquivo</button>. JPG, PNG ou WEBP; fundo limpo funciona melhor.</span>
            </div>
          )}
        </div>
        <div className="in-step in-step-opts">
          <div>
            <h3 id="in-scene-l"><b>2</b>Cenário</h3>
            <div className="in-scenes" role="group" aria-labelledby="in-scene-l">
              {f.scenes.map((s) => (
                <button key={s.id} type="button" className="in-scene" aria-pressed={f.scene === s.id} aria-disabled={s.locked || undefined} disabled={f.busy}
                  title={lockText(s) || undefined} onClick={() => { if (!s.locked) f.setScene(s.id); }}>
                  <span className="in-scene-img"><Img src={sceneThumb(s.id)} />{f.scene === s.id && <span className="in-tick" aria-hidden="true"><Check size={12} strokeWidth={3} /></span>}
                    {s.locked && <span className="in-lock"><Lock size={14} aria-hidden="true" /></span>}</span>
                  <span className="in-scene-name">{s.label}</span>
                </button>
              ))}
            </div>
          </div>
          <div>
            <h3 id="in-plat-l"><b>3</b>Onde vai publicar</h3>
            <div className="in-plats" role="group" aria-labelledby="in-plat-l">
              {f.platforms.map((p) => (
                <button key={p.id} type="button" className="in-pill" aria-pressed={f.platform === p.id} disabled={f.busy} onClick={() => f.setPlatform(p.id)}>
                  <Img src={platformLogo(p.id)} className="in-plat-logo" />{p.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
      {f.error && <div role="alert" className="in-err"><AlertCircle size={18} aria-hidden="true" />{f.error}{f.noFunds && <button type="button" className="in-link" onClick={f.openBuy}>Ver pacotes</button>}</div>}
      <footer className="in-create-foot">
        <p className="in-muted"><Clock3 size={15} aria-hidden="true" />{`Fica pronto em ${estimateLabel()}`}{cost ? ` · ${cost}` : ''}{bal}</p>
        <button type="button" className="in-btn in-btn-ink in-btn-lg" onClick={f.create} disabled={f.busy || !f.file || f.errors.length > 0 || f.reuseBlocked}>
          {f.busy ? <Loader2 className="in-spin" size={16} aria-hidden="true" /> : <ArrowRight size={16} aria-hidden="true" />}{f.busy ? 'Começando…' : 'Criar vídeo'}
        </button>
      </footer>
    </section>
  );
}

// ---------------------------------------------------------------- lateral direita
function Team({ v }) {
  const t = teamSummary(v.team, v.statuses);
  return (
    <section className="in-card in-team" aria-labelledby="in-team-h" data-tour="team">
      <header><h2 id="in-team-h">Sua equipe</h2><button type="button" className="in-link" onClick={() => v.setView('equipe')}>Ver equipe<ChevronRight size={14} aria-hidden="true" /></button></header>
      <div className="in-team-row">
        <ul className="in-avatars" aria-label={`${t.count} agentes`}>{v.team.map((a) => <li key={a.id}><Avatar look={a.look} size={34} /></li>)}</ul>
        <p className="in-muted"><strong>{t.count} agentes</strong><span>{t.status}</span></p>
      </div>
      {t.waiting.length > 0 && <div className="in-team-wait"><Avatar look={t.waiting[0].look} size={30} /><span>{t.line}</span></div>}
    </section>
  );
}
const HOW = [['Envie a foto', 'Só a foto do produto. O resto a equipe faz.'], ['A equipe produz', 'Roteiro, imagens, narração e edição.'], ['Aprove e publique', 'Baixe o vídeo, o título e a legenda prontos.']];
function HowItWorks() {
  return (
    <section className="in-card in-how" aria-labelledby="in-how-h"><h2 id="in-how-h">Como funciona</h2>
      <ol>{HOW.map(([t, d], i) => <li key={t}><b aria-hidden="true">{i + 1}</b><span><strong>{t}</strong><span className="in-muted">{d}</span></span></li>)}</ol></section>
  );
}
function FirstSteps({ fs }) {
  return (
    <section className="in-card in-first" aria-labelledby="in-first-h">
      <header><h2 id="in-first-h">Primeiros passos</h2><span className="in-muted">{fs.done} de {fs.total}</span></header>
      <div className="in-bar" role="progressbar" aria-valuemin={0} aria-valuemax={fs.total} aria-valuenow={fs.done} aria-label="Primeiros passos"><i style={{ width: `${(fs.done / fs.total) * 100}%` }} /></div>
      <ul>{fs.steps.map((s) => <li key={s.id} data-done={s.done || undefined}><span className="in-check" aria-hidden="true">{s.done && <Check size={12} strokeWidth={3} />}</span>
        <span><strong>{s.label}</strong><span className="in-muted">{s.hint}</span></span><span className="in-sr">{s.done ? 'Feito' : 'Pendente'}</span></li>)}</ul>
    </section>
  );
}
function Welcome({ v }) {
  const w = v.account && v.account.welcome;
  return (
    <section className="in-welcome" aria-labelledby="in-welcome-h">
      <h2 id="in-welcome-h">{w ? `Seus ${w.credits} créditos de boas-vindas estão esperando.` : 'Bem-vindo ao Kiroo.'}</h2>
      <p>Envie a foto do seu produto e veja o vídeo pronto em poucos minutos.</p>
    </section>
  );
}

// ---------------------------------------------------------------- tabela
function RowMenu({ v, r }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild><button type="button" className="in-icon" aria-label={`Mais opções de ${r.name}`}><MoreHorizontal size={18} aria-hidden="true" /></button></DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => openProd(v, r.p)}>Abrir produção</DropdownMenuItem>
        {r.p.status === 'completed' && <DropdownMenuItem onSelect={() => openProd(v, r.p)}>Baixar arquivos</DropdownMenuItem>}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
function Recent({ v, rows }) {
  const [filter, setFilter] = React.useState('todas');
  const ps = rows.map((r) => r.p);
  const counts = filterCounts(ps);
  const shown = new Set(filterProductions(ps, filter).map((p) => p.id));
  const list = rows.filter((r) => shown.has(r.p.id)).slice(0, TABLE_ROWS);
  const filters = FILTERS.filter((f) => f.id !== 'baixadas' || counts.baixadas > 0);   // "Baixadas" só aparece se o servidor um dia informar downloads
  return (
    <section className="in-card in-recent" aria-labelledby="in-recent-h">
      <header><h2 id="in-recent-h">Produções recentes</h2>
        {rows.length > 0 && <div className="in-filters" role="group" aria-label="Filtrar produções">
          {filters.map((f) => <button key={f.id} type="button" className="in-pill in-pill-sm" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>{f.label} <span>{counts[f.id]}</span></button>)}</div>}
      </header>
      {rows.length === 0 ? (
        <div className="in-empty"><strong>Suas produções aparecem aqui.</strong><span className="in-muted">Quando você criar o primeiro vídeo, acompanhe cada etapa e baixe o resultado nesta lista.</span></div>
      ) : list.length === 0 ? <div className="in-empty"><span className="in-muted">Nenhuma produção neste filtro.</span></div> : (
        <table className="in-table">
          <thead><tr><th scope="col">Produto</th><th scope="col">Plataforma</th><th scope="col">Status</th><th scope="col">Criado</th><th scope="col"><span className="in-sr">Ação</span></th></tr></thead>
          <tbody>{list.map((r) => (
            <tr key={r.p.id}>
              <td><div className="in-prod"><span className="in-mini" aria-hidden="true"><Img src={r.thumb} /></span>
                <span><strong>{r.name}</strong><span className="in-muted">{sceneName(v, r.p.scene) || (r.p.mode === 'simulated' ? 'Demonstração' : '')}</span></span></div></td>
              <td>{platName(v, r.p.platform) || '—'}</td>
              <td><Badge s={r.st} />{r.pct != null && <span className="in-bar in-bar-sm" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={r.pct} aria-label={`Progresso de ${r.name}`}><i style={{ width: `${r.pct}%` }} /></span>}
                {r.st.key === 'erro' && <span className="in-muted in-note">{ERROR_NOTE}</span>}</td>
              <td className="in-muted">{relativeDate(r.p.created_at)}</td>
              <td className="in-act"><button type="button" className={'in-btn in-btn-sm' + (r.st.needsYou ? ' in-btn-accent' : '')} onClick={() => openProd(v, r.p)}>{r.st.action}</button><RowMenu v={v} r={r} /></td>
            </tr>))}</tbody>
        </table>
      )}
      {rows.length > TABLE_ROWS && <footer><button type="button" className="in-link" onClick={() => v.setView('missao')}>Ver todas as produções<ArrowRight size={14} aria-hidden="true" /></button></footer>}
    </section>
  );
}
// Celular: as produções viram cartões em lista.
function RecentPhone({ v, rows }) {
  return (
    <section className="in-recent-ph" aria-labelledby="in-recent-h"><h2 id="in-recent-h">Produções recentes</h2>
      {rows.length === 0 ? <div className="in-card in-empty"><strong>Suas produções aparecem aqui.</strong><span className="in-muted">Crie o primeiro vídeo acima.</span></div> : (
        <ul>{rows.slice(0, TABLE_ROWS).map((r) => (
          <li key={r.p.id}><button type="button" className="in-pcard" onClick={() => openProd(v, r.p)} aria-label={`${r.name}: ${r.st.label}. ${r.st.action}`}>
            <span className="in-mini" aria-hidden="true"><Img src={r.thumb} /></span>
            <span className="in-pcard-body"><strong>{r.name}</strong><span className="in-muted">{[platName(v, r.p.platform), relativeDate(r.p.created_at)].filter(Boolean).join(' · ')}</span>
              <Badge s={r.st} />{r.pct != null && <span className="in-bar in-bar-sm" aria-hidden="true"><i style={{ width: `${r.pct}%` }} /></span>}</span>
            <ChevronRight size={20} aria-hidden="true" /></button></li>))}</ul>)}
      {rows.length > TABLE_ROWS && <button type="button" className="in-link" onClick={() => v.setView('missao')}>Ver todas as produções<ArrowRight size={14} aria-hidden="true" /></button>}
    </section>
  );
}

// ---------------------------------------------------------------- tela
export default function Inicio({ v, phone: phoneProp }) {
  const detected = usePhone();
  const phone = phoneProp == null ? detected : phoneProp;
  const rows = useRows(v);
  const name = firstName(v.account && v.account.user);
  const line = summaryLine(v.productions);
  const fs = firstSteps({ account: v.account, productions: v.productions });
  const stepsOn = stepsVisible(fs, v.productions);
  const how = showHowItWorks(v.productions, stepsOn);
  const nNeeds = countsOf(v.productions).aprovacao + countsOf(v.productions).decisao;
  return (
    <div className="pv-scroll in-scroll"><div className="in-page" data-phone={phone || undefined}>
      <header className="in-hello" data-tour="overview">
        <h2>{greeting()}{name ? `, ${name}` : ''}</h2>
        {line && <p className="in-muted" data-needs={nNeeds || undefined}>{line}</p>}
      </header>
      {showWelcome(v.productions) && <Welcome v={v} />}
      <NeedsYou v={v} rows={rows} />
      <div className="in-grid">
        <div className="in-main"><CreateCard v={v} phone={phone} />{phone ? <RecentPhone v={v} rows={rows} /> : <Recent v={v} rows={rows} />}</div>
        <aside className="in-side-col" aria-label="Equipe e ajuda"><Team v={v} />{stepsOn && <FirstSteps fs={fs} />}{how && <HowItWorks />}</aside>
      </div>
    </div></div>
  );
}
