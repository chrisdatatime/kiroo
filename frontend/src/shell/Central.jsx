import React from 'react';
import { Activity, AlertCircle, Ban, CheckCircle2, Clock3 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import Boneco from '../Boneco.jsx';
import Inicio from './Inicio.jsx';

export const PROD_LABEL = { received: 'Preparando o produto', awaiting_references: 'Faltam fotos', validated: 'Direção', scripted: 'Direção', producing: 'Em produção',
  editing: 'Montando', awaiting_final_review: 'Pronto para revisar', completed: 'Exportada', paused: 'Pausada', failed: 'Falhou', cancelled: 'Cancelada' };
export const AGENT_STATE = { need: ['need', 'Precisa de você'], work: ['work', 'Trabalhando'], idle: ['wait', 'Livre'] };

export const Avatar = ({ look, size = 40 }) => (
  <span className="pv-avatar" aria-hidden="true" style={{ width: size, height: size, background: look.shirt + '55' }}><Boneco look={look} crop size={size - 4} /></span>
);

const STATUS_STYLE = {
  done: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  work: 'border-sky-200 bg-sky-50 text-sky-700',
  need: 'border-[#FF5B2E] bg-white text-[#0E0E10]',
  wait: 'border-slate-200 bg-slate-50 text-slate-600',
  ended: 'border-slate-300 bg-slate-100 text-slate-700',   // cancelada/falhou/interrompido: sem animação
};

export const Pill = ({ s, children }) => {
  const StatusIcon = s === 'done' ? CheckCircle2 : s === 'need' ? AlertCircle : s === 'work' ? Activity : s === 'ended' ? Ban : Clock3;
  return <Badge variant="outline" className={`h-6 gap-1 rounded-full px-2 font-medium ${STATUS_STYLE[s] || STATUS_STYLE.wait}`}><StatusIcon className={s === 'work' ? 'animate-pulse' : ''} />{children}</Badge>;
};

// A Central virou o Início (shell/Inicio.jsx): desktop e celular na mesma tela, o layout muda por CSS e por `usePhone`.
export default function Central({ v }) {
  return <Inicio v={v} />;
}
