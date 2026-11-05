# HANDOFF — migração visual do Kiroo (SPEC-VIS-001)

> **2026-11-04 — reavaliação de produto:** diagnóstico, visão e plano em [VISAO_PRODUTO.md](VISAO_PRODUTO.md). Fase 0 entregue: shell com Central, Missão, Equipe e Escritório
> (`frontend/src/shell/`). Pendente: validar no seu navegador; `tests/minigames.test.mjs` segue falhando (já falhava antes).

## Arte licenciada fora do git: como chega ao deploy (2026-11-04)
Três pastas **não estão no git** (licença LimeZu) e entram no **build**, não no servidor:
`assets/characters/*.png` (folhas dos agentes e do jogador), `assets/tilesets/` (inclui `interiors_atlas.png`, gerado por `tools/build_map.py`) e
`frontend/src/assets/home/` (gerado por `tools/render_home.py`).
- As folhas entram no bundle por `import.meta.glob` (`ui/WorldPhaser.jsx`); os tilesets, pelo carregamento do `.tmj`. O servidor Python só serve
  `frontend/dist` (`GAME_DIST` em `web/server.py`). Então **a máquina que roda `npm run build` precisa ter as três pastas**. O servidor não precisa delas.
- Se faltarem, o build **não falha**: o mundo cai no feijão (`charSprite`) e a home fica sem imagens. Por isso o deploy tem de conferir antes do build.
  A partir da 7.1, `tools/check_avatars.py` valida `assets/characters/manifest.json` e falha com erro claro.
- Hoje não existe deploy (fase E do `ROADMAP_SAAS.md`). Regra para quando existir: as três pastas ficam num armazenamento privado (bucket ou
  artefato da CI com acesso restrito), são copiadas para o contexto do build antes de `npm run build` e **nunca** entram numa imagem pública nem no
  repositório. Hoje a única cópia está na máquina do Chris (origem: `Downloads\moderninteriors-win`), então vale ter um backup privado.

## Folhas Kiroo dos agentes (2026-11-04, 512×1536)
`assets/characters/{nina,theo,iris,rui,lia,beto}.png` = grade exata 16×48 de quadros 32×32 (corpo em y 3..29, pé em y=29). Carregadas como spritesheet normal (sem normalizador;
`spriteLayout.js` removido). 8 direções horárias S,SW,W,NW,N,NE,E,SE; usadas só as 4 cardeais. Linhas 0-3 = espera (8 quadros/direção), 4-11 = caminhada (16/direção, 1 ciclo = 2 tiles),
20 = prancheta de frente (usada como "trabalhando"). Mapeamento em `sprites.js` (`kirooFrame`). Não há guia oficial dessas folhas: o resto das linhas (corrida?, sono, "!", rindo, carregando) foi visto mas **não mapeado**; sentado de frente/costas e "precisa de você" ainda usam espera.

## Estado atual
Fase 1 entregue (pipeline + sala de Edição só com tiles do LimeZu).
**Fase 2 entregue (2026-11-04), aguardando validação do Chris:** o `office.tmj` roda no Phaser 3 dentro do Kiroo, atrás
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
1. A pasta `Theme_Sorter_32x32` não estava em `kiroo-assets-ref/`: achei em `Downloads/moderninteriors-win/1_Interiors/32x32/`. O `Interiors_32x32.png` do projeto **não segue a ordem do Theme_Sorter** (ex.: Basement está na linha 341, Cozinha na 257, Pesca na 123), então localizei por correspondência de tiles. Não usei as imagens do Theme_Sorter, só o catálogo ampliado.
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
5. Referências: só havia `Office_Design_1.gif` e `_2.gif` em `kiroo-assets-ref/` (a pasta `6_Office_Designs` não existe).

## Itens da antiga lista "Falta para a Fase 2"
Todos resolvidos na Fase 2 (acima). Decisão sobre a câmera: **a câmera segue o personagem; a sede não encolhe para caber
na tela.** Os personagens usam o sprite de `characters.js` em escala 2×.

## Fase 3 — personagens humanos do LimeZu no mundo Phaser (2026-11-04)
Só o renderer Phaser usa os sprites novos (`frontend/src/game/phaser/sprites.js`, `OfficeScene.drawHuman`). `characters.js`, `Boneco.jsx` e o
renderer canvas seguem intactos (HUD, fichas, retratos, "Meu escritório"). As folhas ficam em `assets/characters/` (**fora do git**, licença;
`/assets/characters/` no `.gitignore`); sem os PNGs o mundo cai no feijão (`charSprite`), então o clone limpo continua funcionando.
- **Folha**: 1792×1312, quadro **32×64** (não 32×32), 56 colunas, grade começa em (0,0); os 32 px finais da altura são vazios.
  Índices 0-based. Direções (idle/walk, 6 quadros cada): direita 0-5, cima 6-11, esquerda 12-17, baixo 18-23. Faixas: 1 idle, 2 walk,
  4 sit, 5 sit2 (pernas escondidas), 6 phone (0-2 início, 3-8 loop, 9-11 fim). `assets/characters/contact-sheet.png` documenta tudo (theo.png).
  O guia original está em `Downloads\moderninteriors-win\2_Characters\Character_Generator\Spritesheet_animations_GUIDE.png`.
- **Pé**: última linha opaca y=63 andando/parado, y=61 sentado; topo da cabeça em y=16 → origem (0.5, 1), nome 48 px acima do pé.
- **Ligação** agente → folha em `CHARACTER_SHEETS` (nina, theo, iris, rui, lia, beto); jogador → `voce`.
- **Poses**: andando = walk, quadro em função da **distância percorrida** (agentes 1 ciclo por tile, jogador 1 ciclo a cada 2 tiles; sem
  deslizar nem andar no lugar); parado = idle (4 fps); sentado/digitando = sit2 de lado (digitando anima, sentado fica no quadro 0);
  pedindo atenção = phone (início + loop); feliz = idle de frente com pulinho de 3 px; acenar = **não existe no guia**, usa phone (só o
  estado "need" chama acenar hoje). Origem nos pés, escala 1, NEAREST, depth = y do pé (sentado: `foot + 1`, na frente do móvel).
- **Sentado** (o guia só tem sit de lado; o Chris reprovou o lado em tudo e escolheu A no sofá, B na mesa): `seatMode(kind, face)` em
  `sprites.js`: assento `kind` agent/visitor (cadeira de mesa) = idle **de costas** rebaixado; os demais (sofá, puff, poltrona, cabine) =
  idle **de frente** rebaixado; assento com `face` left/right = sit de lado. Rebaixado = corpo alinhado pela última linha opaca do tile
  do assento (`rimOf`; o sofá tem ~8 px vazios embaixo), `SEAT.cut`=4 px de perna escondidos e a faixa de baixo do tile (`SEAT.cover`=8 px)
  redesenhada por cima do personagem. Sem tile do assento em `furniture_sorted`, cai no sit de lado. `kind` vem dos objetos `seat` do `.tmj`.
  Só validado a olho na cadeira (8,5) e no sofá (20,3) com um boneco de teste; puff, poltrona e cabine ainda não foram vistos neste modo.

### Pendências da Fase 3
1. O jogador no mundo usa `voce.png` fixo; "Meu escritório" ainda customiza só o feijão (look/cor). Ligar a escolha à folha fica para depois.
2. Agente `need` sentado continua sentado (sem phone); o aviso é só o "!" do balão. Phone é só para quem está em pé.
3. Sem animação de acenar; o guia tem outras poses (sleep, pick up, gift...) ainda não usadas.
4. `tests/minigames.test.mjs` recebe o módulo por argumento (`node tests/minigames.test.mjs ../src/game/minigames.js`); sem ele dá `ERR_MODULE_NOT_FOUND`.
5. 125%/150% de zoom conferidos por simulação do DPR (sem zoom real do navegador): zoom da câmera inteiro, sprite em escala 1,
   posição arredondada, nome com escala dpr/zoom.

## Fase 4 — UI clara do mundo Phaser (2026-11-04, sem commit)
Só vale com `?world=phaser` e a camada HTML dele (`frontend/src/ui/WorldPhaser.jsx`, `ui/world/`). Mapa, `tools/`, flag e renderer canvas não mudaram
(o canvas usa as mesmas classes `px-*`; o estilo novo é todo escopado em `.pw-root`).
- **Tokens (só claro)**: `--pw-*` em `styles.css` sobre `.pw-root` (camada do mundo) e `.pw-theme` (conteúdo em portal: HoverCard, Dialog,
  Tooltip). Fundo `#D7F3DC` (Phaser `backgroundColor` + câmera + container, sem faixa escura), superfície branca 94% + borda `#DCE3EE` +
  sombra suave, raio 12–16, primário índigo `#3B44E6`, texto `#1F2430`, secundário `#6B7280`, "precisa de você" = lima da marca com texto
  escuro e "!". `.pw-theme` também redefine `--primary`, `--ring`, `--popover`... para o shadcn usar o índigo. Espelho para o canvas do
  Phaser em `game/phaser/theme.js` (pill do nome: branca, borda sutil, texto escuro; jogador/perto: índigo com texto branco).
- **Zoom inteiro com tween** (`game/phaser/zoom.js`, `OfficeScene.zoomTo`): níveis 1x–4x em px CSS; o Phaser usa `floor(nível × DPR)`,
  sempre inteiro em px do dispositivo. Cada passo anima 150 ms (fracionário só durante o tween), trava no inteiro e arredonda o scroll
  (`snapScroll`). `prefers-reduced-motion` troca direto. Roda: `wheelAccumulator` (limiar 40 px, trava 200 ms por gesto) — um passo
  por notch e uma rajada de trackpad não pula níveis; zoom ancorado no cursor (`anchorScroll`). Botões à direita (+, nível, −,
  centralizar, automático) e teclas + / −. A escolha sobrescreve o `pickZoom` e fica em `localStorage` `bc.zoom` (try/catch;
  "automático" apaga). `pickZoom` não mudou (é `deviceZoom(pickLevel(w))`), então o `tmj.test` segue igual; `tests/zoom.test.mjs` cobre
  clamp, níveis inteiros em DPR 1/1,25/1,5/2, âncora, roda e armazenamento.
- **Câmera**: segue o jogador; zoom pela roda (no cursor) ou arrastar (botão do meio em qualquer ponto do mundo, ou esquerdo no chão,
  limiar 5 px; o clique que fecha o arraste não manda andar) soltam a câmera. "Centralizar" volta a seguir; se a câmera está solta e o
  jogador anda para fora da vista, ela volta a seguir sozinha. +/− pelos botões zoomam no centro.
- **Interação**: HoverCard (shadcn, 150 ms, fade+scale) nas placas de sala e nos agentes: nome, agente/função, estado, "Ir à sala" e
  "Abrir" (a janela da etapa, `openRoomWork`). Clique na placa abre `RoomDialog` (Dialog shadcn, lazy) com o detalhe e "Ir à sala" /
  "Abrir trabalho". Clique no agente continua sendo conversar. Placas levantam 2 px na tela com sombra no hover; "!" e balão de atenção
  pulsam (o balão só no brilho: o transform dele é a posição). `.pw-root` tem `pointer-events: none`; só `.px-world` e `.pw-zoom` recebem.
  Teclas dentro do card/dialog não chegam ao WASD do App (só Esc passa).
- **Performance**: zoom/câmera mudam o React só via `onView` quando nível/auto/solto mudam; hover é do próprio Radix (sem setState por
  movimento); a posição do card segue o gatilho com `updatePositionStrategy="always"` só enquanto aberto.
- **shadcn**: Tailwind v4 + shadcn (radix-nova, JSX) já estavam no working tree; nesta fase entraram `components/ui/hover-card.jsx` e
  `components/ui/dialog.jsx` (`npx shadcn add`; `package.json` não mudou, `radix-ui` já existia). Sem framer-motion (tw-animate-css basta).
  Popover e Command não foram adicionados (ainda não usados).
- `viewModel` ganhou `rooms[].agent/role` e `chars[].name/role/room` (só leitura, para os cards).

### Pendências da Fase 4
1. Painel lateral estilo Gather (pessoas online, busca, Ctrl+K "Ir à sala"): **aguardando aprovação**. O Shell já tem lateral e paleta Ctrl/⌘ K;
   decidir se o painel do mundo substitui ou complementa.
2. Hover é nas placas e nos agentes, não na área da sala (não há retângulo das salas no viewModel do Phaser).
3. O Dialog substitui só o clique da placa; a janela da etapa (`ProdWindow`) continua a antiga.
4. 125%/150% do Windows: o painel do navegador não emula DPR; coberto pelos testes de `zoom.js` (níveis inteiros e distintos por DPR).
5. `tests/minigames.test.mjs` precisa do caminho do módulo: `node tests/minigames.test.mjs ../src/game/minigames.js` (não é falha).

## Fase 4b — shell e modais modernizados (2026-11-04, sem commit)
Pedido do Chris: o sistema todo no padrão de layout de escritório virtual (trilho, painel, modais), sem copiar marca.
- **Shell** (`frontend/src/shell/Shell.jsx`, `shell.css`): saiu o `Sidebar` do shadcn. Trilho de ícones de 64 px (logo = menu escuro do estúdio com
  "Nova missão", Preferências, Piloto, Créditos, Sobre, Painel do admin, Sair; busca Ctrl K; Central/Missões/Agentes/Escritório; sino de Atividade;
  engrenagem), painel colapsável de 288 px (`bc.panel`; abaixo de 900 px vira sobreposto) com seletor de missão, card "Próxima ação", busca de
  agentes, equipe com avatar e ponto de estado, e conta no rodapé; a área de trabalho é um cartão branco arredondado. A paleta Ctrl K ganhou "Ir à sala".
- **Atividade**: Popover (`components/ui/popover.jsx`, novo) com `v.attn`; "lido" fica em `bc.seen` neste navegador (o item some só quando é resolvido).
- **Preferências** (`ui/Preferences.jsx`, lazy): Dialog com navegação à esquerda: Geral (modo de cor, visual da sede canvas/Phaser), Piloto, Minha conta,
  Créditos e extrato, Sobre. `openAccount/openPilot/openCredits/openAbout` continuam funcionando (abrem a aba certa); `v.openPrefs(tab)` é novo.
  `Account/Pilot/Credits/About.jsx` exportam só o conteúdo; as janelas soltas foram removidas.
- **Tokens**: shadcn `--primary` índigo `#3B44E6`, `--ring` índigo, texto `#1F2430`, bordas `#E3E7EE`. Classes `g-*` (HUD do jogo, janelas antigas)
  redesenhadas: superfície branca, borda 1 px, sombra suave, raio 10–16, fonte Geist; `.g-lime` virou o botão primário índigo. Cores inline das
  janelas antigas trocadas (bordas navy → `#D4DAE4`, creme/bege → `#F7F8FA`). Lima ficou só para "precisa de você".

### Pendências da Fase 4b
1. As janelas grandes (`ProdWindow`, Quadro, Setores, Treino, Trilhas, Jogos, diálogo com agente) ainda são `<section>` posicionadas, sem fundo
   escurecido nem foco preso; o visual já é o novo, mas o próximo passo é migrá-las para Dialog/Sheet do shadcn, uma por vez.
2. O mundo canvas (padrão) também pegou o HUD novo (`g-*`); o mapa em si não mudou.
3. Modo escuro: não existe (Preferências mostra "Claro").

## Hover do mapa Phaser (2026-11-04, sem commit)
- Tile sob o cursor: quatro cantos em L discretos no chão (`OfficeScene.drawHover`, depth 1, abaixo dos móveis), só onde dá para andar.
- Cadeira/assento livre, monitor da sala, Meu setup e objetos com interação: contorno branco de 2 px na tela + preenchimento branco 28% e
  um rótulo em pill com a ação ("Sentar aqui", "Levantar", "Usar o monitor: Revisão"...). Agentes ficam de fora (já têm hover card).
- `App.hoverAt(i, j)` decide (reaproveita `targetAtTile`, `highlightOf`, `labelFor`, `passP`); a cena guarda o ponteiro em px do canvas,
  recalcula o tile por frame só com a câmera e só redesenha quando tile, resultado ou zoom mudam. Nenhum setState: o cursor (pointer em
  alvo) é um `data-hover` no overlay. Placas escondem o destaque; o rótulo "Monitor" do DOM ficou oculto no Phaser (o Phaser mostra a ação).

## Fase 5 — kit de onboarding (2026-11-04, sem commit)
Tour guiado pós-login, igual nos dois renderizadores (canvas e `?world=phaser`). Mapa e `tools/` não mudaram.
- **Onde o estado fica**: no usuário, no servidor. `users.onboarding_done_at` (nulo = ainda não concluiu/pulou) e `users.onboarding_step`
  (índice em `STEPS`, para retomar), criados pela migração em `src/studio/accounts.py` (`Accounts.onboarding/set_onboarding`).
  `GET /api/me` devolve `user.onboarding = {done_at, step}`; `POST /api/onboarding` aceita `{step}` (onde parou), `{step, done: true}`
  (concluiu ou pulou) e `{done: false}` (reabre). Teste: `tests/test_accounts.py::test_onboarding_persists_per_user`.
  Reserva: se o `/api/me` não trouxer o campo ou o POST falhar, o App grava em `localStorage` (`bc.onb`). Usuários antigos também veem o kit uma vez.
- **Quando abre**: `App.maybeStartTour()` depois do login, se `done_at` é nulo (conta nova e conta DEMO inclusive), no passo salvo. O componente
  (`frontend/src/onboarding/Onboarding.jsx`) é `React.lazy` (chunk próprio de ~12 kB) e fica dentro de um error boundary (`TourBoundary`):
  se falhar, só o tour some. A dica antiga do escritório (`Tutorial` em `ui/Windows.jsx`) não aparece com o tour aberto e é dispensada quando ele termina.
- **Como reabrir**: "Rever tutorial" em Preferências → Geral (seção Ajuda), Minha conta, Sobre e créditos, menu do estúdio (logo) e Ctrl K
  (digite "rever"). Tudo chama `v.openTour()`, que recomeça do passo 1 sem mexer no `done_at`.
- **Comportamento**: passo 1 e conclusão são Dialog do shadcn (fade + scale); os demais são spotlight: máscara SVG com recorte arredondado
  (o Chromium não repinta máscara com x/y vindos de CSS, então o recorte anda por um tween curto em JS, `useCutTween`) e card com seta,
  posicionado por `placeCard` (lado preferido → outros lados → por dentro, no canto superior direito, no caso do mundo). Voltar, Próximo,
  Pular tutorial (com confirmação), "N de 8", Esc fecha e salva o passo, ← → navegam, foco preso no card, `aria-live` no título.
  Quatro bloqueadores em volta do recorte impedem clique fora do alvo; o alvo continua usável. No passo do escritório as teclas sobem até o
  Shell (dá para andar com WASD/setas com o tour aberto). Alvo ausente ou escondido (painel recolhido, tela estreita) → card centralizado.
  `prefers-reduced-motion` desliga as transições. Posição recalculada por ResizeObserver + resize/scroll num rAF, mais uma checagem a cada 500 ms.
- **Passo 6**: "Isento" é o botão de saldo do workspace (`credits_exempt`: consumo registrado, saldo não exigido; outros estúdios veem
  "N créditos") e o botão ao lado é o Piloto (Manual/Assistido/Automático). O texto do passo muda com a conta.
- **Como adicionar um passo**: inclua um objeto em `STEPS` (`frontend/src/onboarding/tour.js`; os campos estão documentados no topo do arquivo:
  `id`, `kind`, `targets`, `view`, `side`, `interactive`, `skip`, `title`, `body`) e marque o elemento real com `data-tour="<alvo>"`.
  Alvos atuais: `team`, `team-head`, `next-action`, `account` (painel), `new-mission`, `top-modes` (topo), `overview`, `needs-you` (Central),
  `office` (área do mundo), `office-rail` (trilho). O passo salvo é o índice em `STEPS`: ao inserir no meio, quem parou depois dele retoma um passo antes.
- **Testes**: `node frontend/tests/onboarding.test.mjs` (passo salvo/retomado, pular conclui, alvo ausente → centralizado, posição do card).
  Navegador (conta nova, servidor local): fluxo 1→8 + conclusão, fechar no passo 4 e retomar, Rever tutorial (Ctrl K, Conta, Sobre),
  `?world=phaser` e `?world=canvas`, celular 375 px.

### Pendências da Fase 5
1. Com 1024 px o botão do Piloto fica escondido (`pv-hide-md`); o passo 6 recorta só o saldo e o texto cita "no topo ou no menu do logo".
2. No passo do escritório o card cobre parte do botão "Abrir ficha" do HUD em telas de ~1000 px de largura.
3. "Pular" e "Concluir" usam a mesma marca (`done_at`); se um dia for preciso saber quem pulou, guardar o motivo numa coluna à parte.
