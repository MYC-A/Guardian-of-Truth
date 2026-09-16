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
 * - returns an OpenAI-format completion with usage.
 */
import http from 'node:http';
import { createRequire } from 'node:module';

// Resolve the globally installed SDK (bun global install) by absolute path.
const require = createRequire(import.meta.url);
const module_ = require('/home/z/.bun/install/global/node_modules/z-ai-web-dev-sdk');
const ZAI = module_.default || module_;

const PORT = parseInt(process.env.ZAI_PROXY_PORT || '8010', 10);
const HOST = '127.0.0.1';

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
  try {
    const zai = await ZAI.create();
    const completion = await zai.chat.completions.create({
      messages,
      thinking: { type: 'disabled' },
    });
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
    console.error(`[proxy] ${new Date().toISOString()} ok model=${completion.model || '?'} prompt_chars=${JSON.stringify(messages.map(m => (m.content || '').length))}`);
  } catch (error) {
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: { message: String(error && error.message || error) } }));
    console.error(`[proxy] ${new Date().toISOString()} ERROR ${String(error && error.message || error)}`);
  }
});

server.listen(PORT, HOST, () => {
  console.error(`[proxy] listening on http://${HOST}:${PORT}/v1/chat/completions`);
});
