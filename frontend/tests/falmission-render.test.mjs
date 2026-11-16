// Tela "Missão concluída": marcação renderizada (sem navegador; o Vite compila o JSX em modo SSR e o React gera o HTML).
// Cobre: concluída sem "Cancelar missão" e sem card de saldo; em andamento com "Cancelar missão"; narração escondida sem texto;
// esteira compacta como <ol> rotulado; botões e imagens acessíveis; "Compartilhar" fora do HTML sem suporte a arquivos.
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { renderToStaticMarkup } from 'react-dom/server';
import React from 'react';
import { falStations, gallery } from '../src/ui/falFlow.js';

const front = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const vite = await createServer({ root: front, configFile: path.join(front, 'vite.config.js'), logLevel: 'error', server: { middlewareMode: true, hmr: false }, appType: 'custom',
  optimizeDeps: { noDiscovery: true, include: [] } });
try {
  const { FalMissionView } = await vite.ssrLoadModule('/src/shell/MissionView.jsx');
  const team = [
    { id: 'nina', name: 'Nina', look: { shirt: '#FF8FC0', acc: 'bone' } }, { id: 'theo', name: 'Theo', look: { shirt: '#FF9A3D', acc: 'oculos' } },
    { id: 'iris', name: 'Iris', look: { shirt: '#B6E84A', acc: 'fones' } }, { id: 'rui', name: 'Rui', look: { shirt: '#4FD0BF', acc: 'oculos' } },
    { id: 'lia', name: 'Lia', look: { shirt: '#A88BF0', acc: 'fones' } }, { id: 'beto', name: 'Beto', look: { shirt: '#4A7BF0', acc: 'boina' } },
  ];
  const count = (html, re) => (html.match(re) || []).length;

  const delivered = (over = {}) => ({
    id: 'prod_1', engine: 'fal', status: 'awaiting_final_review', ended: null, running: false, scene: 'natural', platform: 'tiktok_shop',
    credits: { spent: 20 }, product: { name: 'Fone azul' },
    sheet: { references: [{ url: '/media/prod_1/references/foto.jpg' }] },
    delivery: { 'final.mp4': '/media/prod_1/delivery/final.mp4', 'cover.jpg': '/media/prod_1/delivery/cover.jpg', 'product_image_01.jpg': '/media/prod_1/delivery/product_image_01.jpg', 'caption.txt': '/media/prod_1/delivery/caption.txt' },
    fal: { scene: 'natural', scene_label: 'Natural', platform: 'tiktok_shop', platform_label: 'TikTok Shop', stage: 'delivered', delivery_status: 'complete',
      title: 'Fone de Ouvido Azul Marinho', caption: 'Descubra o conforto! Clica no carrinho. #FoneDeOuvido #TikTokAchados',
      image: { role: 'hero', url: '/media/prod_1/delivery/product_image_01.jpg' }, narration: null, elapsed_s: 180, submitted_at: '2026-11-14T10:00:00+00:00' },
    ...over,
  });
  const mission = (P, extra = {}) => ({ P, gallery: gallery(P), chips: { scene: { id: P.scene, label: 'Natural' }, platform: { id: P.platform, label: 'TikTok Shop' } },
    reuse: () => {}, variantCredits: '20', support: { whatsapp: 'https://wa.me/5511999999999', email: null }, busy: false, error: null, exportVideo: () => {}, start: () => {}, ...extra });
  const view = (over = {}) => ({ team, prodName: 'Fone azul', prodId: 'prod_1', ended: null, canCancel: false, confirmCancel: false, balanceText: 'Saldo: 120', firstVideo: null,
    cancelProd: () => {}, keepProd: () => {}, openBuy: () => {}, ...over });
  const render = (v, m) => renderToStaticMarkup(React.createElement(FalMissionView, { v, m }));

  // ---- concluída: banner + esteira compacta + resultado; sem Cancelar, sem saldo, sem o cartão verde "Pronto"
  let P = delivered();
  let html = render(view(), mission(P));
  assert.match(html, /<h1[^>]*>Seu vídeo está pronto<\/h1>/);
  assert.match(html, /Feito pela equipe em 3 min · 20 créditos usados/);
  assert.ok(!/Cancelar missão/.test(html), 'concluída não tem "Cancelar missão"');
  assert.ok(!/Saldo/.test(html) && !/SEU VÍDEO|Seu vídeo<\/div>/i.test(html.replace(/Seu vídeo está pronto/g, '')), 'sem o cartão do saldo');
  assert.ok(!/role="status"/.test(html) && !/pv-bar/.test(html), 'sem o cartão de status com a barra preta');
  assert.ok(!/pv-station/.test(html), 'a esteira grande some quando concluída');
  // esteira compacta: <ol> rotulado, 6 etapas com check, 5 linhas de ligação decorativas
  assert.match(html, /<ol class="fd-belt" aria-label="Etapas concluídas">/);
  assert.equal(count(html, /class="fd-step"/g), 6);
  assert.equal(count(html, /class="fd-ok"/g), 6);
  assert.equal(count(html, /class="fd-link" aria-hidden="true"/g), 5);
  assert.match(html, /aria-label="Planejamento, Nina, concluída"/); assert.match(html, /aria-label="Edição, Beto, concluída"/);
  // player 9:16 com poster, controles e selo; ações; cards
  assert.match(html, /<video[^>]*src="\/media\/prod_1\/delivery\/final\.mp4"[^>]*poster="\/media\/prod_1\/delivery\/cover\.jpg"[^>]*controls=""[^>]*aria-label="Vídeo final: Fone azul"/);
  assert.match(html, /15 s · 9:16/);
  // aguardando aprovação: barra fixa com "Aprovar vídeo" (principal) e "Baixar vídeo" (ao lado); sem "Marcar como exportado"
  assert.match(html, /<div class="fd-bar" role="region" aria-label="Ações do vídeo">/);
  assert.match(html, /<button type="button" class="fd-btn fd-approve"[^>]*>.*Aprovar vídeo<\/button>/);
  assert.match(html, /class="fd-btn fd-secondary" href="\/media\/prod_1\/delivery\/final\.mp4\?download=1" download=""/);
  assert.ok(!/Marcar como exportado/.test(html) && !/Pedir ajuste/.test(html) && !/Aprovado<\/span>/.test(html), 'nada de exportado, nada de ajuste inventado, sem selo antes de aprovar');
  assert.ok(html.indexOf('fd-bar') > html.indexOf('Algo saiu errado'), 'a barra é o último bloco (gruda no fim da área)');
  // aprovado: selo "Aprovado", Baixar vídeo vira a ação principal e não há mais "Aprovar vídeo"
  const done = render(view(), mission(delivered({ status: 'completed' })));
  assert.match(done, /class="fd-approved" role="status">.*Aprovado<\/span>/);
  assert.match(done, /class="fd-btn fd-primary" href="\/media\/prod_1\/delivery\/final\.mp4\?download=1" download=""/);
  assert.ok(!/Aprovar vídeo/.test(done) && !/Marcar como exportado/.test(done));
  // faixa "Criar outro vídeo" (texto de appConfig) fica antes da barra, sem valor em reais
  const strip = render(view({ firstVideo: { text: 'Seu produto já tem um vídeo pronto para vender. Que tal dar o mesmo impulso ao próximo da sua loja?', cta: 'Criar outro vídeo' }, newProd: () => {} }), mission(delivered({ status: 'completed' })));
  assert.match(strip, /Seu produto já tem um vídeo pronto para vender\. Que tal dar o mesmo impulso ao próximo da sua loja\?/);
  assert.match(strip, />Criar outro vídeo<\/button>/);
  assert.ok(!/R\$|Ver pacotes|vendendo sozinho/.test(strip));
  assert.ok(strip.indexOf('pv-upsell') < strip.indexOf('fd-bar'));
  assert.match(html, /Pronto pra postar no TikTok Shop/); assert.match(html, /Copie e cole na hora de publicar/);
  assert.match(html, /Fone de Ouvido Azul Marinho/); assert.match(html, /27 caracteres/); assert.match(html, /Copiar título/);
  assert.match(html, /<li>#FoneDeOuvido<\/li><li>#TikTokAchados<\/li>/);
  assert.match(html, /68 caracteres com hashtags/); assert.match(html, /Copiar legenda/);
  assert.ok(!/Descubra o conforto! Clica no carrinho\. #Fone/.test(html), 'a legenda exibida não repete as hashtags (elas viram chips)');
  assert.match(html, /alt="Foto do produto gerada"/); assert.match(html, /9:16, boa para capa ou anúncio/); assert.match(html, /Baixar foto/);
  assert.match(html, /Quer testar outra versão\?/); assert.match(html, /Mesma foto e produto\. Cada vídeo usa 20 créditos\./);
  assert.match(html, /<button type="button" class="fd-btn"[^>]*>Outra plataforma<\/button>/); assert.match(html, />Outro cenário<\/button>/);
  assert.match(html, /Algo saiu errado\?\s*<a href="https:\/\/wa\.me\/5511999999999"[^>]*>Reportar problema<\/a>\. Se for erro técnico, os créditos voltam\./);
  assert.ok(!/Compartilhar/.test(html), 'sem suporte a compartilhar arquivo, o botão nem aparece (nada de link de /media)');
  // acessibilidade: todo botão é <button type="button"> ou link real; nenhum div clicável
  assert.ok(!/<div[^>]*onClick|role="button"/.test(html));
  assert.equal(count(html, /<img/g), count(html, /<img[^>]*alt="/g), 'toda imagem tem alt');

  // ---- narração: só aparece com texto; com texto mostra "{s} s · {n} palavras"
  assert.ok(!/Narração/.test(html), 'sem narration_text, o card de narração não aparece');
  P = delivered({ fal: { ...delivered().fal, narration: { text: 'Procurando um fone confortável? Clica no carrinho e garante o seu!', seconds: 12.4, words: 10 } } });
  html = render(view(), mission(P));
  assert.match(html, /Narração/); assert.match(html, /12 s · 10 palavras/); assert.match(html, /“Procurando um fone confortável\? Clica no carrinho e garante o seu!”/);
  P = delivered({ fal: { ...delivered().fal, narration: { text: '   ', seconds: 3 } } });
  assert.ok(!/Narração/.test(render(view(), mission(P))), 'texto em branco = sem card');

  // ---- sem foto / sem título: cards somem em vez de aparecer vazios; texto faltando vira aviso
  P = delivered({ fal: { ...delivered().fal, image: { role: 'hero', url: null }, title: '', caption: '' } });
  html = render(view(), mission(P));
  assert.ok(!/Foto do produto/.test(html) && !/Copiar título/.test(html));
  assert.match(html, /O vídeo veio sem título e legenda/);
  // sem suporte configurado, "Reportar problema" vira texto (sem link)
  html = render(view(), mission(delivered(), { support: null }));
  assert.match(html, /<strong>Reportar problema<\/strong>/);
  html = render(view(), mission(delivered(), { support: { whatsapp: null, email: 'ajuda@x.com' } }));
  assert.match(html, /href="mailto:ajuda@x\.com\?subject=/);
  // demo (créditos fixos = 0): a frase não inventa preço
  assert.match(render(view(), mission(delivered(), { variantCredits: '0' })), /Mesma foto e produto\.<\/span>/);

  // ---- em andamento: esteira grande, status e "Cancelar missão"; nada de banner de pronto nem card de saldo
  const running = { id: 'prod_2', engine: 'fal', status: 'producing', ended: null, running: true, scene: 'natural', platform: 'tiktok_shop', credits: { spent: 0 },
    delivery: {}, fal: { stage: 'submitted', remote_status: 'IN_PROGRESS', submitted_at: new Date(Date.now() - 20000).toISOString(), scene_label: 'Natural', platform_label: 'TikTok Shop' } };
  html = render(view({ canCancel: true }), mission(running, { gallery: null }));
  assert.match(html, />Cancelar missão<\/button>/);
  assert.match(html, /pv-station/); assert.match(html, /role="status"/);
  assert.ok(!/Seu vídeo está pronto/.test(html) && !/Saldo/.test(html) && !/fd-belt/.test(html));
  // missão falhada: o status aparece e o cancelar some
  const failed = { ...running, status: 'failed', ended: 'failed', running: false };
  html = render(view({ canCancel: false, ended: 'failed' }), mission(failed, { gallery: null }));
  assert.ok(!/Cancelar missão/.test(html)); assert.match(html, /Não deu certo/);
  // concluída, mas a entrega ainda não tem vídeo: nunca mostra o resultado vazio
  html = render(view(), mission(delivered({ delivery: {} }), { gallery: gallery(delivered({ delivery: {} })) }));
  assert.ok(!/Seu vídeo está pronto/.test(html));

  // ---- falStations não muda: continua a fonte da esteira grande
  assert.equal(falStations(delivered()).allDone, true);
  console.log('falmission-render ok');
} finally {
  await vite.close();
}
