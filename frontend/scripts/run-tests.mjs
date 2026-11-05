// npm test: guard da marca + todos os tests/*.test.mjs versionados. Sai com erro se algum falhar.
import { execFileSync, spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const front = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const run = (args) => spawnSync(process.execPath, args, { cwd: front, stdio: 'inherit' }).status === 0;
// minigames.test.mjs recebe o módulo por argumento (os outros ignoram)
const minigames = pathToFileURL(path.join(front, 'src/game/minigames.js')).href;
const tests = execFileSync('git', ['ls-files', 'tests/*.test.mjs'], { cwd: front, encoding: 'utf8' }).split('\n').filter(Boolean);
const failed = [];
if (!run(['scripts/check-brand.mjs'])) failed.push('check:brand');
for (const t of tests) if (!run([t, minigames])) failed.push(t);
if (failed.length) { console.error(`\nfalharam: ${failed.join(', ')}`); process.exit(1); }
console.log(`\nok: check:brand + ${tests.length} testes`);
