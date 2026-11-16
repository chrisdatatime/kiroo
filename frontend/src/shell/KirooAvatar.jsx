import React from 'react';
import Boneco from '../Boneco.jsx';
import { kirooLook, kirooTint } from '../ui/avatar.js';

// Avatar redondo da conta: o kiroo do usuário (mesmo sprite do escritório), recortado do peito para cima.
export default function KirooAvatar({ user, size = 32 }) {
  const look = kirooLook(user);
  return (
    <span className="kv-av" aria-hidden="true" style={{ width: size, height: size, background: kirooTint(look) }}>
      <Boneco look={look} crop size={Math.round(size * 0.82)} />
    </span>
  );
}
