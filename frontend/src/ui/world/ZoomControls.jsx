import React from 'react';
import { Plus, Minus, LocateFixed, Maximize2 } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { MIN_LEVEL, MAX_LEVEL, fmtLevel } from '../../game/phaser/zoom.js';

// Coluna flutuante à direita (centro vertical): + / nível / − / centralizar / automático.
function Tip({ label, children }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side="left" className="pw-theme">{label}</TooltipContent>
    </Tooltip>
  );
}

export default function ZoomControls({ view, onIn, onOut, onCenter, onAuto }) {
  const { level, auto, free } = view;
  return (
    <div className="pw-zoom pw-surface" role="toolbar" aria-label="Zoom do mapa" aria-orientation="vertical">
      <Tip label="Aproximar (+)">
        <button type="button" className="pw-iconbtn" onClick={onIn} disabled={level >= MAX_LEVEL} aria-label="Aproximar"><Plus size={18} aria-hidden="true" /></button>
      </Tip>
      <Tip label={auto ? `Zoom ${fmtLevel(level)} (ajustado à tela). Role o mouse ou use + e −` : `Zoom ${fmtLevel(level)} (escolhido por você)`}>
        <span className="pw-zoom-level" role="status" aria-live="polite" tabIndex={0}>{fmtLevel(level)}</span>
      </Tip>
      <Tip label="Afastar (−)">
        <button type="button" className="pw-iconbtn" onClick={onOut} disabled={level <= MIN_LEVEL} aria-label="Afastar"><Minus size={18} aria-hidden="true" /></button>
      </Tip>
      <span className="pw-zoom-sep" aria-hidden="true" />
      <Tip label={free || !auto ? 'Recentralizar: mostrar a sede inteira' : 'Sede inteira, centralizada'}>
        <button type="button" className={'pw-iconbtn' + (free || !auto ? ' pw-iconbtn-on' : '')} onClick={onCenter} aria-label="Recentralizar e ajustar à tela"><LocateFixed size={18} aria-hidden="true" /></button>
      </Tip>
      <Tip label={auto ? 'Zoom automático (ajustado à tela)' : 'Voltar ao zoom automático (ajustar à tela)'}>
        <button type="button" className="pw-iconbtn" onClick={onAuto} disabled={auto} aria-label="Zoom automático"><Maximize2 size={16} aria-hidden="true" /></button>
      </Tip>
    </div>
  );
}
