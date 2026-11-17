import React from 'react';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { post } from '../engine/api.js';
import logo from '../assets/brand/wordmark-preto-laranja.svg';
import { TERMS_LINKS, termsVersion } from './termsGate.js';
import './auth.css';

// Tela de aceite obrigatório quando os Termos ou a Política mudam de versão (quem já tem conta vê antes de usar o app).
export default function TermsGate({ account, onAccepted, onLogout }) {
  const [ok, setOk] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState('');
  const version = termsVersion(account);
  const accept = async () => {
    setBusy(true); setErr('');
    try { await post('/api/account/terms/accept', { accept: true, version }); await onAccepted(); }
    catch (e) { setErr(e.message || 'Não foi possível registrar o aceite. Tente de novo.'); setBusy(false); }
  };
  return (
    <div className="au" role="dialog" aria-modal="true" aria-labelledby="tg-title">
      <div className="au-main">
        <div className="au-top"><span className="au-brand"><img src={logo} alt="Kiroo" /></span></div>
        <div className="au-center">
          <div className="au-panel">
            <h1 id="tg-title" className="au-title">Atualizamos nossos Termos</h1>
            <p className="au-sub">Para continuar usando o Kiroo, leia e aceite os Termos de Uso e a Política de Privacidade (versão {version}).</p>
            <label className="au-consent" htmlFor="tg-consent" style={{ marginTop: 20 }}>
              <input id="tg-consent" type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} />
              <span>Li e aceito os <a href={TERMS_LINKS.terms} target="_blank" rel="noopener">Termos de Uso</a> e a{' '}
                <a href={TERMS_LINKS.privacy} target="_blank" rel="noopener">Política de Privacidade</a>.</span>
            </label>
            {err && <p className="au-sub" role="alert">{err}</p>}
            <Button type="button" onClick={accept} disabled={!ok || busy} style={{ marginTop: 20 }}>
              {busy && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}Aceitar e continuar
            </Button>
            <button type="button" className="au-link" onClick={onLogout} style={{ marginTop: 14 }}>Sair</button>
          </div>
        </div>
      </div>
    </div>
  );
}
