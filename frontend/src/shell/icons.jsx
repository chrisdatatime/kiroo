import React from 'react';

// Ícones de traço (24×24, 1.8 px). Sempre acompanhados de texto ou aria-label: nunca são a única informação.
const P = {
  home: 'M3 10.5 12 3l9 7.5M5 9.5V20h5v-6h4v6h5V9.5',
  flow: 'M5 4h6v5H5zM13 15h6v5h-6zM8 9v3a2 2 0 0 0 2 2h3M5 15h4M5 18h4',
  team: 'M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M16 5.2a3 3 0 0 1 0 5.6M18 14.4c1.8.7 3 2.5 3 4.6',
  office: 'M4 21V6l8-3 8 3v15M9 21v-5h6v5M8 9h1M11.5 9h1M15 9h1M8 12.5h1M11.5 12.5h1M15 12.5h1',
  coin: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v10M9.5 9.6c0-1 1-1.6 2.5-1.6s2.5.6 2.5 1.6-1 1.5-2.5 1.9-2.5.9-2.5 1.9 1 1.6 2.5 1.6 2.5-.6 2.5-1.6',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 3.6-7 8-7s8 3 8 7',
  plus: 'M12 5v14M5 12h14',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  alert: 'M12 8v5M12 16.5v.5M10.3 3.9 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2',
  spark: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z',
  search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4',
  arrow: 'M5 12h14M13 6l6 6-6 6',
  down: 'M12 5v14M6 13l6 6 6-6',
  pilot: 'M12 3l8 4v5c0 4.5-3.2 8-8 9-4.8-1-8-4.5-8-9V7z',
  menu: 'M4 7h16M4 12h16M4 17h16',
  edit: 'M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17zM13.5 8l3 3',
  image: 'M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M9 9.5h.01',
  video: 'M3 6h13v12H3zM16 10l5-3v10l-5-3',
  shield: 'M12 3l8 4v5c0 4.5-3.2 8-8 9-4.8-1-8-4.5-8-9V7zM8.5 12l2.5 2.5L15.5 10',
  box: 'M21 8l-9-5-9 5v8l9 5 9-5zM3 8l9 5 9-5M12 13v8',
  chat: 'M4 5h16v11H9l-5 4z',
  brain: 'M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 5 1V4.5A2.5 2.5 0 0 0 9 4zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-5 1V4.5A2.5 2.5 0 0 1 15 4z',
};

export default function Icon({ name, size = 18, className, title }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" role={title ? 'img' : undefined} aria-label={title} aria-hidden={title ? undefined : 'true'}>
      <path d={P[name] || P.spark} />
    </svg>
  );
}
