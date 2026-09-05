# Explicit declarative rules

`guardian_truth.rules.check_rules(history, candidate, graph)` returns
`(list[Finding], list[str])`: mechanically proved precondition violations and
unresolved conditions. It does not infer policy from prose, consult a model,
execute expressions, access the network, or use the machine clock. A passing
rule does not establish that the entire response is safe or correct.

Only a single complete `[GUARDIAN_RULES] ... [/GUARDIAN_RULES]` block in a SYSTEM
text event in the prompt is authoritative. USER, ASSISTANT, result, and candidate
blocks cannot supply policies. Multiple blocks, duplicate JSON keys or rule IDs,
unsupported versions/operators/keys, invalid JSON, and incomplete blocks make
the policy unresolved. The entire policy must validate before any finding can
be emitted. Arbitrary surrounding prose is not interpreted or claimed covered.

```json
{
  "version": 1,
  "context": {"actor_id": "person-A", "today": "2026-09-05"},
  "rules": [
    {
      "id": "owner-only",
      "tool": "modify_record",
      "when": {"eq": [{"arg": ["mode"]}, {"literal": "commit"}]},
      "except": {"eq": [{"arg": ["override"]}, {"literal": true}]},
      "require": {
        "eq": [
          {"fact": {
            "tool": "inspect_record",
            "role": "assistant",
            "field": "owner_id",
            "entity": {"record_id": {"arg": ["record_id"]}}
          }},
          {"context": ["actor_id"]}
        ]
      }
    }
  ]
}
```

Wrap this JSON in the delimiters inside the SYSTEM message. Tool names, IDs,
fields, and values are arbitrary exact strings; no domain-specific aliases or
dataset-dependent checks exist. `context` is optional and contains only explicit
policy data. A rule requires `id`, `tool`, and `require`; `when` defaults to true,
and `except` defaults to false. Unknown applicability or exception status blocks
a hard finding. Explicitly true exceptions and false applicability skip a rule.
In the example a missing `override` is unknown, not implicitly false; callers
should either provide it or omit the exception clause from their policy.

Expressions are boolean constants or single-key objects:

| Expression | Meaning |
| --- | --- |
| `{"all": [expr, ...]}` | False if any child is false; otherwise unknown if any is unknown |
| `{"any": [expr, ...]}` | True if any child is true; otherwise unknown if any is unknown |
| `{"not": expr}` | Negation preserving unknown |
| `{"eq": [a,b]}`, `{"ne": [a,b]}` | Exact typed JSON equality/inequality |
| `lt`, `le`, `gt`, `ge` | Same-type string/integer/float order; no boolean or mixed-type coercion |
| `in`, `not_in` | Exact typed membership in a literal or resolved JSON list |
| `date_lt`, `date_le`, `date_gt`, `date_ge` | Calendar comparison of valid `YYYY-MM-DD` strings |

Each binary comparison takes exactly two operands. Operands are
`{"literal": value}`, `{"arg": [path, ...]}`, `{"context": [path, ...]}`, or
`{"fact": selector}`. Paths contain object keys and nonnegative array indices.
Missing paths are unknown. Literals can be any finite JSON value. Equality keeps
booleans, integers, floats, strings, and null distinct, including inside objects
and lists. Lists in `all`/`any` must be nonempty. Dates require explicitly supplied
arguments, facts, or context; there is no implicit "now".

A fact selector requires `tool`, `role` (`assistant` or `user`), `field`, and a
nonempty `entity` map. Each entity binding is a literal, argument, or context
operand resolving to a string or integer. An optional `container` is the exact
sequence of object keys preceding the leaf, excluding array indices. For example
`["records"]` selects leaves within the records array. Entity identities and
version chains use the existing evidence graph, which recognizes `_id` and
`_number` identity fields and explicit date selectors. Arbitrary record schemas
without these anchors remain unknown.

Resolution requires one version lineage: same tool, requesting role, structural
container, field, and full entity scope. Different tools, roles, dates, owners,
or containers never overwrite each other. Multiple matching lineages, conflicting
simultaneous values, anonymous array observations, missing values, unsupported
sources, and absent entity scope remain unknown. Within a unique lineage the
latest observation is used. A newer partial observation in the selected container
that omits the requested field, or a newer unparsed result for that tool/role,
makes the value unknown. Omission does not establish persistence or deletion.
These observations are evidence under the explicit policy, not independent proof
of current external state or real-world authorization.

Findings cite the delimited policy, candidate call, and all facts used by the
decisive predicates, including evidence for applicability and exceptions. Facts
must retain a valid source for the matching historical tool result. Unsupported
model-generated rules never become mechanically accepted policies.

The interpreter checks candidate assistant calls in sequence but has no transition
or effects language in version 1. Calls do not imply success. Candidate-authored
results never supply facts. After any earlier candidate assistant call, subsequent
fact operands are unknown because possible effects are unspecified; argument-only
rules can still be checked. `effects` and other unsupported clauses invalidate a
policy rather than silently ignoring constraints. This deliberately conservative
limit can be extended only with an explicit bounded transition model.

Bounds: one policy block up to 65,536 characters, 128 rules, 2,048 expression
nodes, expression depth 24, and operand paths of at most 24 segments. The entire
JSON tree is limited to 16,384 values and depth 72, including literals. This is a
small interpreter over structured data, with no `eval`, `exec`, templates,
imports, callbacks supplied by the policy, or external backend dependencies.
