"""F6 LLM-FIRST EXTRACTION — frozen prompts and arm definitions.

Frozen BEFORE any F6 inference (anti-leakage directive section 18:
suite -> commit -> arms/prompts -> freeze -> commit -> inference ->
analysis). Prompts are written from the directive text and prior-phase
public knowledge only; no F6 result has been seen.

Arms (directive sections 4-14):
  A   raw LLM extractor, minimal grounding line   (ministral-14b)
  A2  raw LLM extractor, same prompt, codestral-latest (independent)
  Ag  raw Granite extractor (remote GPU; run when the gateway returns)
  B   raw LLM + strict source-grounding discipline (4 constraints)
  C   A + NLP coverage audit (stanza structural anchors)
  D   A + selective escalation (narrow resolver questions)
  E   two independent extractors (A vs A2), disagreement = uncertainty
  F   narrow judge over disputed points
  G   calibrated uncertainty / selective prediction (observable signals)
  H   multiple interpretations (Phi)
  I   verdict-aware escalation (edge-set agreement proxy)
"""

# ----------------------------------------------------------------- ARM A
# Minimal: raw policy (+ tools) + strict JSON schema. One grounding line
# (the directive's own requirement), no NLP artifacts in the input.
ARM_A_SYSTEM = """You are a semantic extraction engine for workplace policies. Read the RAW POLICY text and find every policy-relevant semantic mention: actions to perform, checks or verifications, states of affairs, recordings of events, communications, and references to earlier events.

For each mention return:
- quote: the exact substring of the policy text that expresses the mention, copied character by character;
- type: one of ACTION, CHECK, STATE, RECORD, COMMUNICATION, REFERENCE_TO_EVENT;
- predicate: the lemma of the action/state verb or the nominalization head;
- arguments: the salient participants bound to the source (role + span).

Types:
- ACTION: an action or operation to be performed (imperative, passive or participial clause).
- CHECK: a verification action over a state or event ("verify that X", "check that X", reading an instrument).
- STATE: a state of affairs or result condition ("the tank is full", "the filter was inspected" as an embedded state).
- RECORD: a recording action ("log", "record", "file", "archive", "sign").
- COMMUNICATION: a notification, report or confirmation to someone.
- REFERENCE_TO_EVENT: a noun phrase or pronoun referring to an event mentioned elsewhere ("the inspection", "this step", "it" as event reference).

Include nested content: when a check/record/communication verb embeds a clause ("Verify that the filter was inspected"), return BOTH the outer mention (type CHECK) and the embedded clause (type STATE or REFERENCE_TO_EVENT).
Return every distinct event-like mention, including passive, nominalized, participial and reported ones. Do not merge two mentions into one; return them separately.
Answer strictly as JSON:
{"mentions": [{"quote": "...", "type": "...", "predicate": "...", "arguments": [{"role": "object|actor|location|time|value", "quote": "..."}]}]}"""

ARM_A_USER_TMPL = """RAW POLICY:
\"{policy}\"

TOOL CATALOG (context only, not part of the policy text):
{tools}

Extract every policy-relevant semantic mention. Answer strictly as JSON."""


# ----------------------------------------------------------------- ARM B
# Strict source-grounding discipline (directive section 6).
ARM_B_SYSTEM = """You are a semantic extraction engine for workplace policies. Read the RAW POLICY text and find every policy-relevant semantic mention: actions, checks, states, recordings, communications, and references to earlier events.

HARD GROUNDING RULES (an answer violating any of them is invalid):
1. Every quote MUST be an exact substring of the policy text, copied character by character. Never paraphrase, never fix capitalization, never add or drop words.
2. The semantic interpretation of a mention must be readable from the quote itself (plus its sentence); do not use knowledge that is not in the policy.
3. The predicate must be locatable inside the quote.
4. Every argument quote must also be an exact substring of the policy text.

Types: ACTION (operation to perform), CHECK (verification over a state/event, instrument reading), STATE (state of affairs / result condition), RECORD (log/record/file/archive/sign), COMMUNICATION (notify/report/confirm to someone), REFERENCE_TO_EVENT (noun phrase or pronoun referring to an event mentioned elsewhere).

Include nested content: when a check/record/communication verb embeds a clause, return BOTH the outer mention and the embedded clause.
Return every distinct event-like mention, including passive, nominalized, participial and reported ones. Do not merge two mentions into one.
Answer strictly as JSON:
{"mentions": [{"quote": "...", "type": "...", "predicate": "...", "arguments": [{"role": "object|actor|location|time|value", "quote": "..."}]}]}"""

ARM_B_USER_TMPL = ARM_A_USER_TMPL


# ----------------------------------------------------------------- ARM D
# Selective escalation: narrow resolver questions (directive section 8).
ARM_D_RESOLVER_SYSTEM = """You resolve ONE narrow disputed point about a workplace policy. You see the RAW POLICY and the disputed point only. Do not re-extract the whole policy.

Answer with JSON only:
{"answer": "YES|NO|UNKNOWN", "evidence": "<exact substring of the policy that decides the point>", "interpretation": "<one short sentence>"}"""

ARM_D_RESOLVER_USER_TMPL = """RAW POLICY:
\"{policy}\"

DISPUTED POINT:
{question}"""


# ----------------------------------------------------------------- ARM F
# Narrow judge over two candidate interpretations (directive section 10).
ARM_F_JUDGE_SYSTEM = """You judge ONE narrow disputed point about a workplace policy. You see the RAW POLICY, two candidate interpretations, their exact source quotes, and the disputed point. Do not re-parse the whole policy.

Answer with JSON only:
{"choice": "A|B|BOTH_POSSIBLE|UNKNOWN", "evidence": "<exact substring of the policy that decides the point>", "reason": "<one short sentence>"}"""

ARM_F_JUDGE_USER_TMPL = """RAW POLICY:
\"{policy}\"

INTERPRETATION A: {interp_a}
  quotes: {quotes_a}

INTERPRETATION B: {interp_b}
  quotes: {quotes_b}

DISPUTED POINT:
{question}"""


# ------------------------------------------------------- models/endpoints
MODELS = {
    "mistral": "ministral-14b-latest",     # primary extractor (ARM A/B)
    "codestral": "codestral-latest",       # second extractor (A2/E),
                                            # escalation resolver (D)
    "granite": "granite-guardian-4.1-8b",  # remote GPU via gateway (Ag);
                                            # local transformers runner
                                            # (experiments/full21/
                                            # run_granite_modes.py style)
}

ARMS = ["A", "A2", "Ag", "B", "C", "D", "E", "F", "G", "H", "I"]
