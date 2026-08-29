#!/usr/bin/env python3
"""Small authenticated CubeSandbox execution adapter for Agent runtimes.

The adapter owns Cube credentials, sandbox identifiers, policy selection and
audit records. Agent plugins receive only opaque lease and sandbox references.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import html
import json
import os
import re
import signal
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePosixPath
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlparse

from cubesandbox import Sandbox


VERSION = "0.1.0"
MAX_BODY_BYTES = 1024 * 1024
MAX_COMMAND_BYTES = 16 * 1024
MAX_FILE_BYTES = 256 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
ALLOWED_FILE_ROOTS = ("/tmp", "/workspace")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


class AdapterError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AdapterConfig:
    token: str
    session_hmac_key: str
    template: str
    audit_log: str
    bind: str = "127.0.0.1"
    port: int = 18080
    sandbox_timeout_seconds: int = 300
    max_command_seconds: int = 120
    audit_ui: bool = False

    @classmethod
    def from_env(cls) -> "AdapterConfig":
        token = os.environ.get("CUBE_ADAPTER_TOKEN", "")
        if len(token) < 24:
            raise RuntimeError("CUBE_ADAPTER_TOKEN must contain at least 24 characters")
        session_hmac_key = os.environ.get("CUBE_ADAPTER_HMAC_KEY", "")
        if len(session_hmac_key) < 32:
            raise RuntimeError("CUBE_ADAPTER_HMAC_KEY must contain at least 32 characters")
        template = os.environ.get("CUBE_TEMPLATE_ID", "")
        if not template:
            raise RuntimeError("CUBE_TEMPLATE_ID is required")
        return cls(
            token=token,
            session_hmac_key=session_hmac_key,
            template=template,
            audit_log=os.environ.get(
                "CUBE_ADAPTER_AUDIT_LOG", "./cube-adapter-audit.jsonl"
            ),
            bind=os.environ.get("CUBE_ADAPTER_BIND", "127.0.0.1"),
            port=int(os.environ.get("CUBE_ADAPTER_PORT", "18080")),
            sandbox_timeout_seconds=int(
                os.environ.get("CUBE_ADAPTER_SANDBOX_TIMEOUT", "300")
            ),
            max_command_seconds=int(
                os.environ.get("CUBE_ADAPTER_MAX_COMMAND_SECONDS", "120")
            ),
            audit_ui=os.environ.get("CUBE_ADAPTER_AUDIT_UI", "0") == "1",
        )


@dataclass
class Lease:
    lease_ref: str
    runtime: str
    session_hash: str
    profile: str
    sandbox: Any
    sandbox_ref: str
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)


def _digest(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _request_id(value: Any) -> str:
    if isinstance(value, str) and REQUEST_ID_RE.fullmatch(value):
        return value
    return uuid.uuid4().hex[:16]


def _required_string(body: Dict[str, Any], key: str, maximum: int) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AdapterError(400, "invalid_request", f"{key} must be a non-empty string")
    if len(value.encode("utf-8")) > maximum:
        raise AdapterError(413, "value_too_large", f"{key} exceeds the size limit")
    return value


def _bounded_string(body: Dict[str, Any], key: str, maximum: int) -> str:
    value = body.get(key)
    if not isinstance(value, str):
        raise AdapterError(400, "invalid_request", f"{key} must be a string")
    if len(value.encode("utf-8")) > maximum:
        raise AdapterError(413, "value_too_large", f"{key} exceeds the size limit")
    return value


def _safe_path(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise AdapterError(400, "invalid_path", "path must be absolute")
    candidate = PurePosixPath(value)
    if ".." in candidate.parts:
        raise AdapterError(403, "path_denied", "path traversal is not allowed")
    normalized = str(candidate)
    if not any(normalized == root or normalized.startswith(root + "/") for root in ALLOWED_FILE_ROOTS):
        raise AdapterError(
            403,
            "path_denied",
            "path must remain under /workspace or /tmp",
        )
    return normalized


def _truncate(value: str) -> Tuple[str, bool]:
    raw = value.encode("utf-8")
    if len(raw) <= MAX_OUTPUT_BYTES:
        return value, False
    return raw[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"), True


class CubeAdapter:
    def __init__(
        self,
        config: AdapterConfig,
        sandbox_factory: Callable[..., Any] = Sandbox.create,
    ) -> None:
        self.config = config
        self._sandbox_factory = sandbox_factory
        self._leases: Dict[str, Lease] = {}
        self._sessions: Dict[Tuple[str, str], str] = {}
        self._lock = threading.RLock()
        self._audit_lock = threading.Lock()
        self._recent_audit: deque[Dict[str, Any]] = deque(maxlen=200)
        self._load_recent_audit()

    def authenticate(self, authorization: Optional[str]) -> None:
        expected = f"Bearer {self.config.token}"
        if not authorization or not hmac.compare_digest(authorization, expected):
            raise AdapterError(401, "unauthorized", "valid bearer token required")

    def acquire(self, body: Dict[str, Any]) -> Dict[str, Any]:
        started = time.perf_counter()
        runtime = _required_string(body, "runtime", 32).lower()
        if runtime not in {"openclaw", "dsh"}:
            raise AdapterError(400, "invalid_runtime", "runtime must be openclaw or dsh")
        session_key = _required_string(body, "session_key", 512)
        # Session identifiers can be predictable. Use a keyed digest so an
        # audit-log reader cannot cheaply recover them with a dictionary.
        session_hash = hmac.new(
            self.config.session_hmac_key.encode("utf-8"),
            session_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:16]
        profile = body.get("profile", "offline-code")
        if profile != "offline-code":
            raise AdapterError(403, "profile_denied", "only offline-code is enabled")
        request_id = _request_id(body.get("request_id"))
        session_index = (runtime, session_hash)

        with self._lock:
            existing_ref = self._sessions.get(session_index)
            existing = self._leases.get(existing_ref or "")
        if existing is not None:
            existing.last_used_at = time.time()
            result = self._lease_result(existing, reused=True)
            self._audit(existing, "acquire", request_id, "ok", started, reused=True)
            return result

        sandbox = self._sandbox_factory(
            template=self.config.template,
            timeout=self.config.sandbox_timeout_seconds,
            lifecycle={"on_timeout": "pause", "auto_resume": True},
            allow_internet_access=False,
            network={"allow_public_traffic": False},
            metadata={
                "runtime": runtime,
                "purpose": "direct-plugin",
                "session": session_hash,
                "policy": profile,
            },
        )
        lease = Lease(
            lease_ref=f"lease_{uuid.uuid4().hex[:20]}",
            runtime=runtime,
            session_hash=session_hash,
            profile=profile,
            sandbox=sandbox,
            sandbox_ref=str(sandbox.sandbox_id)[:8],
        )
        with self._lock:
            raced_ref = self._sessions.get(session_index)
            raced = self._leases.get(raced_ref or "")
            if raced is None:
                self._leases[lease.lease_ref] = lease
                self._sessions[session_index] = lease.lease_ref
            else:
                sandbox.kill()
                lease = raced
        result = self._lease_result(lease, reused=raced is not None)
        self._audit(lease, "acquire", request_id, "ok", started, reused=result["reused"])
        return result

    def exec(self, lease_ref: str, body: Dict[str, Any]) -> Dict[str, Any]:
        lease = self._lease(lease_ref)
        command = _required_string(body, "command", MAX_COMMAND_BYTES)
        cwd = body.get("cwd")
        if cwd is not None:
            cwd = _safe_path(cwd)
        timeout_ms = body.get("timeout_ms", 60_000)
        if not isinstance(timeout_ms, int) or timeout_ms < 1:
            raise AdapterError(400, "invalid_timeout", "timeout_ms must be a positive integer")
        timeout_ms = min(timeout_ms, self.config.max_command_seconds * 1000)
        request_id = _request_id(body.get("request_id"))
        started = time.perf_counter()
        try:
            with lease.lock:
                result = lease.sandbox.commands.run(
                    command,
                    cwd=cwd,
                    timeout=timeout_ms / 1000,
                )
                lease.last_used_at = time.time()
            stdout, stdout_truncated = _truncate(result.stdout or "")
            stderr, stderr_truncated = _truncate(result.stderr or "")
            response = {
                "executor": "cubesandbox-microvm",
                "sandbox_ref": lease.sandbox_ref,
                "request_id": request_id,
                "exit_code": result.exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }
            self._audit(
                lease,
                "exec",
                request_id,
                "ok",
                started,
                command_sha256=_digest(command, 16),
                exit_code=result.exit_code,
            )
            return response
        except Exception as error:
            self._audit(
                lease,
                "exec",
                request_id,
                "error",
                started,
                command_sha256=_digest(command, 16),
                error_type=type(error).__name__,
            )
            raise

    def read(self, lease_ref: str, body: Dict[str, Any]) -> Dict[str, Any]:
        lease = self._lease(lease_ref)
        path = _safe_path(body.get("path"))
        request_id = _request_id(body.get("request_id"))
        started = time.perf_counter()
        with lease.lock:
            content = lease.sandbox.files.read(path)
            lease.last_used_at = time.time()
        content, truncated = _truncate(content)
        self._audit(lease, "read", request_id, "ok", started, path_sha256=_digest(path, 16))
        return {
            "executor": "cubesandbox-microvm",
            "sandbox_ref": lease.sandbox_ref,
            "request_id": request_id,
            "path": path,
            "content": content,
            "truncated": truncated,
        }

    def write(self, lease_ref: str, body: Dict[str, Any]) -> Dict[str, Any]:
        lease = self._lease(lease_ref)
        path = _safe_path(body.get("path"))
        content = _bounded_string(body, "content", MAX_FILE_BYTES)
        request_id = _request_id(body.get("request_id"))
        started = time.perf_counter()
        with lease.lock:
            lease.sandbox.files.write(path, content)
            lease.last_used_at = time.time()
        self._audit(
            lease,
            "write",
            request_id,
            "ok",
            started,
            path_sha256=_digest(path, 16),
            bytes=len(content.encode("utf-8")),
        )
        return {
            "executor": "cubesandbox-microvm",
            "sandbox_ref": lease.sandbox_ref,
            "request_id": request_id,
            "path": path,
            "bytes": len(content.encode("utf-8")),
        }

    def release(self, lease_ref: str, body: Dict[str, Any]) -> Dict[str, Any]:
        lease = self._lease(lease_ref)
        action = body.get("action", "pause")
        if action not in {"pause", "kill"}:
            raise AdapterError(400, "invalid_action", "action must be pause or kill")
        request_id = _request_id(body.get("request_id"))
        started = time.perf_counter()
        with lease.lock:
            if action == "pause":
                lease.sandbox.pause(wait=True)
            else:
                lease.sandbox.kill()
        if action == "kill":
            with self._lock:
                self._leases.pop(lease.lease_ref, None)
                self._sessions.pop((lease.runtime, lease.session_hash), None)
        self._audit(lease, "release", request_id, "ok", started, release_action=action)
        return {
            "executor": "cubesandbox-microvm",
            "sandbox_ref": lease.sandbox_ref,
            "request_id": request_id,
            "action": action,
        }

    def close(self) -> None:
        with self._lock:
            leases = list(self._leases.values())
            self._leases.clear()
            self._sessions.clear()
        for lease in leases:
            try:
                lease.sandbox.kill()
                self._audit(lease, "shutdown_cleanup", uuid.uuid4().hex[:16], "ok", time.perf_counter())
            except Exception as error:
                self._audit(
                    lease,
                    "shutdown_cleanup",
                    uuid.uuid4().hex[:16],
                    "error",
                    time.perf_counter(),
                    error_type=type(error).__name__,
                )

    def health(self) -> Dict[str, Any]:
        with self._lock:
            leases = len(self._leases)
        return {"status": "ok", "version": VERSION, "active_leases": leases}

    def audit_html(self) -> str:
        if not self.config.audit_ui:
            raise AdapterError(404, "not_found", "audit UI is disabled")
        with self._audit_lock:
            rows = list(reversed(self._recent_audit))
        body = "".join(
            "<tr>"
            f"<td>{html.escape(str(row.get('ts', '')))}</td>"
            f"<td><span class='runtime'>{html.escape(str(row.get('runtime', '')))}</span></td>"
            f"<td>{html.escape(str(row.get('action', '')))}</td>"
            f"<td><code>{html.escape(str(row.get('sandbox_ref', '')))}</code></td>"
            f"<td><code>{html.escape(str(row.get('request_id', '')))}</code></td>"
            f"<td><span class='status {html.escape(str(row.get('outcome', '')))}'>{html.escape(str(row.get('outcome', '')))}</span></td>"
            f"<td>{html.escape(str(row.get('duration_ms', '')))} ms</td>"
            "</tr>"
            for row in rows
        )
        return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Cube Adapter · Audit</title><style>
body{{font:14px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f6f7fb;color:#172033;margin:0}}
header{{background:#fff;border-bottom:1px solid #e5e7eb;padding:24px 36px}}
h1{{font-size:22px;margin:0 0 6px}}p{{color:#667085;margin:0}}main{{padding:28px 36px}}
.cards{{display:flex;gap:14px;margin-bottom:20px}}.card{{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px 20px;min-width:150px}}
.label{{color:#667085;font-size:12px}}.value{{font-size:24px;font-weight:700;margin-top:4px}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden}}
th,td{{text-align:left;padding:13px 14px;border-bottom:1px solid #eef0f4}}th{{font-size:12px;color:#667085;background:#fafbfc}}
code{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}.runtime{{color:#175cd3}}.status{{font-weight:600}}.ok{{color:#067647}}.error{{color:#b42318}}
</style></head><body><header><h1>Cube Adapter 审计</h1><p>实时脱敏事件：不记录命令正文、输出、Token 或完整 Sandbox ID</p></header>
<main><div class='cards'><div class='card'><div class='label'>活动租约</div><div class='value'>{self.health()['active_leases']}</div></div>
<div class='card'><div class='label'>最近事件</div><div class='value'>{len(rows)}</div></div><div class='card'><div class='label'>策略</div><div class='value' style='font-size:18px'>offline-code</div></div></div>
<table><thead><tr><th>时间</th><th>Runtime</th><th>动作</th><th>Sandbox 引用</th><th>Request ID</th><th>结果</th><th>耗时</th></tr></thead><tbody>{body}</tbody></table></main></body></html>"""

    def _lease(self, lease_ref: str) -> Lease:
        with self._lock:
            lease = self._leases.get(lease_ref)
        if lease is None:
            raise AdapterError(404, "lease_not_found", "lease was not found or has expired")
        return lease

    def _load_recent_audit(self) -> None:
        try:
            with open(self.config.audit_log, "r", encoding="utf-8") as stream:
                lines = deque(stream, maxlen=self._recent_audit.maxlen)
        except FileNotFoundError:
            return
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                self._recent_audit.append(event)

    @staticmethod
    def _lease_result(lease: Lease, reused: bool) -> Dict[str, Any]:
        return {
            "executor": "cubesandbox-microvm",
            "lease_ref": lease.lease_ref,
            "sandbox_ref": lease.sandbox_ref,
            "profile": lease.profile,
            "reused": reused,
        }

    def _audit(
        self,
        lease: Lease,
        action: str,
        request_id: str,
        outcome: str,
        started: float,
        **extra: Any,
    ) -> None:
        event = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "runtime": lease.runtime,
            "session_hash": lease.session_hash,
            "action": action,
            "profile": lease.profile,
            "lease_ref": lease.lease_ref,
            "sandbox_ref": lease.sandbox_ref,
            "request_id": request_id,
            "outcome": outcome,
            "duration_ms": round((time.perf_counter() - started) * 1000),
            **extra,
        }
        with self._audit_lock:
            self._recent_audit.append(event)
            os.makedirs(os.path.dirname(os.path.abspath(self.config.audit_log)), exist_ok=True)
            with open(self.config.audit_log, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def make_handler(adapter: CubeAdapter) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "CubeAdapter/" + VERSION

        def do_GET(self) -> None:  # noqa: N802
            try:
                path = urlparse(self.path).path
                if path == "/healthz":
                    self._json(200, adapter.health())
                    return
                if path == "/audit":
                    content = adapter.audit_html().encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
                raise AdapterError(404, "not_found", "route not found")
            except AdapterError as error:
                self._json(error.status, {"error": {"code": error.code, "message": error.message}})

        def do_POST(self) -> None:  # noqa: N802
            try:
                adapter.authenticate(self.headers.get("Authorization"))
                body = self._body()
                path = urlparse(self.path).path
                if path == "/v1/leases/acquire":
                    self._json(200, adapter.acquire(body))
                    return
                match = re.fullmatch(r"/v1/leases/([^/]+)/(exec|read|write|release)", path)
                if match is None:
                    raise AdapterError(404, "not_found", "route not found")
                lease_ref, action = match.groups()
                result = getattr(adapter, action)(lease_ref, body)
                self._json(200, result)
            except AdapterError as error:
                self._json(error.status, {"error": {"code": error.code, "message": error.message}})
            except Exception as error:
                self._json(
                    502,
                    {
                        "error": {
                            "code": "execution_failed",
                            "message": f"CubeSandbox operation failed ({type(error).__name__})",
                        }
                    },
                )

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _body(self) -> Dict[str, Any]:
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise AdapterError(400, "invalid_body", "invalid Content-Length") from error
            if size <= 0 or size > MAX_BODY_BYTES:
                raise AdapterError(413, "invalid_body", "request body is empty or too large")
            try:
                value = json.loads(self.rfile.read(size))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise AdapterError(400, "invalid_json", "request body must be JSON") from error
            if not isinstance(value, dict):
                raise AdapterError(400, "invalid_json", "request body must be a JSON object")
            return value

        def _json(self, status: int, value: Dict[str, Any]) -> None:
            content = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Authenticated CubeSandbox Agent adapter")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.parse_args()
    config = AdapterConfig.from_env()
    adapter = CubeAdapter(config)
    server = ThreadingHTTPServer((config.bind, config.port), make_handler(adapter))

    def stop(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        adapter.close()
        server.server_close()


if __name__ == "__main__":
    main()
