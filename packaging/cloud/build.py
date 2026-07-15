"""构建并验证 asrkit-cloud PyInstaller onedir。"""
from __future__ import annotations

import argparse
import importlib.util
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "packaging" / "cloud" / "asrkit-cloud.spec"
SMOKE = ROOT / "packaging" / "cloud" / "smoke.py"
EXECUTABLE_NAME = "asrkit-cloud.exe" if sys.platform == "win32" else "asrkit-cloud"


def build_command(dist_dir: Path, work_dir: Path, *, clean: bool = True) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
    ]
    if clean:
        command.append("--clean")
    command.append(str(SPEC))
    return command


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the self-contained asrkit-cloud onedir runtime.",
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=ROOT / "dist",
        help="artifact root (default: repository dist directory)",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=ROOT / "build" / "asrkit-cloud",
        help="PyInstaller work directory",
    )
    parser.add_argument("--no-clean", action="store_true", help="reuse PyInstaller analysis cache")
    parser.add_argument("--no-smoke", action="store_true", help="skip the frozen runtime smoke test")
    parser.add_argument("--dry-run", action="store_true", help="print the PyInstaller command only")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    dist_dir = args.dist_dir.resolve()
    work_dir = args.work_dir.resolve()
    command = build_command(dist_dir, work_dir, clean=not args.no_clean)

    if args.dry_run:
        print(shlex.join(command))
        return 0

    if importlib.util.find_spec("PyInstaller") is None:
        print('Build dependency missing. Run: pip install ".[cloud-build]"', file=sys.stderr)
        return 2

    print(f"Building asrkit-cloud into {dist_dir}", file=sys.stderr)
    subprocess.run(command, cwd=ROOT, check=True)

    executable = dist_dir / "asrkit-cloud" / EXECUTABLE_NAME
    if not executable.is_file():
        print(f"[error] PyInstaller did not create {executable}", file=sys.stderr)
        return 1

    if not args.no_smoke:
        subprocess.run([sys.executable, str(SMOKE), str(executable)], cwd=ROOT, check=True)

    print(f"Built asrkit-cloud: {executable}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
