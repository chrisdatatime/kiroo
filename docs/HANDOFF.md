# HANDOFF — migração visual do Pivoo (SPEC-VIS-001)

## Estado atual
Fase 1 entregue (pipeline + sala de Edição só com tiles do LimeZu).
**Fase 2 entregue (2026-11-04), aguardando validação do Chris:** o `office.tmj` roda no Phaser 3 dentro do Pivoo, atrás
de uma feature flag com **padrão `canvas`** (renderizador antigo intacto, nada DEPRECATED foi apagado).
Escopo aprovado (opção A): **só integração**. A estrutura da sede inteira entrou na Fase 2b-1 (abaixo); mobília é a 2b-2.
`npm run build` ✓ · `node tests/map.test.mjs` ✓ · `node tests/tmj.test.mjs` ✓ (novo).
Spec completa: [SPEC-VIS-001.md](SPEC-VIS-001.md).
**Personagem (2026-11-04):** nome desenhado no Phaser, preso ao sprite (antes era HTML e desencontrava ao andar); `TICK=200` e
agentes a `5*TICK` por tile (`v.agentDur`); textura do sprite em NEAREST. Os sprites definitivos virão do **Character Generator 2.0** (fase futura);
os de `characters.js` (20x26 por código) são provisórios.

## Assentos nos móveis de sentar (2026-11-04)
`tiles.yaml`: `sofa_*`, `armchair_blue` e `puff_*` têm `seat: {at: [[dx,dy],...], face, kind, back}`; `build_map.py` emite um objeto `seat` por lugar
(o objeto da sala pode filtrar com `seats: [índices]`; a sala do assento pode ser trocada com `room:`; `kind: mine` = cadeira da cabine).
`back` = linhas acima do assento que também contam no clique (sofá 1, puff/poltrona 0). Sofá de 3 = 2 lugares (pontas), namoradeira = 2.
Novos: cadeira de visita em Vídeos (spot [7,6] virou [3,6]: o bolsão (8,6) ficou isolado) e cadeira na cabine (`chair_swivel` visível em `rooms/patio.yaml`, assento kind `mine`, face right).
Entrada: só o lugar da direita do sofá (o da esquerda não tem saída livre). `tmj.test.mjs` confere: todo assento alcançável do spawn e com tile livre alcançável ao lado.

## Fase 2b-3b — atlas do Interiors + Entrada, Jogos e Pátio (2026-11-04)
**Atlas:** `build_map.py` gera `assets/tilesets/interiors_atlas.png` (fora do git, 512 px de largura) só com os tiles do Interiors usados
(hoje 49), em ordem do GID de origem; os GIDs viram `26685+` e o tileset `Interiors_32x32` sai do `.tmj`/`.tmx`. Idempotente (md5 igual em 2 builds).
`WorldPhaser.jsx` carrega o atlas pelo glob (o PNG gigante continua excluído); o aviso de limite de textura só dispara se algum tileset passar dele.
`tileset_common.py` ganhou `register_atlas()` (o atlas entra em `TILESETS` quando o arquivo existe; `preview.py` o lê).
`tmj.test.mjs` ✓ · `map.test.mjs` ✓ · `npm run build` ✓ · nenhum retângulo livre de 3×3 em nenhuma sala (conferido por script no `.tmj`).

| Sala | Identidade |
|---|---|
| Entrada (`rooms/entrada.yaml`) | sofá azul + poltrona + quadro (esquerda), quadro de avisos e poster (direita), balcão de recepção (mesa lavanda com monitor/telefone/luminária), plantas. Spawn (5,3) livre |
| Jogos e lazer (`rooms/jogos.yaml`) | descanso: 2 sofás e TV na parede norte, mesa de pingue-pongue azul, 3 puffs, planta; porta a leste |
| Pátio (`rooms/patio.yaml`) | copa (balcão + cafeteira, geladeira, bebedouro), mesa redonda, sofá, 2 namoradeiras nas laterais, plantas nas bordas. Cabine, linha acima dela e anel de trilha livres |

Peças novas (`tiles.yaml`, `set: interiors`, faixa 341-365 e 280-282): `sofa_blue/gray/brown/lilac`, `armchair_blue`, `table_round_light/orange`, `pingpong_blue`,
`puff_blue/yellow/red`, `tv_wall`, `fridge`, `coffee_maker`. Os retângulos foram conferidos numa folha das peças antes de usar.
**Desvios / a confirmar:**
1. A pasta `Theme_Sorter_32x32` não estava em `pivoo-assets-ref/`: achei em `Downloads/moderninteriors-win/1_Interiors/32x32/`. O `Interiors_32x32.png` do projeto **não segue a ordem do Theme_Sorter** (ex.: Basement está na linha 341, Cozinha na 257, Pesca na 123), então localizei por correspondência de tiles. Não usei as imagens do Theme_Sorter, só o catálogo ampliado.
2. **Não existe peça de balcão de recepção nem de quadro de cortiça**: usei a mesa lavanda comprida e o quadro branco com gráfico. Se quiser peças de verdade, preciso que você aponte ou eu procuro no Grocery/Classroom.
3. Sofás do Interiors só existem **de frente** (encosto ao norte): por isso ficam encostados na parede norte e a TV fica na mesma parede; não há sofá virado para a TV. Também não existe sofá de costas.
4. Mesas redondas e pingue-pongue têm largura visual de 1,5 e 2 tiles dentro de um retângulo de 3 (as bordas são só sombra/borda); a colisão cobre os 3 tiles.
5. Spots do pátio mudaram (os de baixo foram para `rooms/patio.yaml`, linha livre abaixo da cabine); a entrada do pátio é (22,17).
6. `sofa_brown`/`sofa_lilac` são namoradeiras 2×2 (a peça de 3 na planilha na verdade tem a terceira coluna de outro móvel).

## Fase 2b-3a — salas dos agentes mobiliadas (2026-11-04)
Um `tools/rooms/<id>.yaml` por sala (célula do `layout.yaml` com `room_file`), só `modern_office` + `room_builder_office`.
Personagens e HUD intactos. `build_map.py` idempotente (`cmp`), `tmj.test.mjs` ✓ (agentes alcançam as cadeiras), `map.test.mjs` ✓.
Maior chão livre por sala: nenhum retângulo com lado ≥ 3 (só corredores de 2 de largura); preview: `tools/preview.py --zoom 1`.

| Sala | Identidade |
|---|---|
| Planejamento (Nina) | mesa lavanda + mesa de reunião 5×3, 2 quadros brancos, cadeira de visita na ponta |
| Direção criativa (Theo) | mesa grande cinza-escuro 5×3, sofá, estante, quadro grande, diploma e retratos |
| Imagens (Iris) | 2 estações bege, impressora e plantas no vão da porta, quadro colorido |
| Vídeos (Lia) | estúdio: 2 racks, rig de câmera + softbox + monitores, mesa com tela tripla |
| Revisão (Rui) | 2 estações, quadros brancos, bebedouro, planta; porta ao norte |

Peças novas em `tiles.yaml` (todas `modern_office`): `desk_light/dark/lav`, `table_lav_long`, `table_dark_long`, `art_pop`, `frame_mini`,
`frame_face_a/b`, `certificate_a/b`, `sofa_dark`, `rack_a/b`, `studio_rig`, `monitor_triple`. **Nenhuma peça faltou.**
Notas: salas de 8 de altura têm só 4 fileiras de piso, então as mesas ficam sobre a base da parede (linha 1) e a cadeira nas linhas 4-5;
só há cadeira de frente (pendência 2 da Fase 2); a mesa de reunião tem 1 assento (outros cortariam o corredor); Vídeos usa 1 estação (o estúdio ocupa o resto).

## Fase 2b-2 — escala e identidade visual (2026-11-04, sem mobília nas outras salas)
Mapa **38×32** (era 53×33), salas menores, pisos coloridos, paredes com face de 2 tiles, câmera 1× em telas largas.
`npm run build` ✓ · `node tests/tmj.test.mjs` ✓ (inclui escala e `pickZoom`) · `node tests/map.test.mjs` ✓. Preview: `tools/out/preview.png`
(`tools/preview.py --zoom 1`, mapa inteiro, 1216×1024).

| Célula | Tamanho externo | Piso | Porta |
|---|---|---|---|
| Planejamento · Imagens | 10×8 | verde-acinzentado · menta | sul |
| Direção criativa | 12×8 | azul claro | sul |
| Vídeos · Jogos | 10×9 | rosa-vermelho · verde claro | oeste · leste |
| Edição | 10×9 (`rooms/edicao.yaml`, 2 estações, estante, planta, quadros) | areia | **oeste** |
| Entrada · Revisão | 10×9 · 12×9 | bege · laranja | norte |
| Pátio | 12×9 aberto, cabine com 2 divisórias (8×3) | madeira bege | — |

Corredores de 3 tiles em madeira bege clara (GID 2818, `floors.madeira`); trilha amarela viva (2210) no anel ao redor do pátio.
**Paredes:** horizontais (norte e sul) agora têm a face de 2 tiles (`F` topo+face, `B` face baixa), com vão de porta de 2 tiles
(as pontas viram batentes sozinhas); laterais continuam as peças finas `L`/`R`. O retângulo da célula é o externo (parede incluída).
**Câmera:** `game/phaser/zoom.js` — zoom 1 com ≥ 1280 px CSS de largura, 2 abaixo; inteiro em pixels do dispositivo (× DPR, arredondado para baixo).

**Desvios do pedido (decisões a confirmar):**
1. Salas de agente **10×8**, não 10×7: com 2 tiles de face em cima e embaixo, 10×7 deixaria só 3 fileiras de piso. As de baixo e
   Vídeos/Jogos têm 9. O mapa ficou 38×32 (pedido ~40×27: o ganho vertical não fecha com 3 linhas de salas + corredores de 3).
2. **Pisos vêm do `room_builder` (Interiors), não do `room_builder_office`**: o office só tem cinza, ocre e vinho, sem madeira
   bege nem carpete colorido. O Interiors continua fora do atlas (só ~2,4k px de largura, cabe na textura).
3. A porta da Edição passou para o **oeste** (sem corredor sul); a cadeira da fileira de baixo exige 5 fileiras de piso.
4. **Janelas: não existem peças** de janela em `modern_office`, `room_builder_office` nem nas faixas conferidas do `room_builder`; ficaram de fora.
5. Laterais com face de 2 tiles não existem no tileset (só linha fina); porta = vão com batentes nas paredes horizontais e vão nas laterais.

## Fase 2b-1 — estrutura da sede (53×33, substituída pela 2b-2 acima) (2026-11-04, sem mobília)
O `office.tmj` agora é a sede inteira: **53×33 tiles**, "anel de produção" (grade 3×3 de células + corredores de 2 tiles).
Fonte: `tools/layout.yaml` (células, portas, corredores, trilha, spawn, spots). `build_map.py` lê o layout, gera as salas
novas (parede com face frontal, porta, chão, colisão) e usa `rooms/edicao.yaml` para a Edição (idêntica, só transladada).
Idempotente (conferido com `cmp`).

| Célula | Sala (id) | Agente | Tamanho | Porta |
|---|---|---|---|---|
| A1 | Planejamento (`planejamento`) · sala 1 | nina | 14×8 | sul |
| B1 | Direção criativa (`direcao`) · 2 | theo | 18×8 | sul |
| C1 | Imagens (`imagens`) · 3 | iris | 17×8 | sul |
| C2 | Vídeos (`videos`) · 4 | lia | 17×11 | oeste |
| C3 | Edição (`edicao`) · 5 | beto | 14×8 na célula 17×8 | sul |
| B3 | Revisão (`revisao`) · 6 | rui | 18×8 | norte |
| A3 | Entrada (`entrada`): spawn + recepção | — | 14×8 | norte |
| A2 | Jogos e lazer (`jogos`) | — | 14×11 | leste |
| B2 | Pátio (`patio`), sem paredes; cabine `meu` (Meu escritório, 12×4) no meio | — | 18×11 | aberto |

- **Trilha:** anel de 2 tiles nos corredores ao redor do pátio, com o piso claro de tábuas do `room_builder_office`
  (GID 26571, `floors.trilha` em `tiles.yaml`). Não havia peça "luminosa" dedicada; é a mais clara que existe.
- **Cabine:** 3 `glass_divider` (4×3) na frente, colisão só na fileira de baixo (12 tiles). Sem laterais nem fundo ainda (2b-2).
- **Objects:** um `room` por célula (+ `meu`), `spawn` na Entrada, `spot` no pátio, nos corredores (13) e na Edição (3), `entry` em cada sala.
  O spawn saiu de `rooms/edicao.yaml` (o jogo começa na Entrada).
- **Desvios do pedido (decisão a confirmar):** (1) mapa 53×33, não 52×31: a porta da Edição é **ao sul** (sala idêntica à atual),
  então existe uma faixa de corredor de 2 tiles sob ela (`y 31–32`, só sob a Edição). (2) A célula C3 tem 17 de largura mas a
  Edição tem 14: as 3 colunas da direita ficam **vazias** (sem chão, bloqueadas, não aparecem).
- **Jogos e lazer, Entrada e Pátio** não existem em `map.js`: entram como salas novas (sem agente) e aparecem em Setores.
- **Testes:** `tests/tmj.test.mjs` confere salas colocadas, agentes certos, entrada de toda sala alcançável do spawn, sem tile isolado
  nas salas vazias e spawn na Entrada. Com `?world=phaser`, "Ir à sala" das 10 salas leva até elas e o aviso de "sala fora do mapa" sumiu.
- **Preview:** `tools/preview.py --zoom 0.5` (agora aceita fração) → mapa inteiro. Dois pontos que dá para melhorar na 2b-2: a trilha
  é cinza-claro, pouco "luminosa", e a cabine é só a fachada de vidro.
- Usava só `room_builder_office` e `modern_office` (o Interiors entrou na 2b-3b, via atlas).

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
1. ~~`Interiors_32x32.png` passa do limite de textura WebGL~~ — resolvido na 2b-3b (atlas gerado pelo `build_map.py`).
2. A cadeira do tileset é vista de frente: sentado "trabalhando" o personagem fica de costas (face up) na frente do encosto.
   Funciona, mas a leitura é estranha. Mesma pendência 2 da Fase 1 (não existe giratória de costas).
3. Com a sede inteira (53×33 = 1696×1056 px) a câmera rola de verdade em telas pequenas; conferir à mão o zoom e as bordas.
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
- **2b-3 (feito):** todas as salas mobiliadas (a cabine "Meu escritório" segue só com a fachada de vidro: laterais, fundo e mobília são a próxima).
- Objetos de interação que faltam: `interact` com `action` board/coffee/games/music/mine (o `tmjWorld` precisa preencher `INTERACT`).
- Depois de validado: virar o padrão da flag e apagar `renderer.js`, `furniture.js`, `draw.js` (o que só serve a cenário) e `map.js`
  (os metadados das salas — nome, dica, agente — precisam ir para outro lugar antes).

## Pipeline (`tools/`)
| Arquivo | O que faz |
|---|---|
| `tileset_common.py` | tilesets, GID ↔ (coluna, linha), recorte de tile, fundo xadrez, fonte |
| `make_catalog.py` | `--contact` = visão geral; sem ela = catálogo ampliado com o GID escrito (`--rows`, `--cols`, `--zoom`) |
| `tiles.yaml` | vocabulário: pisos, tabela explícita de parede, objetos com `cells`/`collision`/`layer` |
| `layout.yaml` | a sede: mapa, células (posição, tamanho, porta), corredores, trilha, spawn, spots |
| `rooms/edicao.yaml` | a sala 14×8 em texto: grade de caracteres + lista de objetos (origem vem do layout) |
| `build_map.py` | `layout.yaml` + salas → `assets/maps/office.tmj` e `.tmx` + `assets/tilesets/interiors_atlas.png`; colisão em retângulos; idempotente |
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
