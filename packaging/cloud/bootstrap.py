"""在隔离 venv 中安装构建依赖并运行 cloud 构建器。"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import venv
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = ROOT / "packaging" / "cloud" / "build.py"
DEFAULT_ENV = ROOT / "build" / "asrkit-cloud-env"
_ENV_MARKER = ".asrkit-cloud-build-env"
_ENV_MARKER_CONTENT = "asrkit-cloud-build-env-v1\n"


class EnvironmentSafetyError(ValueError):
    """构建环境目标不满足安全删除或创建约束。"""


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


def _validate_environment_target(raw_environment: Path) -> Path:
    """先检查原始 leaf，再解析路径并排除高风险目标。"""
    raw = raw_environment.expanduser()
    if not raw.is_absolute():
        raw = Path.cwd() / raw
    raw = Path(os.path.abspath(raw))

    try:
        raw_stat = raw.lstat()
    except FileNotFoundError:
        raw_stat = None
    except OSError as exc:
        raise EnvironmentSafetyError(
            f"cannot inspect build environment path: {raw}") from exc
    if raw_stat is not None and stat.S_ISLNK(raw_stat.st_mode):
        raise EnvironmentSafetyError(
            f"unsafe build environment path is a symlink: {raw}")

    try:
        environment = raw.resolve()
    except OSError as exc:
        raise EnvironmentSafetyError(
            f"cannot resolve build environment path: {raw}") from exc

    default_environment = Path(os.path.abspath(DEFAULT_ENV.expanduser()))
    if raw == default_environment and environment != default_environment:
        raise EnvironmentSafetyError(
            "default build environment escapes the repository through a symlink: "
            f"{raw}")

    filesystem_root = Path(environment.anchor)
    repo_root = ROOT.resolve()
    cwd = Path.cwd().resolve()
    home = Path.home().resolve()
    temporary_roots = {Path(tempfile.gettempdir()).resolve()}
    if os.name != "nt":
        temporary_roots.update(
            Path(candidate).resolve()
            for candidate in ("/tmp", "/var/tmp", "/private/tmp")
        )
    unsafe = (
        environment == filesystem_root
        or environment == home
        or environment == repo_root
        or environment in repo_root.parents
        or environment == cwd
        or environment in cwd.parents
        or environment in temporary_roots
    )
    if unsafe:
        raise EnvironmentSafetyError(
            f"unsafe build environment target: {environment}")
    if environment.exists() and not environment.is_dir():
        raise EnvironmentSafetyError(
            f"build environment target is not a directory: {environment}")
    return environment


def _is_regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _is_valid_environment(environment: Path) -> bool:
    return (
        environment.is_dir()
        and _is_regular_file(environment / "pyvenv.cfg")
        and environment_python(environment).is_file()
    )


def _has_valid_marker(environment: Path) -> bool:
    marker = environment / _ENV_MARKER
    if not _is_regular_file(marker):
        return False
    try:
        return marker.read_text(encoding="utf-8") == _ENV_MARKER_CONTENT
    except OSError:
        return False


def _is_legacy_default_environment(environment: Path) -> bool:
    # DEFAULT_ENV 本身的词法路径必须与验证后路径一致。不对它 resolve，
    # 否则 build/ 这类父目录 symlink 会把仓库外 venv 伪装成旧默认环境。
    return environment == DEFAULT_ENV and _is_valid_environment(environment)


def _is_managed_environment(
    environment: Path,
    *,
    allow_legacy_default: bool = False,
) -> bool:
    if not _is_valid_environment(environment):
        return False
    if _has_valid_marker(environment):
        return True
    return allow_legacy_default and _is_legacy_default_environment(environment)


def _write_marker_atomic(environment: Path) -> None:
    fd: Optional[int] = None
    temporary: Optional[str] = None
    try:
        fd, temporary = tempfile.mkstemp(
            prefix=f".{_ENV_MARKER}.tmp-",
            dir=environment,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = None
            stream.write(_ENV_MARKER_CONTENT)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, environment / _ENV_MARKER)
        temporary = None
    finally:
        if fd is not None:
            os.close(fd)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _remove_managed_environment(
    environment: Path,
    *,
    allow_legacy_default: bool = False,
) -> None:
    """仓库内唯一允许递归删除构建环境的入口。"""
    validated = _validate_environment_target(environment)
    if validated != environment:
        raise EnvironmentSafetyError(
            f"build environment path changed during validation: {environment}")
    if not _is_managed_environment(
        validated,
        allow_legacy_default=allow_legacy_default,
    ):
        raise EnvironmentSafetyError(
            f"build environment is not a managed ASRKit environment: {validated}")
    shutil.rmtree(validated)


def _create_managed_environment(environment: Path) -> None:
    if environment.exists():
        if not environment.is_dir():
            raise EnvironmentSafetyError(
                f"build environment target is not a directory: {environment}")
        try:
            has_entries = next(environment.iterdir(), None) is not None
        except OSError as exc:
            raise EnvironmentSafetyError(
                f"cannot inspect build environment directory: {environment}") from exc
        if has_entries:
            raise EnvironmentSafetyError(
                f"build environment directory is not empty: {environment}")

    print(f"Creating isolated build environment: {environment}", file=sys.stderr)
    venv.EnvBuilder(with_pip=True).create(environment)
    if not _is_valid_environment(environment):
        raise EnvironmentSafetyError(
            f"created build environment failed validation: {environment}")
    _write_marker_atomic(environment)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    try:
        environment = _validate_environment_target(args.env_dir)
        valid_environment = _is_valid_environment(environment)

        if args.recreate and environment.exists():
            _remove_managed_environment(
                environment,
                allow_legacy_default=_is_legacy_default_environment(environment),
            )
            valid_environment = False

        if not valid_environment:
            _create_managed_environment(environment)
        elif _is_legacy_default_environment(environment) and not _has_valid_marker(environment):
            # 只迁移仓库默认位置的旧合法 venv；自定义 venv 始终归用户管理。
            _write_marker_atomic(environment)
    except EnvironmentSafetyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    python = environment_python(environment)

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
