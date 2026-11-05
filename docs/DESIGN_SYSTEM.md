# Kiroo Design System

## Objetivo

O Design System separa a interface SaaS do universo visual do escritório sem criar dois produtos. O shell administrativo usa superfícies precisas, tipografia Geist, densidade moderada e movimento discreto. O escritório preserva a pixel art e os componentes `g-*` durante a migração.

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

## Tokens

| Papel | Token | Valor inicial |
| --- | --- | --- |
| Marca/estrutura | `--primary`, `--kiroo-ink` | `#17234B` |
| Ação prioritária | `--kiroo-lime` | `#D5F45B` |
| Canvas SaaS | `--background` | `#F6F7FA` |
| Superfície | `--card` | `#FFFFFF` |
| Texto secundário | `--muted-foreground` | `#626B87` |
| Linha | `--border` | `#DDE1EA` |
| Foco | `--ring` | `#9AB52F` |
| Sidebar | `--sidebar` | `#111A38` |

Regras:

- Lima indica ação prioritária, seleção ou atenção; não é cor decorativa ampla.
- Marinho sustenta navegação, texto e ações institucionais.
- Estados nunca dependem apenas de cor: usam texto e ícone.
- Raios base partem de 12 px; cards principais usam 14–16 px.
- Sombras são leves e reservadas para elevação real, como menus e command palette.
- Alvos interativos principais devem ter no mínimo 40 px; navegação usa 44 px ou mais.

## Tipografia e ícones

- Interface SaaS: Geist Variable.
- Escritório e legado: Nunito Sans até a migração de cada componente.
- Títulos usam peso 600–650 e tracking negativo discreto.
- Lucide usa normalmente 16 px, `strokeWidth={1.8}` na navegação e alinhamento central óptico.
- Emojis não substituem ícones de interface.

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
