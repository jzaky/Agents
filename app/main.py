from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .registry import AGENTS, AGENT_BY_ID

UPSTREAM_COMMIT = "9beeb721c2af551bacaab827a76bddaecaa0ca5e"
UPSTREAM_ROOT = Path(os.getenv("UPSTREAM_ROOT", "/opt/upstream"))
RUNS_ROOT = Path(os.getenv("RUNS_ROOT", "/tmp/agent-runs"))
RUN_TIMEOUT = int(os.getenv("RUN_TIMEOUT_SECONDS", "300"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "30"))
ALLOWED_SECRET_KEYS = {"OPENAI_API_KEY", "TAVILY_API_KEY", "NEWS_API_KEY", "GITHUB_TOKEN"}
RUNNER_ACCESS_TOKEN = os.getenv("RUNNER_ACCESS_TOKEN", "").strip()

RUNS_ROOT.mkdir(parents=True, exist_ok=True)
RUN_SEMAPHORE = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENT_RUNS", "2")))

app = FastAPI(title="Actual AI Agent Runner", version="1.0.0")


def require_access(authorization: str | None) -> None:
    if not RUNNER_ACCESS_TOKEN:
        return
    expected = f"Bearer {RUNNER_ACCESS_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid runner access token")


def validate_upstream() -> None:
    agents_dir = UPSTREAM_ROOT / "agents"
    if not agents_dir.is_dir():
        raise RuntimeError(
            f"Actual upstream agents were not found at {agents_dir}. "
            "Build with the included Dockerfile or run scripts/bootstrap.sh."
        )


def public_agent(agent: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in agent.items() if k not in {"stdin_field"}}


@app.get("/api/health")
def health() -> dict[str, Any]:
    ok = (UPSTREAM_ROOT / "agents").is_dir()
    return {
        "ok": ok,
        "upstream_commit": UPSTREAM_COMMIT,
        "upstream_root": str(UPSTREAM_ROOT),
        "agent_count": len(AGENTS),
    }


@app.get("/api/agents")
def agents(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_access(authorization)
    configured = {key: bool(os.getenv(key)) for key in ALLOWED_SECRET_KEYS}
    return {
        "agents": [public_agent(a) for a in AGENTS],
        "configured_keys": configured,
        "upstream_commit": UPSTREAM_COMMIT,
    }


async def save_upload(upload: UploadFile, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with destination.open("wb") as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_MB * 1024 * 1024:
                handle.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"Upload exceeds {MAX_UPLOAD_MB} MB")
            handle.write(chunk)
    return destination


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def validate_fields(agent: dict[str, Any], values: dict[str, Any], uploads: dict[str, list[Path]]) -> None:
    for field in agent.get("fields", []):
        name = field["name"]
        if not field.get("required"):
            continue
        if field["type"] in {"file", "multifile"}:
            present = bool(uploads.get(name))
        elif field["type"] == "checkbox":
            present = truthy(values.get(name))
        else:
            present = str(values.get(name, "")).strip() != ""
        if not present:
            raise HTTPException(status_code=422, detail=f"{field['label']} is required")

    one_of = agent.get("one_of")
    if one_of:
        present = False
        for name in one_of:
            if uploads.get(name):
                present = True
            if str(values.get(name, "")).strip():
                present = True
        if not present:
            raise HTTPException(status_code=422, detail=f"Provide one of: {', '.join(one_of)}")


def build_command(agent: dict[str, Any], values: dict[str, Any], uploads: dict[str, list[Path]], workspace: Path) -> tuple[list[str], str | None]:
    cmd = [sys.executable, "agent.py"]
    stdin_data = None

    for field in agent.get("fields", []):
        name = field["name"]
        kind = field["type"]
        flag = field.get("flag")

        if kind == "multifile":
            paths = uploads.get(name, [])
            if paths and agent["id"] == "13-customer-support-agent":
                kb_dir = workspace / "kb"
                kb_dir.mkdir(exist_ok=True)
                for path in paths:
                    target = kb_dir / path.name
                    if path != target:
                        shutil.copy2(path, target)
                cmd.extend(["--kb-dir", str(kb_dir)])
            continue

        if kind == "file":
            paths = uploads.get(name, [])
            if paths and flag:
                cmd.extend([flag, str(paths[0])])
            continue

        value = values.get(name)
        if kind == "checkbox":
            if truthy(value) and flag:
                cmd.append(flag)
            continue

        if value is None or str(value).strip() == "":
            continue
        if flag:
            cmd.extend([flag, str(value)])

    stdin_field = agent.get("stdin_field")
    if stdin_field:
        stdin_data = f"{values.get(stdin_field, '')}\nquit\n"

    return cmd, stdin_data


def collect_generated(workspace: Path, before: set[str]) -> list[str]:
    generated = []
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(workspace).as_posix()
        if rel in before:
            continue
        if rel.startswith("__pycache__/") or "/__pycache__/" in rel:
            continue
        generated.append(rel)
    return sorted(generated)


@app.post("/api/run/{agent_id}")
async def run_agent(
    agent_id: str,
    request: Request,
    payload_json: str = Form(default="{}"),
    secrets_json: str = Form(default="{}"),
    files: list[UploadFile] = File(default=[]),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_access(authorization)
    validate_upstream()

    agent = AGENT_BY_ID.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Unknown agent")

    try:
        values = json.loads(payload_json or "{}")
        secret_values = json.loads(secrets_json or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc

    if not isinstance(values, dict) or not isinstance(secret_values, dict):
        raise HTTPException(status_code=400, detail="payload_json and secrets_json must be JSON objects")

    run_id = uuid.uuid4().hex
    run_root = RUNS_ROOT / run_id
    workspace = run_root / "workspace"
    source_dir = UPSTREAM_ROOT / "agents" / agent_id
    if not source_dir.is_dir():
        raise HTTPException(status_code=500, detail=f"Upstream agent folder missing: {agent_id}")
    shutil.copytree(source_dir, workspace)

    upload_map: dict[str, list[Path]] = {}
    # File field names are encoded into the UploadFile filename as field::original-name by the UI.
    for upload in files:
        raw_name = Path(upload.filename or "upload.bin").name
        if "__FIELD__" in raw_name:
            field_name, original_name = raw_name.split("__FIELD__", 1)
        else:
            field_name, original_name = "file", raw_name
        destination = workspace / "uploads" / field_name / Path(original_name).name
        path = await save_upload(upload, destination)
        upload_map.setdefault(field_name, []).append(path)

    validate_fields(agent, values, upload_map)
    before = {p.relative_to(workspace).as_posix() for p in workspace.rglob("*") if p.is_file()}
    cmd, stdin_data = build_command(agent, values, upload_map, workspace)

    env = os.environ.copy()
    for key, value in secret_values.items():
        if key in ALLOWED_SECRET_KEYS and isinstance(value, str) and value.strip():
            env[key] = value.strip()

    missing = [key for key in agent.get("keys", []) if not env.get(key)]
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing API key(s): {', '.join(missing)}")

    async with RUN_SEMAPHORE:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(workspace),
                env=env,
                stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(stdin_data.encode() if stdin_data is not None else None),
                timeout=RUN_TIMEOUT,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise HTTPException(status_code=504, detail=f"Agent exceeded {RUN_TIMEOUT} second timeout")

    stdout = stdout_b.decode("utf-8", errors="replace")[-1_000_000:]
    stderr = stderr_b.decode("utf-8", errors="replace")[-300_000:]
    generated = collect_generated(workspace, before)

    return {
        "run_id": run_id,
        "agent_id": agent_id,
        "command": ["python", "agent.py", *cmd[2:]],
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "generated_files": generated,
    }


@app.get("/api/runs/{run_id}/files/{file_path:path}")
def run_file(run_id: str, file_path: str, authorization: str | None = Header(default=None)):
    require_access(authorization)
    root = (RUNS_ROOT / run_id / "workspace").resolve()
    target = (root / file_path).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target, filename=target.name)


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
