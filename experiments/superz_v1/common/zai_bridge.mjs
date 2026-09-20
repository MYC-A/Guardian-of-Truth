// z-ai bridge: reads a request JSON file, calls ZAI chat completion,
// writes response JSON file. Avoids argv length limits entirely.
// Usage: node zai_bridge.mjs <request.json> <response.json>
import fs from 'fs/promises';

const SDK = '/home/z/.bun/install/global/node_modules/z-ai-web-dev-sdk/dist/index.js';
const { default: ZAI } = await import(SDK);

async function main() {
  const [reqPath, respPath] = process.argv.slice(2);
  const req = JSON.parse(await fs.readFile(reqPath, 'utf-8'));
  // req: {system, user, thinking}
  const zai = await ZAI.create();
  const body = {
    messages: [
      { role: 'system', content: req.system },
      { role: 'user', content: req.user },
    ],
    thinking: { type: req.thinking ? 'enabled' : 'disabled' },
  };
  const t0 = Date.now();
  const response = await zai.chat.completions.create(body);
  const out = {
    ok: true,
    content: response?.choices?.[0]?.message?.content ?? '',
    model: response?.model ?? '',
    usage: response?.usage ?? null,
    elapsed_ms: Date.now() - t0,
  };
  if (!out.content || !out.content.trim()) { out.ok = false; out.error = 'empty-content'; }
  await fs.writeFile(respPath, JSON.stringify(out), 'utf-8');
}

main().catch(async (e) => {
  const respPath = process.argv[3];
  try { await fs.writeFile(respPath, JSON.stringify({ ok: false, error: String(e && e.message || e) }), 'utf-8'); } catch {}
  process.exit(1);
});
