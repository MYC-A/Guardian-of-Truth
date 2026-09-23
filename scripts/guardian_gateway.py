"""Pinned-TLS client for the existing Guardian Gateway 2.0.

Credentials live in ~/.guardian_gateway/{server.crt,token}, outside Git.
The client never prints or stores the token in job artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import time
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://57.129.48.249:8443"
EXPECTED_CERT_SHA256 = "00D64D5BC999F825BC6168ECD3B76E7DBFC96308535CA1035DCE5A1ECC7674E1"
HOME = Path.home() / ".guardian_gateway"


class GatewayError(RuntimeError):
    pass


class GuardianGateway:
    def __init__(self, *, base_url: str = BASE_URL,
                 cert_file: Path = HOME / "server.crt",
                 token_file: Path = HOME / "token"):
        if not cert_file.is_file() or not token_file.is_file():
            raise GatewayError("missing pinned certificate or token file in ~/.guardian_gateway")
        pem = cert_file.read_text(encoding="ascii")
        actual = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest().upper()
        if actual != EXPECTED_CERT_SHA256:
            raise GatewayError("saved TLS certificate fingerprint does not match expected pin")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.verify = str(cert_file)
        self._token = token_file.read_text(encoding="ascii").strip()
        self.session.headers["Authorization"] = "Bearer " + self._token

    def request(self, method: str, endpoint: str, *, params: dict | None = None,
                payload: dict | None = None, timeout: int = 60,
                authorized: bool = True) -> dict:
        if not endpoint.startswith("/"):
            raise ValueError("endpoint must start with /")
        session = self.session if authorized else requests.Session()
        if not authorized:
            session.verify = self.session.verify
        response = session.request(method, self.base_url + endpoint, params=params,
                                   json=payload, timeout=timeout)
        if not response.ok:
            # Do not echo a response body: gateways may repeat a request field.
            raise GatewayError(f"{method} {endpoint}: HTTP {response.status_code}")
        try:
            value = response.json()
        except ValueError as exc:
            raise GatewayError(f"{method} {endpoint}: invalid JSON response") from exc
        if not isinstance(value, dict):
            raise GatewayError(f"{method} {endpoint}: JSON response is not an object")
        return value

    def health(self) -> dict:
        return self.request("GET", "/health", authorized=False)

    def gpu(self) -> dict:
        return self.request("GET", "/gpu", timeout=90)

    def environment(self) -> dict:
        return self.request("GET", "/environment", timeout=90)

    def files(self, path: str = ".") -> dict:
        return self.request("GET", "/files", params={"path": path})

    def read_file(self, path: str) -> str:
        value = self.request("GET", "/files/content", params={"path": path})
        if not isinstance(value.get("content"), str):
            raise GatewayError("file read returned no text content")
        return value["content"]

    def write_file(self, path: str, content: str) -> dict:
        return self.request("PUT", "/files/content", payload={"path": path,
                                                                "content": content})

    def delete_file(self, path: str) -> dict:
        return self.request("DELETE", "/files/content", params={"path": path})

    def submit(self, argv: list[str], *, cwd: str = ".",
               timeout: int = 120) -> dict:
        if not argv or not all(isinstance(part, str) for part in argv):
            raise ValueError("exec argv must be a non-empty string list")
        value = self.request("POST", "/jobs", payload={"operation": "exec",
                    "argv": argv, "cwd": cwd, "timeout": timeout}, timeout=90)
        job_id = value.get("job_id")
        if job_id:
            HOME.mkdir(parents=True, exist_ok=True)
            with (HOME / "jobs.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"job_id": job_id, "argv": argv,
                                          "cwd": cwd, "submitted_at": time.time()}) + "\n")
        return value

    def run_python(self, *args: str, cwd: str = "Guardian-of-Truth",
                   timeout: int = 120) -> dict:
        return self.submit(["/mnt/data/guardian/venv/bin/python", *args],
                           cwd=cwd, timeout=timeout)

    def run_pytest(self, *args: str, cwd: str = "Guardian-of-Truth",
                   timeout: int = 600) -> dict:
        return self.run_python("-m", "pytest", *args, cwd=cwd, timeout=timeout)

    def run_git(self, *args: str, cwd: str = "Guardian-of-Truth",
                timeout: int = 120) -> dict:
        return self.submit(["git", *args], cwd=cwd, timeout=timeout)

    def status(self, job_id: str) -> dict:
        return self.request("GET", f"/jobs/{job_id}")

    def logs(self, job_id: str) -> dict:
        return self.request("GET", f"/jobs/{job_id}/logs")

    def cancel(self, job_id: str) -> dict:
        return self.request("POST", f"/jobs/{job_id}/cancel")

    def wait(self, job_id: str, *, interval: int = 30,
             deadline: int = 3600) -> dict:
        end = time.monotonic() + deadline
        while True:
            status = self.status(job_id)
            if status.get("status") in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"}:
                return status
            if time.monotonic() >= end:
                raise TimeoutError(f"job {job_id} still running after {deadline}s")
            time.sleep(interval)


def safe_view(value: Any, secret: str) -> Any:
    """Keep CLI output compact and avoid accidental credential fields."""
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if any(word in k.lower() for word in
                ("token", "password", "secret", "authorization", "api_key"))
                else safe_view(v, secret)) for k, v in value.items()}
    if isinstance(value, list):
        return [safe_view(item, secret) for item in value]
    if isinstance(value, str) and secret:
        return value.replace(secret, "[REDACTED]")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("health", "gpu", "environment"):
        sub.add_parser(name)
    files = sub.add_parser("files")
    files.add_argument("path", nargs="?", default=".")
    read = sub.add_parser("read")
    read.add_argument("path")
    write = sub.add_parser("write")
    write.add_argument("path")
    write.add_argument("local_file", type=Path)
    delete = sub.add_parser("delete")
    delete.add_argument("path")
    submit = sub.add_parser("submit")
    submit.add_argument("spec_file", type=Path,
                        help="JSON with argv, cwd and timeout; no shell string")
    for name in ("status", "logs", "cancel", "wait"):
        command = sub.add_parser(name)
        command.add_argument("job_id")
    args = parser.parse_args()
    gateway = GuardianGateway()
    if args.command == "health":
        value = gateway.health()
    elif args.command == "gpu":
        value = gateway.gpu()
    elif args.command == "environment":
        value = gateway.environment()
    elif args.command == "files":
        value = gateway.files(args.path)
    elif args.command == "read":
        if re.search(r"(?i)(secret|token|credential|\.env|auth)", args.path):
            raise GatewayError("CLI refuses to display a possible credential file")
        value = {"path": args.path, "content": gateway.read_file(args.path)}
    elif args.command == "write":
        value = gateway.write_file(args.path,
                                   args.local_file.read_text(encoding="utf-8"))
    elif args.command == "delete":
        value = gateway.delete_file(args.path)
    elif args.command == "submit":
        spec = json.loads(args.spec_file.read_text(encoding="utf-8"))
        value = gateway.submit(spec["argv"], cwd=spec.get("cwd", "."),
                               timeout=spec.get("timeout", 120))
    elif args.command == "status":
        value = gateway.status(args.job_id)
    elif args.command == "logs":
        value = gateway.logs(args.job_id)
    elif args.command == "cancel":
        value = gateway.cancel(args.job_id)
    else:
        value = gateway.wait(args.job_id)
    print(json.dumps(safe_view(value, gateway._token), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
