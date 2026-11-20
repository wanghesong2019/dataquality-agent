// Validate every ```mermaid block in docs/ by running it through mermaid.parse.
import {JSDOM} from 'jsdom';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', {pretendToBeVisual: true});
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, 'navigator', {
  value: dom.window.navigator,
  configurable: true,
  writable: true,
});
globalThis.DOMPurify = {sanitize: (dirty) => dirty};

const mermaid = (await import('mermaid')).default;
mermaid.initialize({startOnLoad: false});

const root = path.dirname(fileURLToPath(import.meta.url));
const docsDir = path.join(root, '..', 'docs');
const files = [];
(function walk(dir) {
  for (const e of fs.readdirSync(dir, {withFileTypes: true})) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p);
    else if (e.name.endsWith('.md') || e.name.endsWith('.mdx')) files.push(p);
  }
})(docsDir);

let ok = 0;
let fail = 0;
for (const f of files) {
  const src = fs.readFileSync(f, 'utf8');
  const blocks = [...src.matchAll(/```mermaid\n([\s\S]*?)```/g)];
  for (const m of blocks) {
    const code = m[1].trim();
    try {
      await mermaid.parse(code);
      ok++;
      console.log(`OK   ${path.relative(root, f)}`);
    } catch (e) {
      fail++;
      console.log(`FAIL ${path.relative(root, f)}: ${String(e.message).split('\n')[0]}`);
    }
  }
}
console.log(`\n${ok} diagram(s) OK, ${fail} failed`);
process.exit(fail ? 1 : 0);
