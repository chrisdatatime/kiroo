# SPEC-VIS-001 — Mundo do Pivoo em tileset (Tiled + Phaser 3)

| | |
|---|---|
| Estado | Fase 1 entregue (pipeline + sala de Edição). Fase 2 entregue atrás da flag `?world=phaser` (só a Edição no mapa), aguardando validação. Fase 2b: demais salas + atlas. Ver HANDOFF.md. |
| Autor | Chris + Claude |
| Criada | 2026-11-04 |
| Substitui | Renderizador em Canvas 2D desenhado por código (`frontend/src/game/pixel/`) |

## 1. Problema

O mundo é desenhado por código (retângulos e elipses em Canvas 2D). O resultado lê como **planta baixa**: móveis
esquemáticos, paredes sem face frontal convincente, pouca densidade de detalhe. O alvo é o nível visual do
**Gather.town**: top-down 3/4, salas densas, parede com face frontal, personagem passando atrás dos móveis.

Desenhar isso à mão em código não escala: cada móvel novo é dezenas de linhas e nunca chega ao acabamento de um
tileset profissional.

## 2. Decisões já tomadas

- **Tileset:** LimeZu *Modern Interiors* 32×32, licença comercial comprada (exige crédito).
  Tilesets permitidos (em `assets/tilesets/`): `interiors` (`Interiors_32x32.png`), `room_builder`
  (`Room_Builder_32x32.png`), `modern_office` (`Modern_Office_32x32.png`) e `room_builder_office`
  (`Room_Builder_Office_32x32.png`). Nenhum outro.
- **Formato do mapa:** Tiled. A fonte da verdade do layout é `assets/maps/office.tmx` / `.tmj`.
- **Render do mundo:** Phaser 3 lendo o `.tmj`, com y-sorting, colisão e câmera. HUD, janelas e fichas continuam em
  React por cima.
- **Proibido** desenhar tile, móvel ou parede por código, SVG ou `fillRect`.

## 3. Como o mundo funciona hoje (levantamento do Passo 0)

### 3.1 Arquivos

| Arquivo | Linhas | Papel |
|---|---|---|
| `frontend/src/game/map.js` | 157 | **Dados do mapa**: `ROOMS`, `WALLS`, `DOORS`, `FURNITURE`, `CHAIRS`, `RUGS`, `WALL_DECOR`, `OUTSIDE`, `INTERACT`, `BLOCKED`, `SPOTS`. Grade 52×30, tile de 16 px. |
| `frontend/src/game/geometry.js` | 42 | tile ↔ pixel, direção do passo e BFS de 8 direções (caminho e colisão). |
| `frontend/src/game/pixel/draw.js` | 53 | Paleta, "pincel" de pixels, cache de sprites. |
| `frontend/src/game/pixel/furniture.js` | 289 | **Desenha por código** cada móvel, cadeira e tela de monitor. |
| `frontend/src/game/pixel/characters.js` | 119 | **Desenha por código** os personagens (20×26 px, 4 direções, 6 poses). |
| `frontend/src/game/pixel/renderer.js` | 343 | Loop de desenho: chão/paredes em canvas pré-renderizado, y-sorting, câmera, janelas animadas. |
| `frontend/src/ui/World.jsx` | 59 | Monta o canvas + a camada HTML (placas, nomes, cliques). |
| `frontend/src/Boneco.jsx` | 21 | Retrato do personagem no HUD e nas janelas, usando `characters.js`. |
| `frontend/src/App.jsx` | 937 | Estado do jogo e `viewModel()`: movimento, interações, câmera, estados dos agentes. |
| `frontend/tests/map.test.mjs` | 38 | Confere que salas, cadeiras, interações e portas são alcançáveis. |

### 3.2 Fluxo atual

1. `map.js` descreve o mapa em tiles; `BLOCKED` é a lista de tiles intransponíveis.
2. `App.jsx` guarda `player {i, j, path, dir, seat}` e `agents{}` em tiles inteiros; um `setInterval` de 130 ms dá um
   passo por vez, e a BFS de `geometry.js` acha o caminho.
3. `viewModel()` devolve posição, animação, destaques e estado de cada agente.
4. `renderer.js` desenha tudo e aplica a mesma câmera à camada HTML, onde ficam placas, nomes e botões de clique.
5. Interação: `targetAtTile()` mapeia tile → alvo (`agent`, `monitor`, `chair`, `board`, `coffee`, `games`, `music`,
   `mine`) e `doAction()` abre a janela React correspondente.

### 3.3 O que depende disso

- **`App.jsx`** é o maior acoplamento: importa `GRID`, `ROOMS`, `CHAIRS`, `FURNITURE`, `INTERACT`, `BLOCKED`, `SPOTS`,
  `SPAWN` e `tilesOf`, e converte tile → pixel na mão (`(i + 0.5) * T`).
- **`ui/World.jsx`** instancia o renderizador e posiciona a camada HTML.
- **`Boneco.jsx`** usa `characters.js` nos retratos do HUD, do diálogo, do treinamento e das janelas.
- **`tests/map.test.mjs`** valida o grafo de caminhos a partir de `map.js`.
- **Não dependem do desenho:** produção, agentes, treinamento, trilhas e créditos. O servidor Python não conhece o mapa.

### 3.4 Tilesets disponíveis (medidos)

| Arquivo | Tamanho | Grade | Tiles |
|---|---|---|---|
| `Room_Builder_32x32.png` | 2432×3616 | 76 col × 113 lin | 8.588 |
| `Interiors_32x32.png` | 512×34048 | 16 col × 1064 lin | 17.024 |

`assets/maps/office.tmx` já existe (30×20, 32 px) com as camadas certas e vazias:
`floor`, `walls`, `furniture_below`, `furniture_above` (tiles) e `collision`, `objects` (objetos).

## 4. Alvo

```
tools/tiles.yaml      nomes semânticos -> GIDs (fonte da verdade do vocabulário)
tools/rooms/*.yaml    cada sala descrita em texto
      ↓ tools/build_map.py (idempotente)
assets/maps/office.tmj + office.tmx
      ↓ Phaser 3 (frontend)                    ↓ tools/preview.py
mundo no jogo                                  tools/out/preview.png (validação)
```

- **Camadas:** `floor` e `walls` (chão e parede), `furniture_below` (atrás do personagem), `furniture_above` (na
  frente), `collision` (retângulos), `objects` (retângulos `type=room` com `id` e `nome`).
- **Y-sorting:** o personagem é desenhado entre `furniture_below` e `furniture_above`.
- **Colisão:** vem dos retângulos de `collision`, não mais de `BLOCKED`.

## 5. Restrições e riscos levantados

1. **Volume dos catálogos.** São 25.612 tiles. Gerar o catálogo é barato, mas **ler** todos como imagem é caro e lento.
   Mitigação: gerar o catálogo inteiro e ler sob demanda só os blocos necessários para a sala em construção.
2. **Pillow não está instalado** no `.venv`. As ferramentas precisam dele (`pip install pillow`).
3. **Personagens continuam desenhados por código.** Os dois arquivos liberados são cenário e móveis; o pacote de
   personagens do LimeZu é outro. `characters.js` e `Boneco.jsx` **não** são descontinuados nesta spec.
4. **Tamanho do tile dobra (16 → 32 px).** Com a regra atual de "sede inteira sempre na tela", uma tela de 1424×810
   comporta ~44×25 tiles de 32 px em escala 1:1. Isso implica salas de ~12×8, como já previsto para a Edição, e uma
   sede menor em tiles do que a atual (52×30). O layout será reconstruído, não convertido.
5. **Phaser 3 pesa** (~1,2 MB minificado). Entra como dependência nova do frontend, carregada depois do login.
6. **Autotile de parede e canto** precisa de tabela explícita em `tiles.yaml`; não será adivinhado.
7. **Crédito obrigatório:** `CREDITS.md` com "Tileset: Modern Interiors by LimeZu — https://limezu.itch.io/moderninteriors".

## 6. Descontinuado (não apagar até a Fase 2 validada)

- `frontend/src/game/pixel/furniture.js` — móveis desenhados por código.
- `frontend/src/game/pixel/renderer.js` — loop de desenho do mundo.
- `frontend/src/game/pixel/draw.js` — só o que serve a móveis e cenário.
- `frontend/src/game/map.js` — some quando o `.tmj` virar a fonte da verdade.

Continuam vivos: `characters.js`, `Boneco.jsx`, `geometry.js` (ou equivalente) e toda a lógica de produção.

## 7. Ferramentas da Fase 1 (entregues)

| Arquivo | O que faz |
|---|---|
| `tools/tileset_common.py` | tilesets, GID ↔ (coluna, linha), recorte de tile, fundo xadrez, fonte |
| `tools/make_catalog.py` | `--contact` (visão geral, aceita `--rows`) e catálogo ampliado com GID escrito (`--rows`, `--cols`, `--zoom`) |
| `tools/tiles.yaml` | vocabulário semântico: pisos, tabela explícita de parede, objetos com `cells`/`collision`/`layer` |
| `tools/rooms/edicao.yaml` | a sala 12×8 em texto (grid de caracteres + lista de objetos) |
| `tools/build_map.py` | YAML → `assets/maps/office.tmj` e `.tmx`; colisão em retângulos; sala como objeto `room`; idempotente |
| `tools/preview.py` | compõe as camadas em `tools/out/preview.png` (`--grid`, `--zoom`, `--crop`) |

Dependências: `pillow` e `ruamel.yaml` (o PyYAML não tem wheel para o Python 3.15 e falha ao compilar).

```
.venv\Scripts\python tools/make_catalog.py --contact
.venv\Scripts\python tools/build_map.py
.venv\Scripts\python tools/preview.py --zoom 2 --crop 1,1,15,11
```

## 8. Critérios de aceite

**Fase 1 (pipeline, só a sala de Edição)**
- `tools/make_catalog.py`, `tools/build_map.py` e `tools/preview.py` rodam do zero e são idempotentes.
- `tools/tiles.yaml` tem nome semântico para cada tile usado, com `layer: below|above`.
- `tools/rooms/edicao.yaml` descreve a sala 12×8 em texto.
- `tools/out/preview.png` mostra a sala com parede de face frontal, 3 estações de trabalho, plantas, estante, tapete e
  quadro, **sem área de chão livre maior que 3×3**.
- Nenhum tile é desenhado por código.

**Fase 2 (integração)**
- O `.tmj` é renderizado no Phaser dentro do Pivoo, com y-sorting, colisão e câmera.
- Os objetos `room` ligam às salas e estados que já existem.
- Andar, sentar, monitores, agentes, treinamento e trilhas seguem funcionando.
- `CREDITS.md` presente.
