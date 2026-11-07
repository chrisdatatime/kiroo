// Guard da marca: falha se o nome antigo aparecer em qualquer arquivo versionado (conteúdo, inclusive binários e
// metadados de imagem lidos como bytes, e nome de arquivo/pasta). Rodar: npm run check:brand (também roda em npm test).
// O nome é montado por partes para este arquivo não acusar a si mesmo.
// Allowlist estrita: só a nota histórica do HANDOFF e, se um dia existir, código de migração de chave antiga
// (localStorage/cookie). Cada exceção é arquivo + linha inteira exata (sem espaços nas pontas); nada de pasta, glob
// ou trecho parcial. Hoje não há migração de chave (nada persistido tinha o nome antigo), então só a nota do HANDOFF.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const OLD = ['p', 'i', 'v', 'o', 'o'].join('');
const re = new RegExp(OLD, 'i');
const Old = OLD[0].toUpperCase() + OLD.slice(1);
const ALLOW = [
  { file: 'docs/HANDOFF.md', line: `> Antes: ${Old} (renomeado para Kiroo em 2026-11)` }, // nota histórica
  // migração de chave: { file: 'frontend/src/...', line: '<linha exata>' }
];

const root = execFileSync('git', ['rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim();
const files = execFileSync('git', ['ls-files', '-z'], { cwd: root, encoding: 'utf8' }).split('\0').filter(Boolean);
const hits = [];
for (const f of files) {
  if (re.test(f)) { hits.push(`${f}: nome do arquivo`); continue; }
  const full = path.join(root, f);
  if (!fs.existsSync(full)) continue; // apagado no working tree e ainda não commitado
  const text = fs.readFileSync(full).toString('latin1');
  if (!re.test(text)) continue;
  text.split(/\r?\n/).forEach((ln, i) => {
    if (!re.test(ln)) return;
    if (ALLOW.some((a) => a.file === f && ln.trim() === a.line)) return;
    hits.push(`${f}:${i + 1}: ${ln.trim().slice(0, 120)}`);
  });
}
if (hits.length) {
  console.error(`check:brand: ${hits.length} ocorrência(s) do nome antigo em arquivos versionados:`);
  hits.forEach((h) => console.error('  ' + h));
  process.exit(1);
}
console.log(`check:brand ok (${files.length} arquivos versionados, nenhuma ocorrência fora da allowlist)`);
