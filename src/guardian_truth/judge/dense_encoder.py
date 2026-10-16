"""Local multilingual sentence encoder for the u2_dense context (CPU, offline).

Pinned model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 at PINNED_REVISION, loaded with
transformers + torch from local files only (local_files_only, HF offline variables); no network at run time.
Mean pooling over the attention mask, L2-normalised. The real input limit is max_seq_length of
sentence_bert_config.json (128 tokens for this model), not the position-embedding size: longer texts are
split into windows of that size, at most max_windows per text (the vector is the normalised mean of its
windows; texts cut there are counted in stats['truncated_texts']). The model is loaded once per process,
identical texts are encoded once (cache by SHA-1, float32 arrays) and windows are encoded in batches.
A passed deadline raises EncoderBudgetExceeded; the caller turns it into a named fallback to lexical U2.

Implements the interface of guardian_truth.evidence_packer.embed.Embedder: name, encode(texts, *, is_query).
Embeddings only rank candidate units; they never decide admission, labels or hard findings.
"""
from __future__ import annotations

from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import time

PINNED_REPOSITORY = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
PINNED_REVISION = 'e8f8c211226b894fcb81acc59f3b34ba3efd5f42'
REQUIRED_FILES = ('config.json', 'model.safetensors', 'tokenizer.json', 'tokenizer_config.json',
                  'sentence_bert_config.json')
FETCH_PATTERNS = REQUIRED_FILES + ('special_tokens_map.json', 'modules.json', '1_Pooling/config.json')


class EncoderUnavailable(RuntimeError):
    """The pinned encoder cannot be loaded from local files (missing files or libraries)."""


class EncoderBudgetExceeded(RuntimeError):
    """The embedding deadline passed before every requested window was encoded."""


class LocalEncoder:
    def __init__(self, directory, *, threads=None, batch_size=32, max_windows=2):
        directory = Path(directory)
        missing = [name for name in REQUIRED_FILES if not (directory / name).is_file()]
        if missing:
            raise EncoderUnavailable('MISSING_FILES:' + ','.join(missing))
        os.environ.setdefault('HF_HUB_OFFLINE', '1')
        os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except Exception as error:  # noqa: BLE001 - reported as a named fallback
            raise EncoderUnavailable('LIBRARIES:%s: %s' % (type(error).__name__, error)) from error
        self.torch = torch
        torch.set_num_threads(int(threads or max(1, min(8, (os.cpu_count() or 2) // 2))))
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(str(directory), local_files_only=True)
            self.model = AutoModel.from_pretrained(str(directory), local_files_only=True).eval()
        except Exception as error:  # noqa: BLE001
            raise EncoderUnavailable('LOAD:%s: %s' % (type(error).__name__, error)) from error
        config = json.loads((directory / 'sentence_bert_config.json').read_text(encoding='utf-8'))
        positions = int(getattr(self.model.config, 'max_position_embeddings', 512))
        self.max_tokens = min(int(config.get('max_seq_length', 128)), positions - 2)
        self.batch_size, self.max_windows = int(batch_size), int(max_windows)
        self.name = 'paraphrase-multilingual-MiniLM-L12-v2@' + PINNED_REVISION[:12]
        self.deadline = None
        self._cache = {}
        self.stats = dict(texts=0, cache_hits=0, windows=0, truncated_texts=0, batches=0, seconds=0.0,
                          max_tokens=self.max_tokens)

    def _windows(self, text):
        # Let the tokenizer's native post-processor add the correct special tokens to every window.
        # Transformers 5 TokenizersBackend no longer exposes build_inputs_with_special_tokens.
        windows = self.tokenizer(text, add_special_tokens=True, truncation=True, max_length=self.max_tokens,
                                 return_overflowing_tokens=True)['input_ids']
        if len(windows) > self.max_windows:
            self.stats['truncated_texts'] += 1
            windows = windows[:self.max_windows]
        return windows

    def fits_one_window(self, text):
        """True when `text` with its special tokens fits ONE window (max_tokens): the encoder sees all of it."""
        try:
            ids = self.tokenizer(text, add_special_tokens=True, verbose=False)['input_ids']
        except TypeError:  # a tokenizer without the verbose switch
            ids = self.tokenizer(text, add_special_tokens=True)['input_ids']
        return len(ids) <= self.max_tokens

    def _encode_windows(self, windows):
        torch, out = self.torch, []
        pad = self.tokenizer.pad_token_id if self.tokenizer.pad_token_id is not None else 0
        for k in range(0, len(windows), self.batch_size):
            if self.deadline is not None and time.time() >= self.deadline:
                raise EncoderBudgetExceeded('EMBED_DEADLINE')
            chunk = windows[k:k + self.batch_size]
            width = max(len(c) for c in chunk)
            ids = torch.tensor([c + [pad] * (width - len(c)) for c in chunk])
            mask = torch.tensor([[1] * len(c) + [0] * (width - len(c)) for c in chunk])
            with torch.no_grad():
                hidden = self.model(input_ids=ids, attention_mask=mask).last_hidden_state
            pooled = (hidden * mask.unsqueeze(-1)).sum(1) / mask.sum(1, keepdim=True).clamp(min=1)
            out.extend(pooled.tolist())
            self.stats['batches'] += 1
        return out

    def encode(self, texts, *, is_query=False):
        started = time.perf_counter()
        try:
            keys = [hashlib.sha1(t.encode('utf-8', 'surrogatepass')).hexdigest() for t in texts]
            todo = [k for k in dict.fromkeys(keys) if k not in self._cache]
            self.stats['texts'] += len(texts)
            self.stats['cache_hits'] += len(texts) - len(todo)
            text_of = dict(zip(keys, texts))
            spans, windows = {}, []
            for key in todo:
                pieces = self._windows(text_of[key])
                spans[key] = (len(windows), len(windows) + len(pieces))
                windows.extend(pieces)
            self.stats['windows'] += len(windows)
            vectors = self._encode_windows(windows) if windows else []
            for key, (a, b) in spans.items():
                mean = [sum(col) / (b - a) for col in zip(*vectors[a:b])]
                norm = math.sqrt(sum(x * x for x in mean)) or 1.0
                self._cache[key] = array('f', (x / norm for x in mean))
            return [self._cache[k] for k in keys]
        finally:
            self.stats['seconds'] = round(self.stats['seconds'] + time.perf_counter() - started, 3)
