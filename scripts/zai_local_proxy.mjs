#!/usr/bin/env node
/**
 * Local OpenAI-compatible proxy: POST /v1/chat/completions -> z-ai SDK.
 *
 * Purpose: research-diagnostic LLM backend for the Guardian competition audit
 * arms (C1/C2/C3) while the frozen BAI provider account has zero balance.
 * This proxy is a RESEARCH TOOL, never part of a competition submission
 * (external API dependency is not competition-legal under the conservative
 * no-network interpretation; see COMPETITION_REQUIREMENTS_AUDIT.md §9).
 *
 * - accepts OpenAI chat.completions payloads (messages, max_tokens,
 *   max_completion_tokens, response_format, reasoning_effort are accepted
 *   and ignored except messages);
 * - forwards messages to z-ai-web-dev-sdk with thinking disabled;
 * - GLOBAL request queue: minimum spacing between upstream calls
 *   (ZAI_PROXY_MIN_INTERVAL_MS, default 4000) to respect rate limits;
 * - on upstream 429/5xx: exponential backoff retries (5s,15s,45s,90s,150s);
 * - logs per-call usage tokens for resource profiling (§24).
 */
import http from 'node:http';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const module_ = require('/home/z/.bun/install/global/node_modules/z-ai-web-dev-sdk');
const ZAI = module_.default || module_;

const PORT = parseInt(process.env.ZAI_PROXY_PORT || '8010', 10);
const HOST = '127.0.0.1';
const MIN_INTERVAL = parseInt(process.env.ZAI_PROXY_MIN_INTERVAL_MS || '4000', 10);
const BACKOFFS = [3000, 8000, 20000, 40000, 60000];

let zaiPromise = null;
async function getClient() {
  if (!zaiPromise) zaiPromise = ZAI.create();
  return zaiPromise;
}

const queue = [];
let busy = false;
let lastCallAt = 0;

async function processQueue() {
  if (busy) return;
  busy = true;
  try {
    while (queue.length) {
      const job = queue[0];
      const wait = Math.max(0, lastCallAt + MIN_INTERVAL - Date.now());
      if (wait > 0) await new Promise(r => setTimeout(r, wait));
      lastCallAt = Date.now();
      try {
        const zai = await getClient();
        const completion = await zai.chat.completions.create({
          messages: job.messages,
          thinking: { type: 'disabled' },
        });
        job.resolve(completion);
        const usage = completion.usage || {};
        console.error(`[proxy] ${new Date().toISOString()} ok model=${completion.model || '?'} `
          + `pt=${usage.prompt_tokens ?? '?'} ct=${usage.completion_tokens ?? '?'} `
          + `chars=${job.messages.map(m => (m.content || '').length).join(',')}`);
      } catch (error) {
        const message = String(error && error.message || error);
        const retryable = /429|Too many requests|rate/i.test(message) || /status 5\d\d/.test(message);
        if (retryable && job.attempt < BACKOFFS.length) {
          const delay = BACKOFFS[job.attempt++];
          console.error(`[proxy] ${new Date().toISOString()} retry ${job.attempt}/${BACKOFFS.length} `
            + `in ${delay}ms after: ${message.slice(0, 120)}`);
          queue.push(queue.shift()); // requeue at the end
          await new Promise(r => setTimeout(r, delay));
          continue;
        }
        job.reject(error);
        console.error(`[proxy] ${new Date().toISOString()} ERROR ${message.slice(0, 200)}`);
      } finally {
        if (queue[0] === job) queue.shift();
      }
    }
  } finally {
    busy = false;
  }
}

const server = http.createServer(async (req, res) => {
  if (req.method !== 'POST' || !req.url.replace(/\/$/, '').endsWith('/chat/completions')) {
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: { message: 'not found' } }));
    return;
  }
  let body = '';
  for await (const chunk of req) body += chunk;
  let payload;
  try {
    payload = JSON.parse(body);
  } catch {
    res.writeHead(400, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: { message: 'invalid json' } }));
    return;
  }
  const messages = Array.isArray(payload.messages) ? payload.messages : [];
  const job = { messages, attempt: 0, resolve: null, reject: null };
  const completion = await new Promise((resolve, reject) => {
    job.resolve = resolve;
    job.reject = reject;
    queue.push(job);
    processQueue();
  }).catch(error => ({ __error: error }));
  if (completion.__error) {
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: { message: String(completion.__error.message || completion.__error) } }));
    return;
  }
  const choice = completion.choices && completion.choices[0];
  const content = choice && choice.message ? choice.message.content : '';
  const usage = completion.usage || {};
  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({
    id: completion.id || 'local-proxy',
    object: 'chat.completion',
    created: completion.created || Math.floor(Date.now() / 1000),
    model: completion.model || 'glm-4-plus',
    choices: [{ index: 0, message: { role: 'assistant', content }, finish_reason: 'stop' }],
    usage: {
      prompt_tokens: usage.prompt_tokens ?? null,
      completion_tokens: usage.completion_tokens ?? null,
      total_tokens: usage.total_tokens ?? null,
    },
  }));
});

server.listen(PORT, HOST, () => {
  console.error(`[proxy] listening on http://${HOST}:${PORT}/v1/chat/completions `
    + `min_interval=${MIN_INTERVAL}ms`);
});
