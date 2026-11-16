// Escritório (Fase 2 do novo layout): lógica pura da tela (selos, painel do agente, escolha, balão do E e regra das teclas).
import assert from 'node:assert/strict';
import { agentState, teamLine, officeStatus, agentPanel, pickAgent, nearPrompt, officeKeys, officeHint } from '../src/shell/office.js';
import { kirooLook, KIROO_LOOKS } from '../src/ui/avatar.js';

const beto = { id: 'beto', name: 'Beto', role: 'Edição', look: { shirt: '#000' } };
const nina = { id: 'nina', name: 'Nina', role: 'Preparação', look: { shirt: '#111' } };

// estado do agente → palavra e tom (desconhecido vira Livre)
assert.deepEqual(agentState('need'), { word: 'Precisa de você', tone: 'need' });
assert.deepEqual(agentState('work'), { word: 'Trabalhando', tone: 'work' });
assert.deepEqual(agentState('idle'), { word: 'Livre', tone: 'free' });
assert.deepEqual(agentState('???'), { word: 'Livre', tone: 'free' });

// linha da faixa da equipe, como no design: "Preparação · livre"; quem precisa de você mostra só isso
assert.equal(teamLine(nina, 'idle'), 'Preparação · livre');
assert.equal(teamLine(nina, 'work'), 'Preparação · trabalhando');
assert.equal(teamLine(beto, 'need'), 'Precisa de você');

// selos do alto do mapa
assert.deepEqual(officeStatus({ statuses: { nina: 'idle', beto: 'idle' } }).team, { tone: 'free', title: 'Equipe livre', text: 'nenhuma produção em andamento' });
assert.equal(officeStatus({ statuses: { nina: 'work' } }).team.title, '1 agente trabalhando');
assert.equal(officeStatus({ statuses: { nina: 'work', beto: 'work' }, live: true }).team.title, '2 agentes trabalhando');
assert.equal(officeStatus({ statuses: { nina: 'work' }, live: true }).team.text, 'produção gerando agora');
assert.equal(officeStatus({ statuses: {}, live: true }).team.title, 'Produção gerando');
assert.equal(officeStatus({ waiting: 0 }).need, '');
assert.equal(officeStatus({ waiting: 1 }).need, '1 vídeo espera você');
assert.equal(officeStatus({ waiting: 6 }).need, '6 vídeos esperam você');
assert.doesNotThrow(() => officeStatus());

// painel do agente: o que faz agora (status da sala), produção atual, ação principal
const room = { agent: 'beto', status: 'Precisa de aprovação', hint: 'Timeline, montagem e áudio' };
const pn = agentPanel({ agent: beto, status: 'need', room, hasProd: true, prodName: 'Skate Completo' });
assert.equal(pn.word, 'Precisa de você');
assert.equal(pn.doing, 'Precisa de aprovação');
assert.equal(pn.about, 'Timeline, montagem e áudio');
assert.equal(pn.production, 'Skate Completo');
assert.equal(pn.canOpen, true);
assert.equal(pn.primary, 'Resolver agora');
assert.equal(agentPanel({ agent: beto, status: 'work', room, hasProd: true, prodName: '' }).production, 'Produção atual');
assert.equal(agentPanel({ agent: beto, status: 'work', room, hasProd: true }).primary, 'Abrir produção');
// sem produção: nada de "abrir produção", e o texto não inventa tarefa
const free = agentPanel({ agent: nina, status: 'idle', room: null, hasProd: false });
assert.equal(free.canOpen, false);
assert.equal(free.production, '');
assert.equal(free.doing, 'Nenhuma produção aberta');
assert.equal(agentPanel({ agent: null }), null);

// quem o painel mostra: a escolha; a gaveta do celular cai em quem precisa de você; desktop sem escolha = sem painel
const team = [nina, beto];
assert.equal(pickAgent(team, {}, 'nina'), 'nina');
assert.equal(pickAgent(team, {}, 'fantasma'), null);
assert.equal(pickAgent(team, { beto: 'need' }, null), null);
assert.equal(pickAgent(team, { beto: 'need' }, null, true), 'beto');
assert.equal(pickAgent(team, {}, null, true), null);

// balão "E · Falar com X"
assert.deepEqual(nearPrompt('Falar com Beto'), { key: 'E', label: 'Falar com Beto' });
assert.equal(nearPrompt(''), null);

// teclas só com o escritório focado
assert.equal(officeKeys({ view: 'escritorio', inMap: true }), true);
assert.equal(officeKeys({ view: 'escritorio', isRoot: true }), true);
assert.equal(officeKeys({ view: 'central', inMap: true }), false, 'fora do Escritório');
assert.equal(officeKeys({ view: 'escritorio', tag: 'BUTTON' }), false, 'botão do menu lateral não anda o boneco');
assert.equal(officeKeys({ view: 'escritorio', tag: 'INPUT', inMap: true }), false, 'campo de texto');
assert.equal(officeKeys({ view: 'escritorio', tag: 'textarea', isRoot: true }), false);
assert.equal(officeKeys({ view: 'escritorio', editable: true, inMap: true }), false);
assert.equal(officeKeys({ view: 'escritorio', inDialog: true, inMap: true }), false, 'diálogo ou menu aberto');
assert.equal(officeKeys(), false);

// dica do rodapé
assert.match(officeHint(false), /setas ou WASD/);
assert.equal(officeHint(true), 'Toque numa mesa para andar');

// o boneco "Você" é o kiroo do avatar da conta (e cai no padrão sem id)
assert.deepEqual(kirooLook({ avatar_kiroo: 'k07' }), KIROO_LOOKS.k07);
assert.deepEqual(kirooLook(null), KIROO_LOOKS.k01);

console.log('office ok');
