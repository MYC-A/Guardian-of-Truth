"""TruLens AUTHOR RAG prompts via pinned transparent template-only adapter.

Feedback provider replaced with the existing budgeted Mistral chat backend.
This is an adapted feedback executor, not a native TruLens evaluation run.
"""
import ast
import hashlib
from inspect import cleandoc
import json
from pathlib import Path
import types
import urllib.request
from modular_common import RESULTS, write


def templates():
    folder = Path('/workspace/guardian/third_party_modular_20261002/trulens_templates')
    folder.mkdir(parents=True, exist_ok=True)
    receipt = folder / 'receipt.json'
    if receipt.exists():
        info = json.loads(receipt.read_text())
    else:
        with urllib.request.urlopen('https://api.github.com/repos/truera/trulens/commits/main', timeout=30) as r:
            revision = json.load(r)['sha']
        info = {'revision': revision, 'paths': {}}
        for name in ('base.py', 'rag.py'):
            url = f'https://raw.githubusercontent.com/truera/trulens/{revision}/src/feedback/trulens/feedback/templates/{name}'
            with urllib.request.urlopen(url, timeout=30) as r:
                content = r.read()
            (folder / name).write_bytes(content)
            info['paths'][name] = {'url': url, 'sha256': hashlib.sha256(content).hexdigest()}
        write(receipt, info)
    source = (folder / 'rag.py').read_text()
    if hashlib.sha256(source.encode()).hexdigest() != info['paths']['rag.py']['sha256']:
        raise ValueError('author_template_sha_mismatch')
    # These bases carry metadata; prompts are evaluated exactly as authored.
    class Meta: pass
    class Space:
        name = 'LIKERT_0_3'
        value = (0, 3)
    namespace = {'cleandoc': cleandoc, 'ClassVar': __import__('typing').ClassVar,
                 'Semantics': type('Semantics', (), {}), 'WithPrompt': type('WithPrompt', (), {}),
                 'CriteriaOutputSpaceMixin': type('CriteriaOutputSpaceMixin', (), {}),
                 'OutputSpace': types.SimpleNamespace(LIKERT_0_3=Space()),
                 'LIKERT_0_3_PROMPT': '0, 1, 2, or 3', 'BINARY_0_1_PROMPT': '0 or 1'}
    selected = [node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and
                node.name in ('Relevance', 'Groundedness', 'ContextRelevance', 'PromptResponseRelevance')]
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(folder / 'rag.py'), 'exec'), namespace)
    return {key: namespace[key] for key in ('Groundedness', 'ContextRelevance', 'PromptResponseRelevance')}, info


def feedback(llm, model, query, context, answer, *, caller):
    classes, provenance = templates()
    dimensions = [('context_relevance', 'ContextRelevance', {'question': query, 'context': context}),
                  ('groundedness', 'Groundedness', {'premise': context, 'hypothesis': answer}),
                  ('answer_relevance', 'PromptResponseRelevance', {'prompt': query, 'response': answer})]
    result = {'adapter': 'TruLens-author-template-port/1', 'provenance': provenance,
              'query': query, 'context': context, 'answer': answer, 'dimensions': {}}
    for label, name, fields in dimensions:
        template = classes[name]
        raw = llm.chat(model, [{'role': 'system', 'content': template.system_prompt},
                              {'role': 'user', 'content': template.user_prompt.format(**fields)}],
                       max_tokens=700, temperature=0, json_mode=False,
                       transport_retries=0, caller=caller + '/' + label)
        parsed = llm.extract_json(raw.get('content'))
        try:
            score = parsed.get('score') if isinstance(parsed, dict) else int((raw.get('content') or '').strip())
        except (ValueError, TypeError):
            score = None
        valid = type(score) is int and 0 <= score <= 3
        result['dimensions'][label] = {'score': score if valid else None,
                                     'status': 'MODEL_FEEDBACK' if valid else 'INVALID', 'raw': raw}
    result['coverage'] = {'conditions_and_exceptions_fully_checked': False,
                          'latest_state_proven': False, 'warning': 'Triad score does not certify policy completeness or target correctness.'}
    return result
