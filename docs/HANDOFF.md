# HANDOFF — migração visual do Pivoo (SPEC-VIS-001)

## Estado atual
Fase 1 entregue (pipeline + sala de Edição só com tiles do LimeZu).
**Fase 2 entregue (2026-11-04), aguardando validação do Chris:** o `office.tmj` roda no Phaser 3 dentro do Pivoo, atrás
de uma feature flag com **padrão `canvas`** (renderizador antigo intacto, nada DEPRECATED foi apagado).
Escopo aprovado (opção A): **só integração**; só a Edição/Beto está no mapa novo. As outras 6 salas ficam para a Fase 2b.
`npm run build` ✓ · `node tests/map.test.mjs` ✓ · `node tests/tmj.test.mjs` ✓ (novo).
Spec completa: [SPEC-VIS-001.md](SPEC-VIS-001.md).

## Fase 2 — o que foi feito
| Arquivo | O que faz |
|---|---|
| `frontend/src/game/worldFlag.js` | flag `canvas` (padrão) / `phaser`: `?world=phaser` na URL (fica salvo em `bc.world`) ou botão em Minha conta → Sobre e créditos |
| `frontend/src/game/world/tmjWorld.js` | `buildWorld(tmj, ROOMS)`: lê o `.tmj` e devolve `GRID/ROOMS/CHAIRS/INTERACT/BLOCKED/SPOTS/SPAWN` no formato do `map.js`. `usedTilesets()` |
| `frontend/src/game/data.js` | escolhe a fonte do mapa pela flag; agente sem sala no mapa fica com `seat: null` |
| `frontend/src/game/phaser/OfficeScene.js` | cena Phaser: camadas na ordem do mapa, y-sorting, personagens, câmera, destaque/destino |
| `frontend/src/ui/WorldPhaser.jsx` | monta o Phaser (chunk separado, ~1,5 MB / 343 kB gzip, só baixa com a flag ligada) + a mesma camada HTML de placas/nomes/cliques |
| `frontend/src/ui/About.jsx` | tela **Sobre e créditos** (crédito LimeZu + troca da flag); no login vira um "Sobre e créditos" expansível |
| `CREDITS.md` | "Tileset: Modern Interiors e Modern Office por LimeZu, https://limezu.itch.io/moderninteriors" |
| `frontend/tests/tmj.test.mjs` | ordem das camadas, spawn/spots/cadeiras/mesa alcançáveis, Edição ligada ao Beto, tilesets cabem numa textura |

Como funciona:
- **Render:** `pixelArt`, `roundPixels`, `antialias: false`. Canvas em pixels do dispositivo e zoom **inteiro** nesses pixels
  (`max(1, floor(altura / (14 × 32)))`), então não há escala quebrada nem blur, inclusive com DPR 1,25/1,5.
- **Camadas:** na ordem do `.tmj`. Camadas antes de `furniture_sorted` (chão, parede, móveis atrás) ficam com depth negativo;
  `furniture_sorted` vira um sprite por tile com `depth = y do pé do móvel`; personagens com `depth = y do pé`;
  `furniture_above` fica em depth 1e6 (sempre na frente). Sentado, o personagem fica na frente da própria cadeira.
- **Colisão:** retângulos de `collision` + todo tile sem chão (o vazio fora das salas). Movimento e BFS continuam no `App.jsx`
  (tile a tile, 130 ms); o Phaser só interpola, como o renderizador antigo.
- **Interação:** `objects` tem `room` (id, nome, agent, tab), `seat` (face, kind agent/visitor/free, monitor), `interact`
  (action=monitor), `entry`, `spawn` e `spot`. Na Edição: spawn (9,8), 3 spots, cadeira do Beto, cadeira de visita e uma livre.
- **Câmera:** segue o jogador com lerp 0,12, presa aos limites do mapa; a sede não encolhe. Mapa menor que a tela fica centralizado.
- **Salas fora do mapa novo** (`placed: false`): continuam no HUD, Setores, equipe e janelas. "Ir à sala" avisa que a sala
  ainda não está no mapa novo; "Abrir" funciona. Os agentes delas não aparecem no mundo.
- **Pipeline:** `tiles.yaml` ganhou `sort: true` (móvel em pé → camada de tile-objects `furniture_sorted`, com `foot`).
  A sala YAML ganhou `agent`, `tab`, `seats`, `monitor`, `entry`, `spawn`, `spots`. `build_map.py` continua idempotente
  (conferido com `cmp` em duas execuções); `preview.py` desenha `furniture_sorted` ordenado pelo pé.
- `vite.config.js`: `server.fs.allow: ['..']` (o mapa e os tilesets estão fora de `frontend/`). O glob dos tilesets
  exclui o Interiors (não vai para o `dist/`).

Validação visual (1 rodada, viewport 1024×768, conta DEMO local `fase2-teste@example.com` com a senha das fixtures
de `tests/`): sala inteira correta, Beto passeando entre os spots, destaque na cadeira mais próxima, sentar na cadeira C
(personagem na frente da cadeira, prompt "Levantar"), monitor abre a aba Entrega, "Ir à sala" de Planejamento avisa.
Corrigido depois da rodada (conferido só por DOM, sem nova rodada visual): clicar no encosto da cadeira (tile de cima)
agora conta como a cadeira (antes o jogador ia para trás dela); o aviso dos Setores citava "Ver trabalho" (o botão é "Abrir").

### Pendências da Fase 2
1. **`Interiors_32x32.png` (34.048 px de altura) passa do limite de textura WebGL** (normalmente 16.384, às vezes 8.192).
   Hoje não é usado, então não é carregado (`usedTilesets()` + checagem de `getMaxTextureSize()` na cena). **Fase 2b:
   o `build_map.py` deve gerar um atlas só com os tiles usados** e reescrever os GIDs no `.tmj`. Não implementado.
2. A cadeira do tileset é vista de frente: sentado "trabalhando" o personagem fica de costas (face up) na frente do encosto.
   Funciona, mas a leitura é estranha. Mesma pendência 2 da Fase 1 (não existe giratória de costas).
3. Em 1024×768 o mapa (30×20) é menor que a tela: fica centralizado, e o topo da sala fica sob o HUD. Com a sede inteira
   (Fase 2b) a câmera passa a rolar de verdade.
4. A cadeira fica a 2 tiles da mesa (mesa 3×3 + cadeira 1×2). Por isso o assento tem `monitor: true` no `.tmj`: sentado ali,
   E abre o monitor. A cadeira de visita (estação B) também abre o monitor da Edição.
5. Phaser é ~1,5 MB (343 kB gzip), num chunk separado que só carrega com a flag ligada e depois do login.
6. Animações das telas dos monitores e a luzinha de "precisa de você" na mesa (do renderizador antigo) não existem no Phaser:
   os monitores são tiles. O estado aparece no balão e na placa (HTML).
7. A validação visual roda só com o painel do navegador visível: oculto, o requestAnimationFrame pausa e o Phaser não desenha.

### O que testar à mão (flag ligada: `http://127.0.0.1:8765/?world=phaser`)
- [ ] Nitidez: sem blur em 100%, 125% e 150% de zoom do Windows (o zoom do jogo muda em degraus inteiros).
- [ ] Tela grande (≥ 900 px de altura): zoom 2, câmera seguindo com suavidade e parando nas bordas do mapa.
- [ ] Andar com WASD/setas segurando a tecla (sem picotar) e clicando no chão; não atravessar mesas, paredes nem o vão da porta.
- [ ] Passar atrás das mesas (fileira de cima) e na frente delas: a mesa cobre o personagem quando ele está atrás.
- [ ] Monitor, quadro, telefone e teclado (`furniture_above`) sempre por cima do personagem.
- [ ] Sentar nas 3 cadeiras (clique no assento e no encosto; e E) e levantar (E ou seta).
- [ ] E sentado na cadeira A ou B abre a aba Entrega; falar com o Beto (Ver trabalho, Conversar, Treinar, Trilhas).
- [ ] Produção em andamento: placa da Edição e balão do Beto mudam de estado (Montando, Precisa de aprovação).
- [ ] Setores: "Ir à sala" das 6 outras salas avisa; "Abrir" e a equipe no canto abrem cada etapa.
- [ ] Minha conta → Sobre e créditos: texto do LimeZu e o botão que troca o visual (recarrega a página).
- [ ] Tela de entrar → Sobre e créditos.
- [ ] `?world=canvas` (ou o botão): o jogo antigo idêntico ao de antes, com as 7 salas.

## Fase 2b — próximos passos
- Montar as outras 6 salas e a área comum em YAML (Planejamento/Nina, Direção/Theo, Imagens/Iris, Meu escritório,
  Vídeos/Lia, Revisão/Rui) e o corredor; cada sala nova aparece no jogo sozinha (salas, assentos, monitor, spots).
- Objetos de interação que faltam: `interact` com `action` board/coffee/games/music/mine (o `tmjWorld` precisa preencher `INTERACT`).
- Atlas de tiles usados (pendência 1).
- Depois de validado: virar o padrão da flag e apagar `renderer.js`, `furniture.js`, `draw.js` (o que só serve a cenário) e `map.js`
  (os metadados das salas — nome, dica, agente — precisam ir para outro lugar antes).

## Pipeline (`tools/`)
| Arquivo | O que faz |
|---|---|
| `tileset_common.py` | tilesets, GID ↔ (coluna, linha), recorte de tile, fundo xadrez, fonte |
| `make_catalog.py` | `--contact` = visão geral; sem ela = catálogo ampliado com o GID escrito (`--rows`, `--cols`, `--zoom`) |
| `tiles.yaml` | vocabulário: pisos, tabela explícita de parede, objetos com `cells`/`collision`/`layer` |
| `rooms/edicao.yaml` | a sala 12×8 em texto: grade de caracteres + lista de objetos |
| `build_map.py` | YAML → `assets/maps/office.tmj` e `.tmx`; colisão em retângulos; sala como objeto `room`; idempotente |
| `preview.py` | compõe as camadas em `tools/out/preview.png` (`--grid`, `--zoom`, `--crop`) |

```
.venv\Scripts\python tools/build_map.py
.venv\Scripts\python tools/preview.py --zoom 2 --crop 1,1,15,11
```

## Decisões tomadas
- `Room_Builder_32x32.png` e `Interiors_32x32.png`, mais `Modern_Office_32x32.png` e `Room_Builder_Office_32x32.png` (liberados depois). **Proibido** desenhar tile, móvel ou parede por código.
- Fonte da verdade do layout: `assets/maps/office.tmj` / `.tmx`, gerados do YAML — não editados à mão.
- Parede por **tabela explícita** (topo/face/base/lateral), sem autotile adivinhado. Papel lavanda em toda a sala.
- Piso com 1 variante só: 3 variantes deixavam o chão manchado.
- **Personagens continuam desenhados por código**: os arquivos liberados são cenário e móveis.
  `characters.js` e `Boneco.jsx` ficam; `renderer.js`, `furniture.js`, `draw.js` e `map.js` estão marcados
  `DEPRECATED` e só saem quando a Fase 2 for validada.
- Dependências: `pillow` + `ruamel.yaml` (PyYAML não tem wheel para Python 3.15 e falha ao compilar).
- `tools/out/` no `.gitignore`.
- GID: `room_builder = 1 + linha*76 + coluna` · `interiors = 8589 + linha*16 + coluna`.

## Tilesets de escritório (catalogados em 2026-11-04)
Registrados em `tileset_common.py` e `tiles.yaml` (decisão do Chris: agora liberados, além dos dois originais).
Catálogos: `tools/out/catalog_modern_office_*.png` e `catalog_room_builder_office_0000_c0.png`.

| Tileset | Grade | GIDs | Fórmula |
|---|---|---|---|
| `modern_office` (Modern_Office_32x32) | 16 × 53 | 25613–26460 | `25613 + linha*16 + coluna` |
| `room_builder_office` (Room_Builder_Office_32x32) | 16 × 14 | 26461–26684 | `26461 + linha*16 + coluna` |

Leitura dos catálogos (GID do canto superior esquerdo; peças de várias células, conferir no PNG antes de usar):
- **Mesas** em 4 acabamentos (bege-trama, bege, cinza-escuro, lavanda): 25629–25718; versões em L: 26157–26244 e 26253–26435.
- **Cadeiras**: poltronas cinza/laranja 25757–25794; cadeira giratória cinza/laranja 25761–25762, 25777–25778, 26165–26166.
- **Plantas** 25747, 25779, 25811, 25843; **quadros** 25764–25766, 25796–25797, 25821–25826.
- **Quadro branco** 25798–25799 (liso), 25830–25831 (gráfico), 25862–25863 (gráfico colorido).
- **Impressoras/copiadoras** 25926, 25957–25958, 25973–26023, 26252; **estante/arquivos** 25844–25845, 25997–26018 (racks/servidores).
- **Monitores e PCs** 25770–25836 (cols 12–15), setups completos 26037–26060, 26074–26092, 26103–26156; **luminárias** 25864, 25879, 25896, 25912.
- **Divisória de vidro** 26046–26067 · **sofás** 25885–25921 e 25934–25968 · **bebedouro/cadeira-bolsa** 26373–26426 (não identifiquei com certeza).
- **Room_Builder_Office**: paredes com face frontal em 4 papéis — lavanda 26541–26566, cinza-claro 26573–26598, tijolo-bege 26605–26630, lilás-claro 26637–26662; pisos nas colunas 8–15 das linhas 8–13 (26551–26572 cinza, 26583–26604 cinza-escuro/bege, 26615–26668 cinza/ocre/vinho). Linhas 0–3 são molduras de borda, não auto-tile fechado.

Isto resolveu a antiga pendência 5 (móvel de escritório de verdade) — veja a sala refeita abaixo.

## Sala Edição refeita com os tilesets de escritório (2026-11-04)
`tools/rooms/edicao.yaml` agora é **14×8** (era 12×8: 3 mesas de 3 tiles + estante de 2 + corredor não cabem em 12).
Só `room_builder_office` (chão e parede) e `modern_office` (móveis); nenhum tile do Interiors ficou na sala.
- `build_map.py` ganhou: objetos por `set` + `rect [coluna, linha, w, h]` (GID calculado, tile transparente ignorado),
  tabela explícita de parede com `walls.explicit` (L, R, S, `<`, `>`, `(`, `)`) e os 4 tilesets no `.tmj`/`.tmx`.
- `tiles.yaml`, seção `office`: `desk_office`, `chair_swivel`, `monitor_modern`, `keyboard`, `phone`, `desk_lamp`, `printer`,
  `whiteboard`, `whiteboard_chart`, `shelf`, `glass_divider`, `plant`, `plant_small`, `water_cooler`, `poster`, `frame_wide`.
  A seção `objects` (Interiors) ficou como legado, sem uso.
- Corrigido: 3 mesas de largura completa; faixa lateral própria; porta sul com batentes; sala cheia (maior vazio 2×2).
- Validação: 2 rodadas de preview. Rodada 1: ponta direita da parede norte saía como bloco branco → trocada por peça de meio.

### Pendências
1. Uma linha escura fina sobe na ponta direita da parede norte (peça `base.dir`, 26560); a rodada 2 foi a última permitida.
2. `chair_swivel` é a cadeira de encosto alto vista de frente (col 2, lin 8-9); não existe giratória de costas no tileset.
3. `glass_divider` está mapeada (col 0-3, lin 26-28) mas não foi usada: não achei lugar onde não atrapalhe as estações.
4. O chão fora das faixas laterais/sul aparece como piso (as peças de parede são finas). Decidir na Fase 2 se vira corredor.
5. Referências: só havia `Office_Design_1.gif` e `_2.gif` em `pivoo-assets-ref/` (a pasta `6_Office_Designs` não existe).

## Itens da antiga lista "Falta para a Fase 2"
Todos resolvidos na Fase 2 (acima). Decisão sobre a câmera: **a câmera segue o personagem; a sede não encolhe para caber
na tela.** Os personagens usam o sprite de `characters.js` em escala 2×.
