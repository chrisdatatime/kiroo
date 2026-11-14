import * as React from 'react';
import { PHONE_MQ } from '../ui/mobile.js';

// Celular (<= 640 px). Lê o valor já no primeiro desenho (sem piscar o layout de desktop) e acompanha a rotação.
export function usePhone() {
  const get = () => typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia(PHONE_MQ).matches;
  const [phone, setPhone] = React.useState(get);
  React.useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return undefined;
    const mq = window.matchMedia(PHONE_MQ);
    const on = () => setPhone(mq.matches);
    on();
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return phone;
}
