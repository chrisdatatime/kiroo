// Entrada da landing da raiz (kiroo.io): só a landing, sem o app, sem sessão e sem chamar /api.
// Os botões de entrada são links de página inteira para o app; o endereço e o modo de cadastro vêm do servidor (meta).
import React from 'react';
import { createRoot } from 'react-dom/client';
import Landing from './Landing.jsx';
import '../styles.css';

const meta = (name) => {
  const v = document.querySelector(`meta[name="${name}"]`)?.getAttribute('content') || '';
  return v.startsWith('__') ? '' : v;   // sem o servidor (vite dev), o marcador fica cru
};
const loginHref = meta('kiroo-login-url') || '/login';
const signupOpen = (meta('kiroo-signup') || 'closed') !== 'closed';

createRoot(document.getElementById('root')).render(<Landing loginHref={loginHref} signupOpen={signupOpen} />);
