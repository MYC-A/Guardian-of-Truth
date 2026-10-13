"""Judge prompt, deterministic trimming, rendering with the model's chat template."""
from __future__ import annotations

import re

USER_MARK = '⟦USER⟧'
OMIT = '\n[... {n} characters of the earlier conversation are omitted to fit the context window ...]\n'
RESCUE_HEAD = '[Excerpts from the omitted part that mention identifiers used in the turn under review:]\n'
RESCUE_TAIL = '\n[... end of excerpts ...]\n'
TEXT_ID = re.compile(r'(?<![\w#-])#?(?=[A-Za-z0-9_\-]*[A-Za-z])(?=[A-Za-z0-9_\-]*\d)'
                     r'[A-Za-z0-9][A-Za-z0-9_\-]{4,63}(?![\w-])')
RESPONSE_CHARS = 30000

JUDGE_SYSTEM = """You audit one turn of a customer-service AI agent for contextual hallucinations.

You receive the full transcript the agent saw (system instructions with the domain <policy> and the [AVAILABLE TOOLS] list, user messages, earlier agent turns, tool calls and tool results) and ONE agent turn under review: its text and/or its tool calls.

Answer YES if the turn under review contains at least one statement or action not grounded in the transcript:
- Contradiction: a number, date, price, amount, name, ID, status or other value that does not match the data, instructions or tool results; a reference to an entity, field or value that does not exist in the data; a distortion of them.
- Unsupported: a fact, number, reason, entity, condition or result that cannot be derived from the transcript, including claiming that an action was done or succeeded without a tool result showing it.
- Tool misuse: calling a tool that is not in [AVAILABLE TOOLS], or with arguments (IDs, items, amounts, options) not supported by the transcript or wrong for the entity being handled.
- Policy violation that changes the outcome: an action the policy forbids in the current state (missing required verification, explicit user confirmation, eligibility, dates, limits, preconditions), or telling the user something contrary to the policy.
- False refusal or premature escalation: saying something is impossible, refusing, or transferring to a human while the policy and the available tools still allow the agent to proceed.

Answer NO if the turn is correct: faithful paraphrasing, aggregation, filtering, sorting, rounding or formatting of transcript data; correct arithmetic on transcript values; asking a clarifying or confirmation question; wording issues that do not change the outcome or the data the user sees.

Litmus test: would this change the outcome or the data the user sees? If yes or potentially yes, answer YES.
Judge only the turn under review. Earlier turns are context; an earlier mistake counts only if this turn repeats it or relies on it."""

QUESTION = ('Does the turn under review contain at least one hallucination as defined above? '
            'Answer with exactly one word: YES or NO.')


def system_block(prompt):
    i = prompt.find(USER_MARK)
    return prompt[:i] if i > 0 else ''


def user_message(prompt_text, response, hints):
    parts = ['<transcript>\n', prompt_text, '\n</transcript>\n\n<turn_under_review>\n', response,
             '\n</turn_under_review>\n\n']
    if hints:
        parts += ['Automatic pre-checks (heuristic, may be false alarms; verify each against the transcript):\n',
                  '\n'.join('- ' + h for h in hints), '\n\n']
    parts.append(QUESTION)
    return ''.join(parts)


def render(tok, prompt_text, response, hints):
    messages = [{'role': 'system', 'content': JUDGE_SYSTEM},
                {'role': 'user', 'content': user_message(prompt_text, response, hints)}]
    try:
        return tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                       enable_thinking=False)
    except TypeError:
        return tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


def count_tokens(tok, text):
    return len(tok(text, add_special_tokens=False)['input_ids'])


def headtail(text, limit):
    if len(text) <= limit:
        return text
    keep = max(0, limit - 120)
    return text[:keep // 2] + OMIT.format(n=len(text) - keep) + text[len(text) - (keep - keep // 2):]


def trim_prompt(prompt, response, budget):
    """Keep the system block (policy + tools), the latest part of the dialogue, and lines from the
    omitted middle that mention identifiers used in the turn under review."""
    if len(prompt) <= budget:
        return prompt
    head = system_block(prompt)
    rest = prompt[len(head):]
    if len(head) > budget * 0.6:
        head = headtail(head, int(budget * 0.6))
    room = max(budget - len(head), 1000)
    tail = rest[-int(room * 0.8):]
    cut = tail.find('\n')
    if 0 <= cut < 2000:
        tail = tail[cut + 1:]
    middle = rest[:len(rest) - len(tail)]
    wanted = {t.lstrip('#').lower() for t in TEXT_ID.findall(response)}
    spare, rescued = room - len(tail) - len(RESCUE_HEAD) - len(RESCUE_TAIL), []
    if wanted and spare > 500:
        for line in middle.splitlines():
            low = line.lower()
            if any(w in low for w in wanted):
                piece = line if len(line) <= 3000 else line[:3000] + ' [...]'
                if len(piece) + 1 > spare:
                    break
                rescued.append(piece)
                spare -= len(piece) + 1
    omitted = max(len(middle) - sum(len(r) + 1 for r in rescued), 0)
    body = head + OMIT.format(n=omitted)
    if rescued:
        body += RESCUE_HEAD + '\n'.join(rescued) + RESCUE_TAIL
    return body + tail


def build_prompt(tok, row, cap_tokens):
    """-> (text, n_tokens, trimmed). n_tokens can exceed cap_tokens only in pathological cases;
    the caller must skip such a row instead of sending it."""
    prompt, hints = row['prompt'], row.get('hints') or []
    response = headtail(row['response'], RESPONSE_CHARS)
    text = render(tok, prompt, response, hints)
    n = count_tokens(tok, text)
    if n <= cap_tokens:
        return text, n, False
    ratio = len(text) / max(n, 1)
    budget = len(prompt) - int((n - cap_tokens) * ratio * 1.08) - 500
    for _ in range(5):
        budget = max(budget, 2000)
        text = render(tok, trim_prompt(prompt, response, budget), response, hints)
        n = count_tokens(tok, text)
        if n <= cap_tokens or budget == 2000:
            break
        budget = int(budget * cap_tokens / n * 0.95)
    if n > cap_tokens:
        text = render(tok, headtail(prompt, int(cap_tokens * ratio * 0.5)),
                      headtail(response, int(cap_tokens * ratio * 0.3)), [])
        n = count_tokens(tok, text)
    return text, n, True
