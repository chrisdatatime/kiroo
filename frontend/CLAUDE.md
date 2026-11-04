# Pivoo — frontend (escritório-jogo)

## O que é
Interface principal do **Pivoo**: um escritório explorável em pixel art, visto de cima (RPG 2D), em que o usuário produz vídeos de
produto para a Shopee Vídeo com agentes. **O motor é o servidor Python** (`../src/studio`): este frontend só desenha e
chama a API. Princípio: o usuário traz o produto, o estúdio propõe a produção, o usuário ajusta o que importa.

Decisão de produto: **jogo + atalhos diretos** — toda ação importante abre a 1 clique pelo HUD ou pela equipe no canto;
andar e conversar com os agentes é opcional.

## Rodar
```bash
npm install
npm run build        # gera dist/, servido pelo Python em http://127.0.0.1:8765/
npm run dev          # desenvolvimento: Vite em :5173 com proxy de /api e /media para :8765 (BC_API muda o alvo)
```
O servidor Python precisa estar no ar (`studio ui` na raiz do repositório). O painel administrativo antigo fica em `/painel`.

## Estrutura
```
src/
  App.jsx            # estado do jogo + ações da produção (chamam a API) + viewModel()
  engine/api.js      # /api/me (guarda o CSRF), GET/POST com X-Studio-Token, auth() com X-Studio-Client, 401 → tela de login
  ui/Auth.jsx        # entrar / criar conta / esqueci a senha / nova senha (?reset=token)
  ui/Account.jsx     # Minha conta (botão com o nome no HUD): dados, saldo, link do painel (admin) e Sair
  ui/Credits.jsx     # Créditos do estúdio: saldo, consumo por produção/etapa e extrato (GET /api/credits)
  engine/adapter.js  # estado REAL (/api/state) → etapas do jogo (STAGES) e créditos
  game/map.js        # mapa da sede: salas, paredes, portas, móveis, cadeiras, pontos de interação, bloqueios
  game/geometry.js   # tile ↔ pixel, direção do passo e BFS (colisão)
  game/pixel/        # draw.js (paleta e pincel), furniture.js (móveis/telas), characters.js (sprites), renderer.js (câmera e camadas)
  ui/World.jsx       # canvas + camada HTML (placas, nomes, cliques); Boneco.jsx = retrato no mesmo sprite
  ui/Hud.jsx, ui/Windows.jsx, ui/ProdWindow.jsx, ui/Sectors.jsx, ui/Training.jsx, ui/Music.jsx
```

## Como o estado funciona
- Sem sessão, `App` mostra `AuthScreen`; o escritório só monta depois do login (por isso `setRoot` mede a tela ao montar).
  Se o workspace mudar neste navegador (`bc.ws`), a produção aberta (`bc.pid`) é esquecida.
- Fora de localhost/127.0.0.1, `Auth.jsx` esconde a aba Criar conta: em `studio publish` o servidor recusa cadastro (só convite).
- Duas coisas diferentes chamadas "créditos": `v.credits` é o medidor da produção (usado/limite) e `v.wallet` é o saldo
  do workspace (`S.credits`). Uma pausa com "saldo de créditos" vira o aviso `kind: 'saldo'` no BudgetBox.
- `refresh()` consulta `/api/state` a cada 1,5 s; `deriveStage()` traduz status de produção/cenas para
  `produto → direcao → gerar_img → img_gerando → img_revisao → gerar_vid → vid_gerando → vid_revisao → montando → entrega → exportado`.
- Etapas pagas exigem **liberação explícita** (`/go_ahead`) depois de mostrar a estimativa em créditos.
- A cena 1 é gerada primeiro e, aprovada, vira referência das cenas 2 e 3.
- Look e setup do jogador ficam no `localStorage`; produção, fotos, versões e gastos ficam no servidor.
- **Piloto** (`ui/Pilot.jsx`, botão no HUD): Manual (você aprova tudo; sem refações sozinho), Assistido (padrão: você
  aprova a direção; o estúdio libera etapas pagas dentro do limite, refaz o que o revisor reprovar e aprova o que ele aprovar)
  e Automático (direção sugerida + aprova também o inconclusivo). Revisão final e exportação são sempre suas.
- **Mesa de jogos** (`ui/Games.jsx`, `game/minigames.js`, `GAMES_TILE` em `game/map.js`): Jogo da Velha e Damas com regras brasileiras
  contra um agente livre; avisa quando alguém precisa de você. Regras testadas em `tests/minigames.test.mjs`.
- **Edição do Beto** (`EditBox` em `ui/ProdWindow.jsx`, aba Entrega): estilo (Dinâmico/Suave/Limpo) e trilha vêm de
  `S.settings.edit_styles`; `POST /edit` salva e, com vídeo pronto, remonta só com FFmpeg. Na entrega há também o
  download "sem música" para usar um som em alta no editor da Shopee (músicas virais não podem ser embutidas).
- Personagens: sprites de 20x26 px gerados por código a partir de `look` (cor e acessório); 4 direções e poses parado, andar, sentar,
  digitar, acenar e comemorar. `Boneco` usa o mesmo sprite nos retratos.

## O que ainda é DEMO
Quando o motor está em modo DEMO (`settings.mode === "simulated"`), imagens e vídeos são placeholders e a conferência
do Rui não analisa nada: a interface mostra o selo **DEMO** e diz isso. Em modo real, as gerações são da Gemini API.
A importação automática de fotos pelo link **não existe**: as fotos vêm do usuário.

## Regras de produto (continuam valendo)
- Não inventar preço, título, variante ou características do produto. Legenda só usa ficha + o que o usuário confirmou.
- Mostrar estimativa e limite **antes** de cada etapa paga; diferenciar estimativa de custo confirmado.
- Corrigir uma cena refaz só aquela cena e mostra o que é preservado; limite de tentativas por cena vem do servidor.
- Ao atingir o limite: preservar tudo e oferecer subir limite, revisar o que existe ou continuar depois.
- Conferência automática pode ser inconclusiva; nada de "100% fiel".
- Publicação na Shopee é manual. Não mostrar modelos, filas ou parâmetros de API na experiência principal.
- Acessibilidade: elementos interativos são `<button>`/`<a>`, foco visível, alvos ≥ 44 px, estados não dependem só de cor.

## Identidade visual
Marca **Pivoo**, assinatura "Seu estúdio ganha vida." Marinho `#17234B`, lima `#D5F45B` (próxima ação, seleção, "!"), creme `#FFF8EC`,
preto `#111111`, azul-céu `#8ED8F8`. Fonte Nunito Sans. Os **olhos** são o centro da identidade e mudam com o humor do personagem.
Logos e padrão ficam em `src/assets/` (PNG transparentes enviados pelo Chris; não são vetores). Apoio da pixel art: lavanda `#B8B4DE`. Sem emojis como ícones, sem gradientes roxos.

## Sede em pixel art
> **Migração em andamento (SPEC-VIS-001):** com `?world=phaser` (ou Minha conta → Sobre e créditos) o mundo vem de
> `../assets/maps/office.tmj` no Phaser 3 (`game/world/tmjWorld.js`, `game/phaser/OfficeScene.js`, `ui/WorldPhaser.jsx`), tile de 32 px
> e câmera seguindo o jogador; por enquanto só a sala de Edição. O padrão continua o renderizador abaixo. Veja `../docs/HANDOFF.md`.
> `node tests/tmj.test.mjs` confere o mapa novo. Crédito do tileset: `../CREDITS.md` e `ui/About.jsx`.

- Mapa ortogonal 52x30 tiles em 16:9 (`game/map.js`), para a sede inteira caber na tela com tiles grandes (referência: Gather).
  `BUILD` é o prédio; o que sobra na borda é jardim com árvores (`OUTSIDE`), só visual. Planejamento, Direção criativa e Imagens
  em cima; área comum no meio; Meu escritório, Vídeos, Edição e Revisão embaixo. **A linha y=14 é o corredor que liga tudo: nunca
  ponha móvel nem cadeira nela.** `node tests/map.test.mjs` confere salas, cadeiras, interações e portas.
- Cada sala tem carpete próprio (`floor` em ROOMS → `CARPET` no renderizador); o corredor comum fica com piso de tábuas.
- Desenho em Canvas 2D (`game/pixel/renderer.js`): chão/paredes pré-desenhados, sprites ordenados pela base (o personagem passa na
  frente ou atrás dos móveis), encosto da cadeira por cima de quem senta. A sede inteira fica sempre na tela, sem zoom nem câmera
  seguindo; como a escala quase nunca é inteira, o mundo é desenhado num buffer em escala inteira e reduzido com suavização.
- Movimento fluido: `TICK` (130 ms) é o tempo de um passo e o desenho interpola exatamente esse tempo; `this.held` guarda as teclas
  ainda pressionadas e o `tick` emenda o próximo passo antes de parar, então segurar a tecla anda sem picotar.
- Interações: agente (conversar, ver trabalho, treinar), monitor (trabalho da sala), cadeira (sentar/levantar; a do agente é dele),
  Meu setup (personalizar), quadro, café, jogos e estante de trilhas na sala da Lia. Ao digitar em campos, os atalhos ficam suspensos.
- A imagem do kit visual é referência de arte; todos os móveis e personagens são desenhados por código, um a um.

## Treinamento e trilhas
`ui/Training.jsx` e `LearnPanel` falam com `/api/training/*` (motor em `../src/studio/training.py`). `ui/Music.jsx` fala com `/api/music*` e
`POST /api/productions/{id}/music` (motor em `../src/studio/music.py`). A Lia guarda a escolha; só o `_edit` do Beto aplica a trilha.

## Próximos passos (ver `../docs/ROADMAP_SAAS.md`)
Planos e Mercado Pago (sandbox), hospedagem; versão mobile do escritório.
