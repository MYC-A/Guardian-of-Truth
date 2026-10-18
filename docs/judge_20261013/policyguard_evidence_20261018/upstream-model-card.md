---
library_name: transformers
license: apache-2.0
base_model: Qwen/Qwen3-4B-Instruct-2507
tags:
- agent
model-index:
- name: PolicyGuard
  results: []
language:
- en
datasets:
- Rakancorle1/PolicyGuardBench
metrics:
- accuracy
- f1
pipeline_tag: text-classification
---

# PolicyGuard 🧭

**PolicyGuard** is a lightweight guardrail model trained for **policy-trajectory violation detection** in autonomous web agents.  
It identifies whether an agent’s long-horizon trajectory complies with externally imposed or human-specified policies.  
Built on the **PolicyGuardBench** dataset, it achieves **high accuracy**, **cross-domain generalization**, and **remarkable efficiency** — proving that compact guardrails can be both **accurate** and **deployable**.

For more details, refer to our paper: *[Towards Policy-Compliant Agents: Learning Efficient Guardrails For Policy Violation Detection](https://arxiv.org/abs/2510.03485)*.
---

## 🧩 Key Objectives

1. **Detect policy violations** in agent trajectories (beyond single-turn safety).  
2. **Generalize across domains** (e.g., shopping, GitLab, Reddit, map, admin).  
3. **Enable prefix-based early detection** — anticipating violations before completion.  
4. **Optimize for inference efficiency** with a 4B-parameter model.

---

## ⚙️ Model Overview

- **Model name:** PolicyGuard-4B  
- **Base model:** [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)  
- **Training objective:** Binary classification of `violation` / `no-violation`  
- **Dataset:** [PolicyGuardBench](https://huggingface.co/datasets/Rakancorle1/PolicyGuardBench) — 60k policy–trajectory pairs  
- **License:** apache-2.0  
- **Input format:** concatenated policy + trajectory description  
- **Output format:** “violation” / “no violation”

---

## 📊 Benchmark Results

| Model | Type | Params | Accuracy | F1 | Latency (ms/example) |
|:------|:------|:-------:|:---------:|:----:|:--------------------:|
| **PolicyGuard-4B (ours)** | Guardrail | 4B | <u>0.9014</u> | <u>0.8759</u> | **22.5** |
| Llama-Guard-3-8B | Guardrail | 8B | 0.4246 | 0.5952 | 164.8 |
| Qwen-3-8B | Foundation | 8B | 0.6408 | 0.6407 | 115.8 |
| Llama-3.3-70B | Foundation | 70B | **0.9054** | **0.8883** | 305.0 |
| Gemini-1.5-Pro | Frontier | – | 0.8713 | 0.8502 | 596.1 |

➡️ **PolicyGuard-4B** achieves **near-frontier accuracy** at **<1/10 inference cost**, demonstrating that efficient, small-scale guardrails are feasible:contentReference[oaicite:1]{index=1}.

<!-- ---

## 🧠 Generalization & Early Detection

### Leave-One-Domain-Out (LODO)
| Setting | Accuracy | F1 |
|:--|:--:|:--:|
| In-Domain (avg.) | 0.9328 | 0.9322 |
| Out-of-Domain (avg.) | **0.9083** | **0.9086** |

### Prefix-Based Violation Detection
| Prefix Length | Avg. Accuracy |
|:---------------|:--------------:|
| N=1-5 | **85.3 %** |

🟩 Even when only the **first few actions** of an agent are available, PolicyGuard predicts upcoming violations with strong accuracy:contentReference[oaicite:2]{index=2}.

---

## ⚡ Efficiency Metrics

| Model | F1 | Latency (ms) | EA-F1 ↑ |
|:------|:--:|:--:|:--:|
| Llama-3.3-70B | 0.888 | 305 | 2.91 |
| Qwen2.5-72B | 0.861 | 205 | 4.20 |
| **PolicyGuard-4B (ours)** | **0.876** | **22.5** | **38.93** |

> The **Efficiency-Adjusted F1 (EA-F1)** jointly measures accuracy and latency, showing that PolicyGuard is **>10× more efficient** than larger baselines:contentReference[oaicite:3]{index=3}.

--- -->

## 🧰 How to Use

```python
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch, re

model_id = "Rakancorle1/PolicyGuard-4B"
tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForCausalLM.from_pretrained(model_id, device_map="auto")

def classify(policy, actions):
    if isinstance(actions, list):
        actions = "\n".join(actions)
    prompt = f"Policy: {policy}\n\nTrajectory Actions:\n{actions}\n\nOutput violation or no_violation."
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    outputs = model.generate(**inputs, max_new_tokens=4)
    text = tokenizer.decode(outputs[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True).lower()
    return "no_violation" if "no_violation" in text else "violation"

# Example
policy = "Do not submit a form without filling mandatory fields."
actions = ["Open form page", "Click submit without input"]
print(classify(policy, actions))
# -> 'violation'
```