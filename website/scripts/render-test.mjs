// Render every ```mermaid block in docs/ with mermaid.render() — this exercises
// the tooltip/transition code path that the browser hits (parse() alone does not).
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
// jsdom does not implement CSSStyleSheet / adoptedStyleSheets — shim them.
globalThis.CSSStyleSheet = class {
  replaceSync() {}
  insertRule() {
    return 0;
  }
};
dom.window.document.adoptedStyleSheets = [];

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
let i = 0;
for (const f of files) {
  const src = fs.readFileSync(f, 'utf8');
  const blocks = [...src.matchAll(/```mermaid\n([\s\S]*?)```/g)];
  for (const m of blocks) {
    const code = m[1].trim();
    i++;
    try {
      const {svg} = await mermaid.render(`d${i}`, code);
      if (!svg || svg.length < 50) throw new Error('empty svg');
      ok++;
      console.log(`OK   ${path.relative(root, f)} (svg ${svg.length} chars)`);
    } catch (e) {
      fail++;
      console.log(`FAIL ${path.relative(root, f)}: ${String(e.message).split('\n')[0]}`);
    }
  }
}
console.log(`\n${ok} diagram(s) rendered, ${fail} failed`);
process.exit(fail ? 1 : 0);
