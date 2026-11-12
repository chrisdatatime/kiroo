# Arte licenciada fora do git

A arte de terceiros não é versionada (licença). Ela entra na imagem pelo bucket **kiroo-assets** (R2): o ZIP fixado em `assets.lock`
(`object` + `sha256`) é baixado, conferido e extraído por `docker/fetch_assets.py` (ver `docs/DOCKER.md`). Nada disso exige credencial no repositório.

## Cenário parallax do escritório (Forest of Illusion)

- Arte: **Forest of Illusion**, Luis Zuno (ansimuz), licença do autor (uso pessoal e comercial, modificação e redistribuição permitidos).
- Usamos **só** `back.png` (160x272) e `middle.png` (384x272). **Não** usar `tiles.png`.
- Caminho no pacote e no checkout: `assets/cenarios/floresta/back.png` e `assets/cenarios/floresta/middle.png` (ignorado pelo git; `.gitignore`).
  O frontend lê por `import.meta.glob` em `frontend/src/game/scenery/layers.js`; pasta e nomes em `scenery.js` (`SCENERY_DIR`, `SCENERY_FILES`).
- Sem os arquivos, o cenário é **gerado por código** (céu em degradê, colinas, silhueta de floresta), no mesmo pipeline; nada quebra.
- Como entra:
  1. Coloque os dois PNGs em `assets/cenarios/floresta/` dentro do ZIP do pacote (mesma estrutura de `assets/tilesets/`) e publique o novo ZIP no bucket `kiroo-assets`.
  2. Atualize `object` e `sha256` em `assets.lock`.
  3. `docker/fetch_assets.py` aceita `assets/cenarios/` (`ALLOWED_DIRS`); os arquivos não são obrigatórios (não estão em `REQUIRED`), então o build não falha sem eles.
  4. Localmente, basta copiar os PNGs para `assets/cenarios/floresta/` e rodar `npm run dev`.
- Crédito exibido em Preferências > Sobre e créditos (`SCENERY_CREDIT` em `scenery.js`). A URL da página de origem fica em `SCENERY_CREDIT.url` (vazia até ser informada; sem URL não há link).
- Tema: Preferências > Geral > Cenário do escritório (Floresta | Gerado por código), guardado em `localStorage` (`bc.cenario`).
