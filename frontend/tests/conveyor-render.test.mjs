// Esteira de agentes: marcação renderizada (sem navegador). O Vite compila o JSX em modo SSR e o React gera o HTML:
// estados, estação atual (aria-current), cancelada congelada, movimento reduzido e créditos só quando existem.
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { renderToStaticMarkup } from 'react-dom/server';
import React from 'react';
import { buildPipeline } from '../src/shell/pipeline.js';

const front = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const vite = await createServer({ root: front, configFile: path.join(front, 'vite.config.js'), logLevel: 'error', server: { middlewareMode: true, hmr: false }, appType: 'custom',
  optimizeDeps: { noDiscovery: true, include: [] } });   // sem pré-empacotar dependências: só compilar o JSX
try {
  const { default: Conveyor } = await vite.ssrLoadModule('/src/shell/Conveyor.jsx');
  const team = [
    { id: 'nina', name: 'Nina', look: { shirt: '#FF8FC0', acc: 'bone' } }, { id: 'theo', name: 'Theo', look: { shirt: '#FF9A3D', acc: 'oculos' } },
    { id: 'iris', name: 'Iris', look: { shirt: '#B6E84A', acc: 'fones' } }, { id: 'rui', name: 'Rui', look: { shirt: '#4FD0BF', acc: 'oculos' } },
    { id: 'lia', name: 'Lia', look: { shirt: '#A88BF0', acc: 'fones' } }, { id: 'beto', name: 'Beto', look: { shirt: '#4A7BF0', acc: 'boina' } },
  ];
  const render = (props) => renderToStaticMarkup(React.createElement(Conveyor, { team, missionKey: 'p1', onOpen: () => {}, ...props }));
  const count = (html, re) => (html.match(re) || []).length;

  // imagens em geração: Iris ativa (pulsando), Nina e Theo concluídas, resto apagado; o que está acontecendo aparece
  let p = buildPipeline({ idx: 3, statuses: { iris: 'work' }, hasProd: true, detail: { imagens: 'Criando cena 2' } });
  let html = render({ stations: p.stations, ended: null });
  assert.equal(count(html, /<li[^>]*class="pv-station"/g), 6);
  assert.equal(count(html, /<button type="button" class="pv-station-btn"/g), 6);   // teclado: 6 botões reais
  assert.equal(count(html, /data-s="done"/g), 2);
  assert.equal(count(html, /data-s="active"/g), 1);
  assert.equal(count(html, /data-s="pending"/g), 3);
  assert.equal(count(html, /aria-current="step"/g), 1);
  assert.match(html, /data-s="active" data-current="true"/);
  assert.match(html, /aria-label="Iris, Imagens: Em andamento\. Criando cena 2\."/);
  assert.match(html, /class="pv-station-now">Criando cena 2</);
  assert.match(html, /aria-live="polite">Iris, Imagens: Em andamento\. Criando cena 2\.</);
  assert.ok(!html.includes('pv-belt-hop'), 'primeiro desenho nunca reproduz o salto');
  assert.ok(!html.includes('pv-station-tip'), 'sem dado de créditos, nada de tooltip');
  assert.ok(!html.includes('data-motion'));
  assert.match(html, /aria-label="Esteira de agentes"/);
  assert.match(html, /Nina<\/span><span class="pv-station-step">Produto</);

  // esperando você: destaque de atenção e rótulo
  p = buildPipeline({ idx: 1, statuses: { theo: 'need' }, hasProd: true, detail: { direcao: 'Precisa de aprovação' } });
  html = render({ stations: p.stations });
  assert.match(html, /data-s="need" data-current="true"/);
  assert.match(html, /pv-station-badge" data-k="need">!</);
  assert.match(html, /Theo, Direção: Esperando seu OK\. Precisa de aprovação\. Abrir para decidir\./);

  // cancelada: congelada, selo "Cancelada" na estação onde parou, nada ativo nem esperando você
  p = buildPipeline({ idx: 3, statuses: { iris: 'work', rui: 'need' }, hasProd: true, ended: 'cancelled' });
  html = render({ stations: p.stations, ended: 'cancelled' });
  assert.match(html, /class="pv-belt pv-card" aria-label="Esteira de agentes" data-ended="cancelled"/);
  assert.equal(count(html, /pv-station-seal/g), 1);
  assert.match(html, /class="pv-station-seal" aria-hidden="true">Cancelada</);
  assert.equal(count(html, /data-s="active"|data-s="need"/g), 0);
  assert.equal(count(html, /data-s="ended"/g), 3);
  assert.match(html, /aria-live="polite">Iris, Imagens: Cancelada\./);

  // movimento reduzido: a faixa declara e nunca desenha o salto (CSS troca só a cor)
  html = render({ stations: p.stations, ended: null, reduced: true });
  assert.match(html, /data-motion="reduced"/);
  assert.ok(!html.includes('pv-belt-hop'));

  // créditos já usados: só na estação com dado, como tooltip ligada ao botão (hover e leitor de tela)
  p = buildPipeline({ idx: 5, statuses: { lia: 'need' }, hasProd: true });
  html = render({ stations: p.stations, credits: { imagens: '18,50' } });
  assert.equal(count(html, /pv-station-tip/g), 1);
  assert.match(html, /aria-describedby="pv-belt-cr-imagens"/);
  assert.match(html, /id="pv-belt-cr-imagens">Créditos usados nesta etapa: <strong>18,50<\/strong>/);

  // tudo entregue: nenhuma estação atual; anúncio de missão concluída
  p = buildPipeline({ idx: 10, statuses: {}, hasProd: true });
  html = render({ stations: p.stations });
  assert.equal(count(html, /aria-current/g), 0);
  assert.equal(count(html, /data-s="done"/g), 6);
  assert.match(html, /Missão concluída: todas as etapas entregues\./);
  console.log('conveyor-render ok');
} finally {
  await vite.close();
}
