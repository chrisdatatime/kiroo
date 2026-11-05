# Kiroo

*Seu estúdio ganha vida.*


Esteira orquestrada para vídeos de produto no Shopee Vídeo, preservando o fluxo:
**referências oficiais → imagem estática aprovada → animação dessa imagem → montagem**.

- Arquitetura: [docs/ARQUITETURA.md](docs/ARQUITETURA.md)
- Requisitos, decisões e pendências: [docs/REQUISITOS.md](docs/REQUISITOS.md)
- Integrações e preços verificados: [docs/INTEGRACOES.md](docs/INTEGRACOES.md)

## Estado atual (Marco 1)

| Parte | Situação |
|---|---|
| Ficha, perfis versionados, roteiro de 3 cenas, estados, tentativas, orçamento, retomada | funcionando, testado (modo simulado) |
| Montagem FFmpeg (1080×1920, 30 fps, textos de tela, trilha silenciosa), capa, legenda, relatórios | funcionando, testado |
| Adaptadores Gemini (imagem, vídeo Omni Flash, planner, revisor) | código escrito conforme a doc, **nunca executado** — chave configurada e modelos visíveis; falta orçamento e fotos do produto |
| Escritório dos agentes (interface local): agentes ao vivo, aprovação/reprovação por cena, revisão final, orçamento, configuração dos agentes | funcionando, testado (cadastro de produto com upload ainda pela CLI) |

O **modo simulado** gera placeholders listrados marcados como `SIMULADO`. Ele valida o fluxo, não a integração nem a qualidade visual.

## Instalação (Windows, PowerShell)

```powershell
cd C:\Users\chris\OneDrive\Documentos\Projetos\shopee-video-studio
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev,real]"
copy .env.example .env
winget install Gyan.FFmpeg   # se ainda não houver FFmpeg
.venv\Scripts\studio doctor
```

## Jogo (interface principal)

O escritório-jogo em React fica em `frontend/` e é servido pelo próprio servidor Python em `http://127.0.0.1:8765/` (o painel administrativo continua em `/painel`).

```powershell
cd frontend; npm install; npm run build; cd ..
.venv\Scripts\studio ui
```

**Contas:** o jogo abre numa tela de entrar/criar conta. A **primeira conta criada vira administradora** e herda as produções, o modo real e o teto mensal já existentes; contas seguintes começam em DEMO, isoladas. Administração por linha de comando:

```powershell
.venv\Scripts\studio admin list
.venv\Scripts\studio admin allow-real --email pessoa@exemplo.com   # deny-real desfaz
.venv\Scripts\studio admin reset-link --email pessoa@exemplo.com   # link de nova senha (ainda não há envio de e-mail)
.venv\Scripts\studio admin create-user --email pessoa@exemplo.com --name "Pessoa"   # senha pedida sem eco
.venv\Scripts\studio admin grant-credits --email pessoa@exemplo.com --credits 50 --note "cortesia"
.venv\Scripts\studio admin credits --email pessoa@exemplo.com   # saldo e reservado agora
```

**Créditos:** cada workspace tem um livro-razão. O estúdio reserva a estimativa antes de cada chamada paga e, quando ela termina, cobra o custo e devolve a diferença. Uma recusa sem custo é estornada. Sem saldo, a produção pausa sem gastar. A conta do dono é isenta, mas o consumo dela fica registrado. No jogo, o saldo e o extrato ficam em Minha conta → Créditos e extrato.

Fluxo no jogo: Nina (ficha e fotos) → Theo (direção) → Iris (imagens, com liberação após a estimativa em créditos) → Rui (revisão/ajustes) → Lia (vídeos, nova liberação) → Beto (montagem e exportação). O HUD e a equipe no canto abrem cada etapa a 1 clique.

**Especialistas:**
- **Iris e Lia:** seguem um manual de ofício ([src/studio/agents/craft.py](src/studio/agents/craft.py)) acrescentado a cada cena conforme o tipo de plano (abertura, detalhe ou fechamento).
  - Nas imagens: ótica de celular top de linha, luz, cor fiel às fotos oficiais, materiais, área segura do 9:16 e mãos realistas.
  - Nos vídeos: uma ação por plano, câmera explícita, linha do tempo dentro da parte usada do take, gancho no primeiro segundo e final estável para a transição.
- **Beto (edição):** monta em três estilos ([src/studio/agents/editing.py](src/studio/agents/editing.py)), com áudio normalizado para redes (−14 LUFS).
  - **Dinâmico:** transições rápidas, whoosh, pop no gancho e batida de 120 BPM.
  - **Suave:** fusões e lo-fi de 90 BPM.
  - **Limpo:** cortes secos, sem som.

  Trilhas e efeitos do estúdio são sintetizados pelo FFmpeg e livres de direitos. Trilhas próprias entram em `assets/music/library.json` (`id`, `title`, `file`, `bpm`, `license` obrigatória).

  Músicas virais têm direitos autorais e só são licenciadas dentro de cada plataforma. Por isso o Beto entrega também `final_sem_musica.mp4`, para o som em alta ser escolhido no editor da Shopee Vídeo. Trocar o estilo depois de pronto só remonta (sem custo de geração).

Roteiro comercial (contas, créditos, Mercado Pago, hospedagem): [docs/ROADMAP_SAAS.md](docs/ROADMAP_SAAS.md).

## Treinamento dos agentes e trilhas

**Treinamento** (`src/studio/training.py`): rascunho, teste e versão ativa por workspace e por agente, mais a base da marca. Cada produção congela as versões ao ser criada. Prioridade nos pedidos: regras obrigatórias e fatos do produto; direção da produção; orientações do agente; base da marca. Referências entram cercadas como dados.

| Agente | Onde o treinamento é usado |
|---|---|
| Theo | Chamada de roteiro |
| Nina | Sem modelo próprio: entra na chamada de roteiro |
| Iris e Lia | Pedido de cada imagem e cada vídeo |
| Rui | Critérios da conferência automática |
| Beto | Sem modelo: só o estilo de edição padrão |

**Trilhas** (`src/studio/music.py`): Biblioteca Kiroo, uploads privados com autorização declarada e tendências. Tendências vêm só de curadoria manual em `profiles/music/trends.json` (`updated_at`, `curator`, `items` com `title`, `artist`, `platform`, `region`, `source`, `checked_at`) e nunca são incorporadas: o vídeo sai sem trilha para adicionar a música na plataforma.

## Online pelo seu computador

Instale o túnel uma vez (`winget install Cloudflare.cloudflared`) e rode:

```powershell
.venv\Scripts\studio publish
```

O comando imprime o endereço público `https://....trycloudflare.com`. O servidor continua escutando só em 127.0.0.1; quem chega de fora passa pelo túnel. Nesse modo o cadastro fica **fechado**: crie contas com `studio admin create-user`. O endereço muda a cada reinício, e o estúdio só fica no ar com o PC ligado, sem hibernar e com o comando aberto.

## Painel administrativo (antigo escritório em SVG)

```powershell
.venv\Scripts\studio ui          # abre http://127.0.0.1:8765
```

Na interface (navegação no topo):

- **Nova produção**: assistente em 4 etapas — Produto → Fotos → **Ideia do vídeo** → Revisão e orçamento — com a prévia "Como seu vídeo vai ficar" ao lado. Na ideia do vídeo, o estúdio já traz uma sugestão (apresentação, proposta, ambiente, tom) feita **por regras** a partir do nome/categoria (as fotos não são analisadas); dá para seguir sem digitar, personalizar por cartões, marcar detalhes, desfazer, e ver/editar as instruções de geração (com "Restaurar instruções automáticas"). O rascunho fica salvo neste navegador (as fotos não).
- **Produção**: progresso, bloco "Sua vez" com o que precisa de você, cenas com aprovar/reprovar, entrega final, ficha e controles de orçamento; o escritório fica ao lado e pode ser recolhido.
- **Gastos**, **Agentes** (configuração e eventos) e **Escritório** (vista ampliada).
- **Chave DEMO** no topo: ligada = tudo simulado e sem custo; desligar exige chave no `.env` e teto mensal.

Escolhas criativas viram formato e ambiente versionados (`profiles/format`, `profiles/art_direction`) e um bloco de direção acrescentado às instruções; nunca viram fatos do produto.

Duas travas de gasto por chamada paga: orçamento da produção e teto do mês. O servidor escuta só em 127.0.0.1, exige login (cookie de sessão) e um token CSRF em toda ação; cada conta só vê o próprio workspace. O painel `/painel` é só do administrador.

## Uso

```powershell
# Demo 100% simulada com aprovações automáticas de demo
.venv\Scripts\studio demo

# Produção real (depois de preencher .env com STUDIO_MODE=real, STUDIO_ALLOW_PAID_CALLS=true e GEMINI_API_KEY)
.venv\Scripts\studio new --product examples\copo_alca_azul.json --budget 5
.venv\Scripts\studio run <id>                       # avança até o próximo portão
.venv\Scripts\studio status <id>
.venv\Scripts\studio approve <id> 1 image           # ou video
.venv\Scripts\studio reject <id> 2 video --note "mão atravessa a alça"
.venv\Scripts\studio reject <id> 2 video --redo-image --note "tampa errada"
.venv\Scripts\studio prompt <id> 3 --animation-file novo_prompt.txt
.venv\Scripts\studio grant <id> 1 image --extra 1   # libera cena bloqueada
.venv\Scripts\studio budget <id> --set 8 ; .venv\Scripts\studio resume <id>
.venv\Scripts\studio final <id> approve
```

Referências com caminho relativo são resolvidas a partir da pasta onde o comando roda. A foto da Bia fica em `assets/bia/PERFIL BIA.jpg` (fora do Git).

## Testes

```powershell
.venv\Scripts\python -m pytest -q          # simulados + FFmpeg (sem custo)
```

Testes reais ficam em `tests/integration` com a marca `real` e só rodam com `STUDIO_RUN_REAL_TESTS=1`, chave e `STUDIO_REAL_TEST_BUDGET_USD`.

## Observações

- O projeto está dentro do OneDrive: `data/` (vídeos) e `.venv/` serão sincronizados. Se incomodar, aponte `STUDIO_DATA_DIR` para uma pasta fora do OneDrive.
- O texto "Publicidade • Imagens ilustrativas geradas por IA" é um ponto de partida configurável no perfil de formato e precisa de revisão conforme as regras vigentes.
