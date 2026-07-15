"""在干净子进程环境中验证冻结后的 asrkit-cloud。"""
from __future__ import annotations

import argparse
import json
import os
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import IO, Optional


CLOUD_MODEL_IDS = {
    "dashscope/fun-asr-flash",
    "dashscope/qwen-omni-flash",
    "dashscope/qwen-omni-plus",
    "dashscope/qwen3-asr-flash",
    "doubao/auc-1",
    "doubao/auc-2",
    "elevenlabs/scribe-v1",
    "openai/whisper-1",
    "siliconflow/sensevoice",
    "siliconflow/telespeech",
}


class SmokeError(RuntimeError):
    pass


def clean_environment(source: Optional[dict[str, str]] = None) -> dict[str, str]:
    env = dict(os.environ if source is None else source)
    for name in list(env):
        if name.startswith("ASRKIT_"):
            env.pop(name)
    for name in (
        "CONDA_DEFAULT_ENV",
        "CONDA_PREFIX",
        "DYLD_FALLBACK_LIBRARY_PATH",
        "DYLD_LIBRARY_PATH",
        "LD_LIBRARY_PATH",
        "PYTHONHOME",
        "PYTHONPATH",
        "VIRTUAL_ENV",
    ):
        env.pop(name, None)
    # 子进程只保留系统命令路径，不能从开发环境发现 python 或 asrkit。
    env["PATH"] = os.defpath
    return env


def read_line(stream: IO[str], timeout: float = 15.0) -> str:
    lines: queue.Queue[str] = queue.Queue(maxsize=1)

    def read() -> None:
        lines.put(stream.readline())

    threading.Thread(target=read, daemon=True).start()
    try:
        line = lines.get(timeout=timeout)
    except queue.Empty as exc:
        raise SmokeError("timed out waiting for an asrkit-cloud lifecycle event") from exc
    if not line:
        raise SmokeError("asrkit-cloud closed stdout before emitting a lifecycle event")
    return line


def load_json(url: str, *, token: Optional[str] = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def verify_transcription_route(base_url: str, token: str) -> None:
    boundary = "asrkit-cloud-smoke-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="model"\r\n\r\n'
        "missing/smoke-model\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="smoke.wav"\r\n'
        "Content-Type: audio/wav\r\n\r\n"
        "not-a-real-wave\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    request = urllib.request.Request(
        base_url + "/audio/transcriptions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as exc:
        try:
            payload = json.load(exc)
        finally:
            exc.close()
        if exc.code != 404 or "unknown model" not in payload.get("error", {}).get("message", ""):
            raise SmokeError(f"unexpected transcription routing response: {exc.code} {payload}")
    else:
        raise SmokeError("unknown model transcription unexpectedly succeeded")


def smoke(executable: Path) -> None:
    executable = executable.resolve()
    if not executable.is_file():
        raise SmokeError(f"runtime executable does not exist: {executable}")

    env = clean_environment()
    with tempfile.TemporaryDirectory(prefix="asrkit-cloud-smoke-") as raw_tmp:
        tmp = Path(raw_tmp)
        empty_path = tmp / "empty-path"
        empty_path.mkdir()
        env["PATH"] = str(empty_path)
        version = subprocess.run(
            [str(executable), "--version"],
            cwd=tmp,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if not version.stdout.startswith("asrkit-cloud ") or version.stderr:
            raise SmokeError("unexpected --version output")

        help_result = subprocess.run(
            [str(executable), "--help"],
            cwd=tmp,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if "usage: asrkit-cloud" not in help_result.stdout or help_result.stderr:
            raise SmokeError("unexpected --help output")

        parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        token = secrets.token_urlsafe(32)
        child_env = dict(env)
        child_env["ASRKIT_GATEWAY_TOKEN"] = token
        process = subprocess.Popen(
            [
                str(executable),
                "--embedded",
                "--parent-pid",
                str(parent.pid),
                "--data-dir",
                str(tmp / "data"),
            ],
            cwd=tmp,
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        try:
            ready = json.loads(read_line(process.stdout))
            if ready.get("event") != "ready" or ready.get("protocol_version") != 1:
                raise SmokeError(f"unexpected ready event: {ready}")
            if ready.get("pid") != process.pid:
                raise SmokeError("ready event reported the wrong process id")

            base_url = ready.get("base_url", "")
            if not base_url.startswith("http://127.0.0.1:") or not base_url.endswith("/v1"):
                raise SmokeError(f"unsafe or invalid base URL: {base_url}")

            health = load_json(base_url.removesuffix("/v1") + "/health")
            if health.get("status") != "ok" or health.get("distribution") != "cloud":
                raise SmokeError(f"unexpected health response: {health}")

            try:
                load_json(base_url + "/models")
            except urllib.error.HTTPError as exc:
                if exc.code != 401:
                    raise SmokeError(f"unauthorized model request returned {exc.code}") from exc
                exc.close()
            else:
                raise SmokeError("model endpoint accepted a request without the bearer token")

            models = load_json(base_url + "/models", token=token)
            model_ids = {item["id"] for item in models.get("data", [])}
            if model_ids != CLOUD_MODEL_IDS:
                raise SmokeError(f"unexpected cloud model set: {sorted(model_ids)}")
            verify_transcription_route(base_url, token)

            parent.terminate()
            parent.wait(timeout=10)
            shutdown = json.loads(read_line(process.stdout))
            if shutdown != {"event": "shutdown", "reason": "parent_exited"}:
                raise SmokeError(f"unexpected shutdown event: {shutdown}")
            if process.wait(timeout=15) != 0:
                raise SmokeError("asrkit-cloud returned a non-zero exit status")

            if process.stdout.read():
                raise SmokeError("asrkit-cloud wrote non-protocol data to stdout")
            stderr = process.stderr.read()
            if token in stderr:
                raise SmokeError("asrkit-cloud leaked the gateway token to stderr")
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait(timeout=5)
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test a frozen asrkit-cloud runtime.")
    parser.add_argument("executable", type=Path, help="path to asrkit-cloud[.exe]")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    try:
        smoke(args.executable)
    except (OSError, SmokeError, subprocess.SubprocessError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    print(f"Smoke passed: {args.executable.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
