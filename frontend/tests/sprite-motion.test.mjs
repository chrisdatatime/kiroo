import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import * as sprites from '../src/game/phaser/sprites.js';
import * as zoom from '../src/game/phaser/zoom.js';

// Executa os métodos reais da cena com objetos Phaser mínimos para verificar
// transições e tempo de animação sem inicializar WebGL/DOM.
const source = readFileSync(new URL('../src/game/phaser/OfficeScene.js', import.meta.url), 'utf8')
  .split('// Sobe o jogo')[0]
  .replace(/^import .*;\r?$/gm, '').replace(/^export .*;\r?$/gm, '');
const context = vm.createContext({ ...sprites, ...zoom, Phaser: { Scene: class {} }, window: { devicePixelRatio: 1 } });
vm.runInContext(source + '\n globalThis.OfficeScene = OfficeScene;', context);
const scene = new context.OfficeScene({});
const image = { texture: { key: 'sheet' } };
for (const method of ['setCrop', 'setFrame', 'setOrigin', 'setScale', 'setPosition', 'setVisible', 'setDepth']) {
  image[method] = (...args) => { image[method + 'Args'] = args; return image; };
}
const tag = { setScale: () => tag, setPosition: () => tag, setVisible: () => tag };
scene.cameras = { main: { zoom: 1 } }; scene.T = 32;
const agent = { sheet: 'sheet', img: image, tag: { box: tag }, x: 100, y: 100,
  dir: 'left', dist: 16, walking: true, seated: true, work: true, anim: 'type', foot: 104 };
scene.drawKiroo(agent, 1);
assert.equal(Math.floor(image.setFrameArgs[0] / 16), 6, 'caminhar (esquerda) tem prioridade sobre trabalho/sentado');
agent.walking = false; agent.seated = false; agent.dir = 'down';
scene.drawKiroo(agent, 0); assert.equal(image.setFrameArgs[0], 320);
scene.drawKiroo(agent, 0.1); assert.equal(image.setFrameArgs[0], 320, 'trabalho a 8 fps');
scene.drawKiroo(agent, 0.13); assert.equal(image.setFrameArgs[0], 321);
agent.work = false; agent.anim = 'idle';
scene.drawKiroo(agent, 0); assert.equal(image.setFrameArgs[0], 0);
scene.drawKiroo(agent, 0.21); assert.equal(image.setFrameArgs[0], 1, 'espera a 5 fps');

Object.assign(agent, { init: true, from: [100, 100], to: [132, 100], t0: 0, dur: 1,
  x: 100, y: 100, moveDir: 'right', anim: 'walk', idleSince: 0 });
scene.v = {}; scene.t0 = 0; scene.chars = new Map([['nina', agent]]);
scene.drawChar = () => {}; scene.drawFx = () => {};
scene.update(500); assert.equal(agent.dir, 'right'); assert.equal(agent.x, 116);
scene.update(1000); assert.equal(agent.x, 132);
scene.update(1100); assert.equal(agent.walking, false, 'para ao chegar, mesmo com view-model ainda marcando walk');
assert.equal(agent.dir, 'right', 'sem inversão de direção ao terminar o passo');
console.log('movimento e animação: transições e cadência corretas');
