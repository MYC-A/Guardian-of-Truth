FROM ubuntu:24.04
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 \
    PYTHONHOME=/app/runtime/python LD_LIBRARY_PATH=/app/runtime/lib \
    GUARDIAN_BUNDLED_PYTHON=1
WORKDIR /app
COPY . /app
USER 65534:65534
ENTRYPOINT ["/app/runtime/lib/ld-linux-x86-64.so.2", "--library-path", "/app/runtime/lib", "/app/runtime/python/bin/python3.12", "-X", "utf8", "/app/scripts/predict.py"]
