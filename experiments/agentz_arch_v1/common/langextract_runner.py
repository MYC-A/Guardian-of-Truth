"""Run Google LangExtract with the Ollama-shim in-process (background thread).
The shim proxies to z-ai-web-dev-sdk (GLM API) with file cache. This makes
LangExtract perform its genuine extraction loop (prompting, parsing, fuzzy
char-offset alignment) against an API model - documented as GLM-API, not local.
"""
import threading, time, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import http.server

_shim_started = False

def _start_shim_once():
    global _shim_started
    if _shim_started:
        return
    import ollama_shim
    srv = http.server.HTTPServer(("127.0.0.1", 11434), ollama_shim.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    _shim_started = True
    time.sleep(0.2)


def extract(text, prompt_description, examples, max_chars=12000, timeout=300):
    """Returns list of {class, text, attributes, char_start, char_end, aligned_text}."""
    import langextract as lx
    from langextract import factory
    _start_shim_once()
    # long inputs: truncate conservatively around the policy section
    t = text
    if len(t) > max_chars:
        i = t.find("<policy>")
        if i >= 0:
            t = t[i:i + max_chars]
        else:
            t = t[:max_chars]
    config = factory.ModelConfig(
        model_id="qwen-glm", provider="ollama",
        provider_kwargs={"model_url": "http://127.0.0.1:11434", "timeout": timeout},
    )
    doc = lx.extract(
        text_or_documents=t,
        prompt_description=prompt_description,
        examples=examples,
        config=config,
    )
    out = []
    for e in doc.extractions or []:
        ci = e.char_interval
        s = getattr(ci, "start_pos", None) if ci else None
        en = getattr(ci, "end_pos", None) if ci else None
        out.append({
            "class": e.extraction_class,
            "text": e.extraction_text,
            "attributes": dict(e.attributes or {}),
            "char_start": s, "char_end": en,
            "aligned_text": t[s:en] if (s is not None and en is not None and 0 <= s < en <= len(t)) else None,
        })
    return out


RULE_EXAMPLES = [
    {
        "text": "Возвраты до 5 000 руб. выполняются сразу. Исключение: если счёт заморожен, требуется проверка.",
        "extractions": [
            {"extraction_class": "rule_element", "extraction_text": "Возвраты до 5 000 руб. выполняются сразу",
             "attributes": {"element_type": "permission", "threshold": 5000}},
            {"extraction_class": "rule_element", "extraction_text": "если счёт заморожен, требуется проверка",
             "attributes": {"element_type": "exception", "condition": "account_frozen"}},
        ],
    },
    {
        "text": "Refunds above 10,000 RUB require manager approval before execution.",
        "extractions": [
            {"extraction_class": "rule_element", "extraction_text": "Refunds above 10,000 RUB require manager approval before execution",
             "attributes": {"element_type": "obligation", "action": "refund", "threshold": 10000, "required": "manager_approval"}},
        ],
    },
]


def rule_element_examples():
    import langextract as lx
    return [lx.data.ExampleData(
        text=ex["text"],
        extractions=[lx.data.Extraction(**x) for x in ex["extractions"]])
        for ex in RULE_EXAMPLES]
