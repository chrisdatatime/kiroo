# Kiroo — diagnóstico, visão e plano de evolução (2026-11-04)

> Escrito depois de ler `App.jsx`, `Hud.jsx`, `ProdWindow`, `data.js`, `agent_config.py`, `orchestrator.py`, `view.py`, os docs e o HANDOFF.
> Primeira fatia já implementada: ver "O que entrou agora" no fim.

## 1. Diagnóstico

### O que o código mostra (e não o que a landing promete)
1. **A promessa é uma plataforma de equipes de agentes; o produto é uma esteira fixa de vídeo para a Shopee.**
   Os seis agentes são constantes em `game/data.js` (`AGENTS`), as etapas são uma lista fixa (`STAGES`), o status de cada agente é um `if` por id
   (`App.statusOf`) e as falas vêm de `dialogFor`, um roteiro escrito à mão por etapa. Não existe o conceito de **objetivo**, **plano**,
   **agente configurável** nem **habilidade**. No motor (`agent_config.AGENTS`), 4 dos 8 "agentes" têm `uses_ai: False`: Orquestrador, Preparação, Edição e "Você".
   O Orquestrador é uma máquina de estados de 949 linhas (`orchestrator.py`), boa e robusta, mas escrita para um único fluxo.
2. **A navegação é o jogo.** Tudo que importa (aprovar, liberar gasto, ver custo) mora em 8 botões de HUD + ~12 janelas flutuantes sobrepostas
   (Setores, Produções, Jogos, Meu setup, Piloto, Conta, Créditos, Sobre…). Mesa de jogos e personalização de cadeira têm o mesmo peso que "aprovar uma cena que custa dinheiro".
   Não há hierarquia, não há lugar para "o que precisa de mim agora" (o `!` nos bonecos faz esse papel, mas só quem anda pelo mapa o vê).
3. **Front-end sem camadas.** `App.jsx` é uma classe de 952 linhas que mistura game loop (tick de 200 ms que dá `setState` na árvore inteira, 5×/s), chamadas de API,
   regras de negócio e um `viewModel()` de ~300 linhas que devolve centenas de campos. `ProdWindow` (481 linhas) repete o padrão. Estilo é 90% inline; não há tokens nem componentes
   (cada janela reimplementa painel, cabeçalho, botão de fechar).
4. **Investimento visual desproporcional.** Três gerações de renderização convivem (Canvas legado, Phaser 2b, sprites humanos Fase 3), enquanto a camada de gestão
   (equipe, conhecimento, histórico, aprovações) não existe como tela. O escritório está sendo polido antes de ser **útil**.
5. **Linguagem visual de brinquedo em tarefas sérias.** Bordas de 3 px + sombra dura em formulários de custo e aprovação passam "jogo", não "confiança".
   A base de identidade (marinho, lima, olhos expressivos, Nunito Sans) é boa e deve ficar; falta sistematizar e tirar o "chrome de jogo" do trabalho.
6. **Polling de 1,5 s** em `/api/state` para tudo. Funciona; não escala para várias missões/agentes e não dá linha do tempo ao vivo.

### O que já é de classe mundial (preservar)
- **Livro-razão de créditos** com reserva → débito → estorno, idempotente por `ext_ref`. Raro em MVP.
- **Orçamento antes do gasto**, pausa sem perder nada, retomada de operações remotas, `attempts` auditáveis, reaproveitamento por hash.
- **Piloto** (Manual / Assistido / Automático): é o embrião de uma política de autonomia por agente.
- Regras de produto honestas (não inventar dados, conferência pode ser inconclusiva, publicação manual).
- Suíte de testes do motor (≈ 20 arquivos) e testes do mapa.

## 2. Visão

> **Kiroo é o sistema operacional de equipes de agentes: você descreve um objetivo, a equipe planeja, executa, pede decisão nos pontos certos e entrega — e você vê tudo acontecendo.**

O diagrama "O motor trabalhando nos bastidores" (objetivo → orquestrador → frentes em paralelo → revisão → entrega) é o **modelo mental certo**.
Hoje ele existe só dentro do código. A visão é torná-lo o **centro do produto**:

| Conceito | O que é | Hoje |
|---|---|---|
| **Missão** | Um objetivo do usuário com orçamento, política de autonomia e histórico | "Produção" (só vídeo Shopee) |
| **Playbook** | Receita declarativa: passos, dependências, pontos de aprovação | Hard-coded em `orchestrator.py` |
| **Agente** | Papel + habilidades + conhecimento + limites + treino | 6 constantes |
| **Checkpoint** | Decisão humana (aprovar, ajustar, liberar gasto) | Espalhado em janelas |
| **Entrega** | Arquivos, custo final, trilha de decisões | Aba "Entrega" |
| **Escritório** | Visão *ambiente* da equipe viva (presença) | A navegação inteira |

### Arquitetura de informação (4 áreas + 2 utilitárias)
1. **Central** — a fila: o que precisa de você, missão em curso, equipe agora, recentes. Respondida em 5 segundos.
2. **Missão** — o fluxo ao vivo (a figura acima, com estado real), próxima ação e custo da missão.
3. **Equipe** — cadastro dos agentes: papel, estado, o que sabem, treinar. (Depois: criar, configurar, importar.)
4. **Escritório** — o mundo em pixel art, com seu valor intacto: *ver* a equipe trabalhando e interagir com ela. Deixa de ser a porta de entrada obrigatória.
- Utilitárias: **Créditos** e **Conta**, sempre na lateral; **⌘K** para ir a qualquer lugar.

### Sistema de design "Kiroo Studio"
Mantém marinho `#17234B`, lima `#D5F45B`, creme, Nunito Sans e os olhos. Muda a *gramática*: superfícies planas, linha de 1 px, raio 12, sombra suave, números tabulares,
lima **somente** para "próxima ação / precisa de você". Estado nunca só por cor (ícone + texto). O estilo "jogo" (borda grossa) fica no Escritório e nos minijogos.

## 3. Arquitetura alvo
- **Motor:** extrair do `orchestrator.py` um executor de *playbooks* declarativos (JSON/YAML: passos, `needs`, `approval`, `budget`). O fluxo atual vira o playbook `video_shopee`.
  Agentes viram registros (`agents`, `skills`, `knowledge`) em vez de constantes; `agent_config.AGENTS` já é o ponto de partida.
- **Eventos:** SSE por workspace (`/api/events`) no lugar do polling; a linha do tempo da missão consome o mesmo `events` já persistido.
- **Front:** store externa (`useSyncExternalStore`) com o estado do motor, separada do game loop; o loop do mundo passa a ser só do Escritório
  (hoje roda e re-renderiza tudo mesmo fora dele). Telas novas consomem *selectors*, não um `viewModel` gigante.
- **Phaser** continua em chunk lazy, só na área Escritório.
- **Qualidade:** componentes compartilhados e tokens CSS (`shell.css`); testes puros para a derivação do fluxo (`tests/pipeline.test.mjs`).

## 4. Plano
| Fase | Entrega | Estado |
|---|---|---|
| **0 — Casca** | Shell com navegação, Central, Missão (fluxo ao vivo), Equipe, ⌘K, tokens | **feito** |
| 1 — Fundação do front | Extrair store do `App.jsx`; game loop só no Escritório; migrar ProdWindow para componentes do design system | próxima |
| 2 — Missões genéricas | Modelo `mission` + `playbook` no motor; `video_shopee` como primeiro playbook; "Nova missão" com objetivo em texto | |
| 3 — Agentes como dado | Criar/editar agente (papel, instruções, conhecimento, autonomia por agente); treino sai da janela para a aba Equipe | |
| 4 — Tempo real e histórico | SSE, linha do tempo por missão, inbox de decisões com notificação | |
| 5 — Escritório de presença | Agentes no mapa refletem missões reais de qualquer playbook; remover renderizador legado | |
| 6 — SaaS | Planos/Mercado Pago, convites de membros, mobile | já roteirizado em `ROADMAP_SAAS.md` |

## 5. Decisões que são suas
1. **Foco de mercado**: continuar com vídeo Shopee como primeiro playbook (recomendado: é o caso real e validável) ou abrir já para outros nichos.
2. **Escritório como padrão ou como aba**: esta fatia deixa **Central** como entrada e o Escritório a um clique. Se preferir o contrário, é uma linha (`bc.view`).
3. **Fase 2 mexe no motor** (renomear produção→missão no banco). Quero seu ok antes: migração com dados existentes.

## O que entrou agora (Fase 0)
`frontend/src/shell/`: `Shell.jsx` (lateral, barra superior, ⌘K), `Central.jsx`, `MissionView.jsx`, `TeamView.jsx`, `pipeline.js` (derivação pura do fluxo, testada),
`icons.jsx`, `shell.css`. `App.jsx` ganhou `view` e passa a medir só a área útil; `Hud.jsx` perde o que a barra superior já mostra. Nenhuma API nem regra do motor mudou.
