# Ten adjacent projects: what actually transfers to Guardian

Reviewed repository documentation and, for the two closest or most ambitious
claims, source code. This is an architectural audit, not a benchmark of those
packages. The question is whether they resolve Guardian's observed ambiguity:
`record_audit(...)->{"status":"completed"}` shares an entity and a success
status with a claim that a *replacement* was completed, but does not prove it.

| Project | What it checks | Useful here | Boundary |
| --- | --- | --- | --- |
| [AgentDojo](https://github.com/ethz-spylab/agentdojo) | Agent runs in simulated apps; task-specific utility and attack-security predicates can inspect output, environment state and call trace ([code](https://github.com/ethz-spylab/agentdojo/blob/main/src/agentdojo/task_suite/task_suite.py)). | Recorded trajectories and state-backed attack/benign pairs for external stress tests. Keep a separate count of benign runs flagged. | Its gold checks are authored per task with access to environment state. They are not a universal offline policy judge. |
| [ToolEmu](https://github.com/ryoungj/ToolEmu) | An LLM emulates tool responses and LLM judges rate safety/helpfulness; authors ship 36 toolkits and 144 cases. | Generate rare candidate trajectories, especially related-tool and partial-success distractors. | Emulator and judge outputs are synthetic proposals, not independently verified ground truth. Its published setup expects a separate PromptCoder package and provider API keys. |
| [ToolSandbox](https://github.com/apple-aiml-research/ToolSandbox) | Tools mutate a simulated state; milestone DAGs compare state snapshots, trace entries and response in order. It can scramble tool names and add distractors. | Best test design for **postcondition vs tool-call success**. Derive gold from controlled state changes; perturb names, descriptions and order. | Guardian normally receives a historical text trace, not the simulator's authoritative state. State-oracle checks cannot simply be copied into inference. |
| [Invariant](https://github.com/invariantlabs-ai/invariant) | An authored policy DSL matches `Message`, `ToolCall`, `ToolOutput`, order and argument patterns on a trace. Runs locally via `LocalPolicy` as well as through a gateway. | Typed event representation, `tool_call_id` pairing, compact executable rules for known obligations. | Its examples require someone to author the rule and specify the relevant tool/arguments. DSL execution does not infer that audit success entails replacement. |
| [Snyk Agent Scan](https://github.com/snyk/agent-scan) | Scans agent/MCP configurations, skill text and tool descriptions, with local checks and Snyk API analysis. | Tool-catalog hygiene and suspicious description screening, if those become a separate threat model. | Its described scan analyzes tool metadata; the README says it does not store or log tool-call contents/results. This scan does not decide our historical claim/result question. |
| [NeMo Guardrails](https://github.com/NVIDIA-NeMo/Guardrails) | Colang and configured rails control dialogue, actions, input and output at runtime. | Ideas for explicit order/precondition flows if Guardian can control the agent. | Requires authored flows/integration; a passive competition judge cannot assume those flows or world state exist. |
| [Guardrails AI](https://github.com/guardrails-ai/guardrails) | Structured output, validators and on-failure actions, including deterministic and LLM validators. | Schema validation for proposed frames, quotes and typed effect contracts. | It validates specified predicates; it does not supply missing tool-effect semantics. Re-asking a model is not proof. |
| [Formal RV for tool-using agents](https://github.com/nikos-kekatos/formal-rv-tool-using-llm-agents) | Offline MFOTL/MonPoly replay on AgentDojo/STAC/R-Judge with explicit obligation and provenance experiments. | Strongest source for entity-parametric temporal checks and structured-field provenance. Its [results](https://github.com/nikos-kekatos/formal-rv-tool-using-llm-agents/blob/main/RESULTS.md) explicitly report detection and benign firing separately. | Authors themselves say many corpus obligations reduce to typed-action detection because approvals/timestamps are absent. [Generic code](https://github.com/nikos-kekatos/formal-rv-tool-using-llm-agents/blob/main/code/stac_rv.py) types actions from name substrings and treats *any* previous approval as enough, without matching entity. In a local control, approval for A suppressed a replacement action for B. Published AgentDojo result is 1354/1931 successful attacks flagged and 36/123 benign runs flagged; it is not Guardian accuracy. |
| [Gravit Epistemic Verifier](https://github.com/GravitOpenNetwork/gravit-epistemic-verifier) | Finance-oriented intent/action scoring, policy score, hashes and consensus. | Hash-linked provenance is relevant as an audit property. | The [semantic scorer](https://github.com/GravitOpenNetwork/gravit-epistemic-verifier/blob/main/gravit_verifier/semantic.py) uses token overlap and keyword boosts; its [policy scorer](https://github.com/GravitOpenNetwork/gravit-epistemic-verifier/blob/main/gravit_verifier/policy.py) uses keyword increments. In a local control, `replacement completed case CS-408` versus `audit completed case CS-408` scored 0.616 on semantics, above the engine's 0.5 semantic threshold. This does not prove that the whole engine accepts that pair, but it rules out that semantic component as a solution to our counterexample. The README's performance claims do not establish transfer to Guardian. |
| [Hefesto Code Guardian](https://github.com/artvepa80/Agents-Hefesto) | Static code/security/packaging drift checks in source repositories. | Maybe useful to lint our own repository. | It does not verify agent dialogue policy or business tool effects. |

## Recommendation

The most valuable distinction is **authoritative post-state** versus a trace
that merely reports `status: completed`. ToolSandbox and AgentDojo can create
state-backed test oracles, but Guardian has only the latter at inference.
Invariant and MFOTL can verify event order and same-entity conditions once the
events have been typed; they cannot manufacture the missing meaning of a
generic status field. ToolEmu can propose hard cases, but its emulator must
not label them for final scoring without an independent state or human oracle.

The next implementation worth considering is a small evidence contract:
`claim_action`, `tool_effect`, `entity`, `call_id/pairing`, `outcome`,
`source_trust`, and explicit `postcondition` when one exists. A model may
propose these fields; code must verify source spans, identifiers, event order
and whether a stated postcondition is actually in the result. If the trace
only says generic `status: completed` and the tool's effect is not established,
the outcome is `UNKNOWN`. Test this first as a **false-positive refutation**
component on independent valid and invalid call pairs. Do not add a new OR/veto
arm to C1 based on these repositories alone.

## Local transfer status

The source-scoped part is implemented as `vnext/bound_tool_effects_v2.py` and
`vnext/ordered_effects_v1.py`, with 10 controlled trace variants and a small
state-backed audit/replacement pair in `tests/test_vnext_ordered_effects_v1.py`.
It uses application-authored exact T1 contracts, call/result entity joins and
same-entity order checks. Frozen T1 and the competition decision path remain
unchanged. The seven older contracts in `contracts/tool_effects_v1.json` do not
carry the full provider/schema identity required by vnext T1 and therefore
cannot be silently promoted into this layer. Independent real-case coverage
and benign false alarms remain unmeasured.
