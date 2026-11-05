# Kiroo Design System

## Objetivo

O Design System separa a interface SaaS do universo visual do escritório sem criar dois produtos. O shell administrativo usa superfícies precisas, tipografia Instrument Sans, densidade moderada e movimento discreto. O escritório preserva a pixel art e os componentes `g-*` durante a migração.

## Auditoria inicial

- Stack: React 18, Vite 5 e JavaScript/JSX; backend e orquestração ficam fora do frontend.
- UI anterior: CSS global, estilos inline, componentes `g-*` (jogo/janelas) e `pv-*` (shell) em paralelo.
- Iconografia anterior: SVGs locais sem catálogo compartilhado.
- Ausências: biblioteca de primitives, tokens semânticos globais, tipagem, lint e testes de componentes/acessibilidade automatizados.
- Risco principal: alterar o CSS global pode afetar o escritório, que depende de medidas, posições e camadas específicas.

## Fundação técnica

- shadcn/ui instalado pela CLI oficial em modo Vite, JSX e Radix.
- Tailwind CSS v4 integrado pelo plugin oficial do Vite.
- Lucide React é a biblioteca de ícones do shell.
- `components.json` é a fonte de configuração para novos primitives.
- O alias `@/*` aponta para `frontend/src/*`.
- Components shadcn são código do produto: devem ser revisados e personalizados, não tratados como dependência visual fechada.

## Tokens (marca Kiroo, 2026-11)

| Papel | Token | Valor |
| --- | --- | --- |
| Tinta (texto, primário) | `--kiroo-ink`, `--primary`, `--foreground` | `#0E0E10` |
| Laranja (agente ativo, foco, atenção) | `--kiroo-orange`, `--ring` | `#FF5B2E` |
| Papel (fundo) | `--kiroo-paper`, `--background` | `#FAFAF8` |
| Canvas (fundo do mundo) | `--kiroo-canvas` | `#E9E8E4` |
| Superfície | `--surface`, `--card` | `#FFFFFF` |
| Linha | `--border-color`, `--border`, `--input` | `#E7E7E4` |
| Fundo neutro | `--muted-bg`, `--muted` | `#F2F2EF` |
| Texto secundário | `--text-muted`, `--muted-foreground` | `#77777C` |
| Texto apagado | `--text-faint` | `#9A9AA0` |
| Agente livre | `--idle` | `#C9C9C4` |
| Borda no escuro | `--dark-border` | `#2A2A2E` |

Regras:

- Laranja só para agente ativo, foco e "precisa de você"; nunca em áreas grandes. Texto sobre laranja é sempre tinta (~6:1);
  laranja sobre branco dá ~3:1, então nada de texto pequeno laranja sobre fundo claro.
- Botão primário é tinta com texto papel ("Contratar agente", "Nova missão").
- Estados nunca dependem apenas de cor: usam texto e ícone (a cabeça do agente de 12 px para estado de agente).
- Raios base partem de 12 px; cards principais usam 14–16 px.
- Sombras são leves e reservadas para elevação real, como menus e command palette.
- Alvos interativos principais devem ter no mínimo 40 px; navegação usa 44 px ou mais.
- Só o tema claro está ativo; os tokens escuros ficam em `.kiroo-dark`.

## Tipografia e ícones

- Instrument Sans (400–700) para tudo, inclusive textos desenhados no Phaser; Geist Mono (400–500) para rótulos e números.
  Ambas auto-hospedadas via `@fontsource`.
- Títulos usam peso 600–650 e tracking negativo discreto.
- Lucide usa normalmente 16 px, `strokeWidth={1.8}` na navegação e alinhamento central óptico.
- Emojis não substituem ícones de interface. Logotipo só como imagem (`src/assets/brand/`).

## Componentes adotados na primeira entrega

- `Sidebar`: navegação colapsável no desktop e drawer acessível no mobile.
- `Button`: ações primária, secundária, ghost e outline.
- `Card`: composição dos painéis e métricas.
- `Badge`: estados e contagens.
- `Tooltip`: rótulos da navegação recolhida.
- `DropdownMenu`: conta e preferências.
- `Progress`: progresso de missão e orçamento.
- `Sheet`, `Separator`, `Skeleton` e `Input`: dependências da sidebar e base para próximas etapas.

## Plano de migração

### P0 — concluído nesta fatia

- Integrar shadcn/ui sem criar outra aplicação.
- Definir tokens Kiroo e tipografia do shell.
- Migrar navegação principal, responsividade e menu da conta.
- Migrar a Central preservando ações e dados do `viewModel`.

### P1 — próximo

- Migrar Missão e Equipe para os mesmos primitives.
- Transformar janelas de conta, créditos e piloto em Dialog/Sheet.
- Padronizar estados vazios, carregamento, erro, confirmação e toast.
- Adicionar testes de componentes com Testing Library e axe-core.

### P2

- Migrar formulários de produção, treinamento e configurações por fluxo.
- Adotar React Hook Form + schema somente onde validação complexa justificar as dependências.
- Remover estilos inline à medida que cada componente for migrado.

### P3

- Harmonizar o HUD do escritório com o shell sem descaracterizar a pixel art.
- Medir bundle e separar chunks de Radix/Phaser quando houver ganho real.
- Remover classes legadas apenas quando não houver mais consumidores.

## Guardrails

- Não alterar contratos de API, estados da produção ou lógica dos agentes durante migrações visuais.
- Não fazer conversão ampla para TypeScript junto com a migração visual.
- Cada etapa precisa passar build e testes existentes antes de avançar.
- Não executar atualizações forçadas de dependências para resolver avisos sem análise de compatibilidade.
