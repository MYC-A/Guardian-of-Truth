"""Sequential GPU lifecycle and resource measurements."""

from __future__ import annotations

from contextlib import contextmanager
import gc
import time


class ModelLifecycleManager:
    def __init__(self, device: str = "auto"):
        self.device = device
        self.records: list[dict] = []

    def resolved_device(self) -> str:
        if self.device != "auto":
            return self.device
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    @contextmanager
    def loaded(self, *, stage: str, model_name: str, loader):
        device = self.resolved_device()
        torch = None
        try:
            import torch as torch_module
            torch = torch_module
            if device.startswith("cuda"):
                torch.cuda.reset_peak_memory_stats()
        except ImportError:
            pass
        started = time.monotonic()
        model = loader(device)
        loaded = time.monotonic()
        record = {"stage": stage, "model": model_name, "device": device,
                  "load_duration_s": round(loaded - started, 6)}
        try:
            yield model, record
        finally:
            finished = time.monotonic()
            record["execution_duration_s"] = round(finished - loaded, 6)
            if torch is not None and device.startswith("cuda"):
                record["max_allocated_vram_bytes"] = int(torch.cuda.max_memory_allocated())
                record["max_reserved_vram_bytes"] = int(torch.cuda.max_memory_reserved())
            else:
                record["max_allocated_vram_bytes"] = 0
                record["max_reserved_vram_bytes"] = 0
            self.records.append(record)
            del model
            gc.collect()
            if torch is not None and device.startswith("cuda"):
                torch.cuda.empty_cache()
