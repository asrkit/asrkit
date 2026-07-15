"""在隔离 venv 中安装构建依赖并运行 cloud 构建器。"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = ROOT / "packaging" / "cloud" / "build.py"
DEFAULT_ENV = ROOT / "build" / "asrkit-cloud-env"


def environment_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build asrkit-cloud in an isolated Python environment.",
    )
    parser.add_argument("--env-dir", type=Path, default=DEFAULT_ENV, help="isolated build environment")
    parser.add_argument("--recreate", action="store_true", help="delete and recreate the build environment")
    parser.add_argument("--skip-install", action="store_true", help="reuse dependencies already in the environment")
    parser.add_argument("build_args", nargs=argparse.REMAINDER, help="arguments forwarded to build.py")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    environment = args.env_dir.resolve()
    python = environment_python(environment)

    if args.recreate and environment.exists():
        shutil.rmtree(environment)
    if not python.is_file():
        print(f"Creating isolated build environment: {environment}", file=sys.stderr)
        venv.EnvBuilder(with_pip=True).create(environment)

    if not args.skip_install:
        print("Installing cloud build dependencies", file=sys.stderr)
        subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", ".[cloud-build]"],
            cwd=ROOT,
            check=True,
        )

    build_args = list(args.build_args)
    if build_args[:1] == ["--"]:
        build_args.pop(0)
    return subprocess.run([str(python), str(BUILD_SCRIPT), *build_args], cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
