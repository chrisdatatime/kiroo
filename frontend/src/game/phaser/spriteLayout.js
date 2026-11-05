// Localiza os desenhos pela transparência da folha, pois os PNGs recebidos têm
// espaçamento diferente de 32 px entre os corpos. Executado só ao carregar a cena.
function bands(counts, expected) {
  const runs = [];
  for (let i = 0; i < counts.length; i++) {
    if (!counts[i]) continue;
    const start = i;
    while (i + 1 < counts.length && counts[i + 1]) i++;
    runs.push({ start, end: i + 1 });
  }
  // Antenas e acessórios podem formar ilhas: agrupa primeiro as mais próximas.
  while (runs.length > expected) {
    let closest = 0;
    for (let i = 1; i < runs.length - 1; i++) {
      if (runs[i + 1].start - runs[i].end < runs[closest + 1].start - runs[closest].end) closest = i;
    }
    runs.splice(closest, 2, { start: runs[closest].start, end: runs[closest + 1].end });
  }
  if (runs.length !== expected) throw new Error(`Folha KIROO: esperadas ${expected} faixas, encontradas ${runs.length}`);
  return runs;
}

export function kirooFrameRects({ data, width, height }, columns = 6, rows = 6) {
  const rowCounts = new Uint32Array(height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) if (data[(y * width + x) * 4 + 3] > 127) rowCounts[y]++;
  }
  const rects = [];
  for (const row of bands(rowCounts, rows)) {
    const colCounts = new Uint32Array(width);
    for (let x = 0; x < width; x++) {
      for (let y = row.start; y < row.end; y++) if (data[(y * width + x) * 4 + 3] > 127) colCounts[x]++;
    }
    for (const col of bands(colCounts, columns)) {
      const w = col.end - col.start, h = row.end - row.start;
      if (w > 32 || h > 32) throw new Error(`Quadro KIROO excede 32x32: ${w}x${h}`);
      rects.push({ x: col.start, y: row.start, width: w, height: h });
    }
  }
  return rects;
}

export function normalizeKirooSheet(source, createCanvas = () => document.createElement('canvas')) {
  const input = createCanvas();
  input.width = source.width; input.height = source.height;
  const ctx = input.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(source, 0, 0);
  const rects = kirooFrameRects(ctx.getImageData(0, 0, input.width, input.height));
  const output = createCanvas();
  output.width = 192; output.height = 192;
  const out = output.getContext('2d');
  out.imageSmoothingEnabled = false;
  rects.forEach((r, index) => {
    // Centro e base comuns: não muda escala nem interpola os pixels originais.
    const x = (index % 6) * 32 + Math.floor((32 - r.width) / 2);
    const y = Math.floor(index / 6) * 32 + 32 - r.height;
    out.drawImage(source, r.x, r.y, r.width, r.height, x, y, r.width, r.height);
  });
  return output;
}
