// agentz llm bridge: batch chat-completions via z-ai-web-dev-sdk (GLM API).
// Usage: bun llm_bridge.mjs --tasks tasks.json --out results.json
// tasks.json: [{id, system, prompt, max_tokens?}]
// results.json: [{id, ok, content, error?}]
// Results are cached in CACHE_DIR keyed by sha256(system|prompt).
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const args = process.argv.slice(2);
function argOf(name, def) {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : def;
}
const tasksFile = argOf('--tasks', null);
const outFile = argOf('--out', null);
const cacheDir = argOf('--cache', '/home/z/my-project/got-agentz/experiments/agentz_arch_v1/cache');
const concurrency = parseInt(argOf('--concurrency', '3'), 10);

const { default: ZAI } = await import('z-ai-web-dev-sdk');

const tasks = JSON.parse(fs.readFileSync(tasksFile, 'utf8'));
fs.mkdirSync(cacheDir, { recursive: true });

// Provider selection: mistral if MISTRAL_API_KEY present, else z-ai (GLM)
const MISTRAL_KEY = process.env.MISTRAL_API_KEY || '';
const MISTRAL_MODEL = process.env.MISTRAL_MODEL || 'ministral-14b-latest';
const PROVIDER = MISTRAL_KEY ? 'mistral' : 'zai';

async function mistralCall(t) {
  const body = {
    model: MISTRAL_MODEL,
    messages: [
      ...(t.system ? [{ role: 'system', content: t.system }] : []),
      { role: 'user', content: t.prompt },
    ],
    max_tokens: t.max_tokens || 2048,
    temperature: 0.2,
  };
  const r = await fetch('https://api.mistral.ai/v1/chat/completions', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${MISTRAL_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`status ${r.status}: ${(await r.text()).slice(0, 200)}`);
  const j = await r.json();
  let content = j.choices?.[0]?.message?.content ?? '';
  content = String(content).replace(/<think>[\s\S]*?<\/think>/g, '').trim();
  return content;
}

const keyOf = (t) =>
  crypto.createHash('sha256')
    .update(JSON.stringify([PROVIDER, MISTRAL_MODEL, t.system || '', t.prompt, t.max_tokens || 2048]))
    .digest('hex');

function readCache(key) {
  const p = path.join(cacheDir, key + '.json');
  if (fs.existsSync(p)) {
    try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return null; }
  }
  return null;
}
function writeCache(key, val) {
  const p = path.join(cacheDir, key + '.json');
  fs.writeFileSync(p, JSON.stringify(val));
}

async function runTask(zai, t) {
  const key = keyOf(t);
  const cached = readCache(key);
  if (cached) return { id: t.id, ok: true, cached: true, ...cached };
  for (let attempt = 1; attempt <= 6; attempt++) {
    try {
      let content;
      if (PROVIDER === 'mistral') {
        content = await mistralCall(t);
      } else {
        const messages = [];
        if (t.system) messages.push({ role: 'assistant', content: t.system });
        messages.push({ role: 'user', content: t.prompt });
        const completion = await zai.chat.completions.create({
          messages,
          thinking: { type: 'disabled' },
          max_tokens: t.max_tokens || 2048,
        });
        content = completion.choices?.[0]?.message?.content ?? '';
        content = String(content).replace(/<think>[\s\S]*?<\/think>/g, '').trim();
      }
      const val = { content };
      writeCache(key, val);
      return { id: t.id, ok: true, cached: false, ...val };
    } catch (e) {
      const msg = String(e && e.message || e);
      const is429 = msg.includes('429') || msg.toLowerCase().includes('too many');
      if (attempt === 6) return { id: t.id, ok: false, error: msg };
      await new Promise(r => setTimeout(r, (is429 ? 8000 : 1500) * attempt));
    }
  }
}

async function main() {
  const zai = await ZAI.create();
  const results = new Array(tasks.length);
  let idx = 0;
  async function worker() {
    while (true) {
      const i = idx++;
      if (i >= tasks.length) return;
      results[i] = await runTask(zai, tasks[i]);
      process.stderr.write(`done ${i + 1}/${tasks.length}\n`);
    }
  }
  await Promise.all(Array.from({ length: concurrency }, worker));
  fs.writeFileSync(outFile, JSON.stringify(results, null, 1));
  const bad = results.filter(r => !r.ok).length;
  process.stderr.write(`DONE ok=${results.length - bad} err=${bad}\n`);
}
main().catch(e => { console.error('FATAL', e); process.exit(1); });
