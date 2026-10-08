# Bundled model and engine

- Model: https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF
- Base: https://huggingface.co/Qwen/Qwen3.8-27B
- Historical checkpoint alias:71bc7b627595, Q8_0.
- Actual GGUF SHA256:aab65c67ef0dad127960efef9247f1832bca105faa1c7a052cc039b223cf86a1
- GGUF metadata:general.name=Qwen3.8-27B; architecture=qwen35;64 blocks;
  general.license=apache-2.0; file_type7 (Q8_0).
- llama.cpp source:f498f864fbc0472004ee1c3616c1188c68eb157f
  https://github.com/ggml-org/llama.cpp/commit/f498f864fbc0472004ee1c3616c1188c68eb157f
- Actual `llama-server --version`:0.6.0-dev, build1, f498f86, GNU13.3.0 Linuxx86_64.

The historical model alias ends `llamacpp-b11459`; keep it for unchanged B2 wire
comparison, but actual engine identity is the source/binary hash in MANIFEST.
Do not mistake that alias for independently authenticated engine build metadata.

These model/engine licenses were downloaded from their primary repositories on
2026-10-08. Python package licenses accompany their .dist-info contents. Host
NVIDIA driver is not redistributed.
