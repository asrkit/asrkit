"""本地模型存储与下载（Ollama 式 pull）。

安全（H-01/03）：tar/zip 路径穿越防护、下载超时、可选 sha256 校验。
原子（H-02）：每次 pull 使用私有 staging，完整性验证后再同分区 rename 换入。
格式：按内容（magic bytes）识别，支持 .tar.{bz2,gz,xz}、纯 .tar、.zip —— 不看 URL 扩展名。
"""
from __future__ import annotations

import glob
import hashlib
import os
import shutil
import stat
import tarfile
import tempfile
import threading
import unicodedata
import urllib.request
from urllib.parse import urljoin, urlsplit
import zipfile
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Callable, Iterator

from .types import AdapterMeta

# 下载落盘用的中性文件名；实际格式在解压时按 magic bytes 识别，与扩展名无关。
_ARCHIVE_NAME = "download.archive"


@dataclass(frozen=True)
class InstallLimits:
    """一次模型安装允许消耗的最大资源量。"""

    max_download_bytes: int = 8 << 30
    max_extracted_bytes: int = 16 << 30
    max_members: int = 20_000
    max_member_bytes: int = 8 << 30
    max_path_bytes: int = 1024

    def __post_init__(self) -> None:
        for name in (
            "max_download_bytes",
            "max_extracted_bytes",
            "max_members",
            "max_member_bytes",
            "max_path_bytes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


_DEFAULT_LIMITS = InstallLimits()
_DOWNLOAD_MAX_BYTES: ContextVar[int] = ContextVar(
    "asrkit_download_max_bytes",
    default=_DEFAULT_LIMITS.max_download_bytes,
)
_PULL_LOCKS: dict[str, threading.Lock] = {}
_PULL_LOCKS_GUARD = threading.Lock()


def _validate_download_url(url: str, *, redirect_from: str | None = None) -> None:
    """下载只允许具有完整 host 的 HTTP(S)；HTTPS 链路不得降级。"""
    try:
        parsed = urlsplit(url)
        source = urlsplit(redirect_from) if redirect_from is not None else None
        hostname = parsed.hostname
    except ValueError as exc:
        raise ValueError(f"invalid model download URL: {url}") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not hostname:
        raise ValueError(f"refusing non-http(s) download URL: {url}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("refusing model download URL containing credentials")
    if source is not None and source.scheme.lower() == "https" and scheme != "https":
        raise ValueError("refusing HTTPS model download redirect downgrade")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """每一跳重定向都重新执行下载 URL 策略。"""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        target = urljoin(req.full_url, newurl)
        _validate_download_url(target, redirect_from=req.full_url)
        return super().redirect_request(req, fp, code, msg, headers, target)


def _open_download(request: urllib.request.Request, timeout: int) -> Any:
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    return opener.open(request, timeout=timeout)


@contextmanager
def _download_limit(max_bytes: int) -> Iterator[None]:
    """保持 _download 的历史调用签名，同时把当前 pull 的预算传入下载器。"""
    token = _DOWNLOAD_MAX_BYTES.set(max_bytes)
    try:
        yield
    finally:
        _DOWNLOAD_MAX_BYTES.reset(token)


def models_root(config: dict | None = None) -> str:
    # 优先级：显式 config > 环境变量 > config.json 设置 > 默认 ~/.asrkit/models
    if config and config.get("models_root"):
        return config["models_root"]
    env = os.environ.get("ASRKIT_MODELS_ROOT")
    if env:
        return env
    try:
        from . import config as _config
        stored = _config.get_setting("models_root")
        if stored:
            return stored
    except Exception:
        pass
    return os.path.expanduser("~/.asrkit/models")


def validate_models_root(path: str) -> str:
    """验证可执行写入/删除的模型根目录，拒绝明显的系统与工作区边界。"""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("models root must be a non-empty path")
    expanded = os.path.abspath(os.path.expanduser(path))
    resolved = os.path.realpath(expanded)

    protected: set[str] = set()
    candidates = [
        Path(resolved).anchor,
        str(Path.home()),
        tempfile.gettempdir(),
        "/tmp",
        "/var/tmp",
        "/private/tmp",
        os.getcwd(),
        str(Path(__file__).resolve().parents[2]),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        current = Path(candidate).expanduser().resolve()
        protected.add(os.path.normcase(str(current)))
        # home/cwd/package 的祖先同样是宽泛的破坏边界。
        if candidate not in {tempfile.gettempdir(), "/tmp", "/var/tmp", "/private/tmp"}:
            protected.update(os.path.normcase(str(parent)) for parent in current.parents)

    if os.path.normcase(resolved) in protected:
        raise ValueError(f"refusing unsafe models root: {expanded}")
    return expanded


def _is_within(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((os.path.normcase(path), os.path.normcase(root))) == os.path.normcase(root)
    except ValueError:  # Windows 跨盘符
        return False


def managed_model_dir(model_id: str, config: dict | None = None) -> str:
    """返回 store 管理的模型目录；允许 leaf symlink，但拒绝父路径软链和路径穿越。"""
    folder = model_id.split("/", 1)[-1]
    parts = folder.replace("\\", "/").split("/")
    root = os.path.abspath(os.path.expanduser(models_root(config)))
    if (not folder or "\\" in folder or os.path.isabs(folder)
            or any(part in ("", ".", "..") for part in parts)):
        raise ValueError(f"model id '{model_id}' escapes the models root; refusing")

    dest = os.path.abspath(os.path.join(root, *parts))
    if dest == root or not _is_within(dest, root):
        raise ValueError(f"model id '{model_id}' escapes the models root; refusing")

    # root 自身可以是用户配置的 symlink；其下到 leaf 父目录之间不允许再穿过 symlink。
    parent = os.path.dirname(dest)
    rel_parent = os.path.relpath(parent, root)
    current = root
    if rel_parent != os.curdir:
        for part in rel_parent.split(os.sep):
            current = os.path.join(current, part)
            try:
                mode = os.lstat(current).st_mode
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(mode):
                raise ValueError(f"model id '{model_id}' escapes the models root; refusing")
            if not stat.S_ISDIR(mode):
                raise ValueError(f"model id '{model_id}' has a non-directory parent; refusing")
    return dest


def model_dir(meta: AdapterMeta, config: dict | None = None) -> str:
    if config and config.get("model_dir"):
        return config["model_dir"]
    return managed_model_dir(meta.id, config)


def _install_files_ok(meta: AdapterMeta, d: str) -> bool:
    """H-02：有 install_files 则逐项校验（支持 glob/目录）；否则退回"存在任意 .onnx/.ort"。"""
    if getattr(meta, "install_files", None):
        for pat in meta.install_files:
            relative = pat.rstrip("/")
            parts = relative.replace("\\", "/").split("/")
            if (not relative or "\\" in pat or os.path.isabs(relative)
                    or any(part in ("", ".", "..") for part in parts)):
                return False
            candidate = os.path.abspath(os.path.join(d, *parts))
            root = os.path.abspath(d)
            if not _is_within(candidate, root):
                return False
            if pat.endswith("/"):
                if not os.path.isdir(candidate):
                    return False
            elif not glob.glob(candidate):
                return False
        return True
    for _root, _dirs, files in os.walk(d):
        if any(f.endswith((".onnx", ".ort")) for f in files):
            return True
    return False


def is_installed(meta: AdapterMeta, config: dict | None = None) -> bool:
    d = model_dir(meta, config)
    return os.path.isdir(d) and _install_files_ok(meta, d)


def dir_size(meta: AdapterMeta, config: dict | None = None) -> int:
    """已安装本地模型占用的磁盘字节数（未安装返回 0）。"""
    d = model_dir(meta, config)
    if not os.path.isdir(d):
        return 0
    total = 0
    for root, _dirs, files in os.walk(d):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def remove(meta: AdapterMeta, config: dict | None = None) -> str | None:
    """删除 store 管理的模型；leaf symlink 只 unlink，永不删除其外部目标。"""
    validate_models_root(models_root(config))
    d = managed_model_dir(meta.id, config)
    if os.path.islink(d):
        os.unlink(d)
        return d
    if os.path.isdir(d):
        if not _install_files_ok(meta, d):
            raise ValueError(
                f"managed model directory is incomplete or unverified; refusing to remove it: {d}"
            )
        shutil.rmtree(d)
        return d
    if os.path.lexists(d):
        raise ValueError(f"managed model path is not a directory: {d}")
    return None


def _download(
    url: str,
    path: str,
    log: Callable[[str], Any],
    timeout: int = 30,
) -> None:
    _validate_download_url(url)
    max_bytes = _DOWNLOAD_MAX_BYTES.get()
    req = urllib.request.Request(url, headers={"User-Agent": "asrkit"})
    partial = ""
    try:
        with _open_download(req, timeout) as r:
            raw_length = r.headers.get("Content-Length")
            declared: int | None = None
            if raw_length is not None:
                try:
                    declared = int(raw_length)
                except (TypeError, ValueError) as exc:
                    raise ValueError("invalid Content-Length in model download") from exc
                if declared < 0:
                    raise ValueError("invalid Content-Length in model download")
                if declared > max_bytes:
                    raise ValueError(
                        f"download Content-Length exceeds limit ({declared} > {max_bytes} bytes)"
                    )

            parent = os.path.dirname(os.path.abspath(path))
            os.makedirs(parent, exist_ok=True)
            fd, partial = tempfile.mkstemp(
                prefix=f".{os.path.basename(path)}.",
                suffix=".partial",
                dir=parent,
            )
            with os.fdopen(fd, "wb") as f:
                done = last = 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > max_bytes:
                        raise ValueError(
                            f"download exceeds limit ({done} > {max_bytes} bytes)"
                        )
                    f.write(chunk)
                    if declared and done - last >= (10 << 20):
                        log(f"  {done >> 20}/{declared >> 20} MB")
                        last = done
            if declared is not None and done != declared:
                raise ValueError(
                    f"download size does not match Content-Length ({done} != {declared} bytes)"
                )
        os.replace(partial, path)
        partial = ""
    finally:
        if partial:
            try:
                os.unlink(partial)
            except OSError:
                pass


def _verify_sha256(
    path: str,
    expected: str,
    log: Callable[[str], Any],
) -> None:
    """H-03b：登记了 sha256 才校验，不匹配即报错。"""
    if not expected:
        return
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    got = h.hexdigest()
    if got.lower() != expected.lower():
        raise ValueError(f"checksum mismatch (expected {expected[:12]}…, got {got[:12]}…); rejected")


@dataclass(frozen=True)
class _ArchiveEntry:
    name: str
    key: str
    size: int
    is_dir: bool
    source: object


_WINDOWS_DEVICES = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
    "com¹", "com²", "com³", "lpt¹", "lpt²", "lpt³",
}
_WINDOWS_FORBIDDEN_CHARS = frozenset('<>:"|?*')


def _member_path(name: str, is_dir: bool, limits: InstallLimits) -> tuple[str, str]:
    """把归档内路径归一为可移植的相对路径和碰撞检测 key。"""
    if not isinstance(name, str) or not name or "\x00" in name:
        raise ValueError("unsafe empty member path in archive")
    if "\\" in name:
        raise ValueError(f"archive member contains a backslash ({name}); refusing")
    if name.startswith("/"):
        raise ValueError(f"archive member uses an absolute path ({name}); refusing")

    raw = name[:-1] if is_dir and name.endswith("/") else name
    while raw.startswith("./"):
        raw = raw[2:]
    if is_dir and raw in {"", "."}:
        return "", ""

    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"archive member escapes target dir ({name}); refusing")

    normalized = []
    for part in parts:
        if part.endswith((" ", ".")):
            raise ValueError(f"archive member has a nonportable path ({name}); refusing")
        if any(ord(char) < 32 or char in _WINDOWS_FORBIDDEN_CHARS for char in part):
            raise ValueError(f"archive member has a nonportable path ({name}); refusing")
        folded = unicodedata.normalize("NFC", part).casefold()
        stem = folded.split(".", 1)[0]
        if stem in _WINDOWS_DEVICES:
            raise ValueError(f"archive member has a reserved path ({name}); refusing")
        normalized.append(folded)

    relative = "/".join(parts)
    if len(os.fsencode(relative)) > limits.max_path_bytes:
        raise ValueError(
            f"archive member path length exceeds limit ({name}); refusing"
        )
    return relative, "/".join(normalized)


def _append_preflight_entry(
    entries: list[_ArchiveEntry],
    seen: dict[str, _ArchiveEntry],
    entry: _ArchiveEntry,
    declared_total: int,
    limits: InstallLimits,
) -> int:
    """在读取下一个 tar header 前就应用资源预算，避免清单先自身 OOM。"""
    count = len(entries) + 1
    if count > limits.max_members:
        raise ValueError(
            f"archive member count exceeds limit ({count} > {limits.max_members})"
        )
    if entry.name:  # 归档自身的根目录条目只计数，无需落盘。
        if entry.key in seen:
            raise ValueError(
                f"archive contains a normalized duplicate ({entry.name}); refusing"
            )
        if not entry.is_dir:
            if entry.size < 0:
                raise ValueError(f"archive member has a negative size ({entry.name}); refusing")
            if entry.size > limits.max_member_bytes:
                raise ValueError(
                    f"archive single-member size exceeds limit ({entry.name}); refusing"
                )
            declared_total += entry.size
            if declared_total > limits.max_extracted_bytes:
                raise ValueError("archive declared extracted-size exceeds limit; refusing")
        seen[entry.key] = entry
    entries.append(entry)
    return declared_total


def _finish_preflight(
    entries: list[_ArchiveEntry],
    seen: dict[str, _ArchiveEntry],
) -> list[_ArchiveEntry]:
    # 同一归档不能既把某路径当文件，又把它当作另一路径的父目录。
    for key, entry in seen.items():
        components = key.split("/")
        for index in range(1, len(components)):
            parent = seen.get("/".join(components[:index]))
            if parent is not None and not parent.is_dir:
                raise ValueError(
                    f"archive member has a non-directory parent ({entry.name}); refusing"
                )
    return [entry for entry in entries if entry.name]


def _ensure_extract_root(dest: str) -> str:
    root = os.path.abspath(dest)
    try:
        mode = os.lstat(root).st_mode
    except FileNotFoundError:
        os.makedirs(root)
        mode = os.lstat(root).st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise ValueError(f"extraction target is not a safe directory: {dest}")
    return root


def _ensure_directory(root: str, relative: str) -> str:
    current = root
    if not relative:
        return current
    for part in relative.split("/"):
        current = os.path.join(current, part)
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            os.mkdir(current)
            mode = os.lstat(current).st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ValueError(f"archive extraction encountered an unsafe directory ({relative})")
    return current


def _write_stream(
    stream: IO[bytes],
    root: str,
    entry: _ArchiveEntry,
    actual_total: int,
    limits: InstallLimits,
) -> int:
    parent = entry.name.rsplit("/", 1)[0] if "/" in entry.name else ""
    _ensure_directory(root, parent)
    target = os.path.join(root, *entry.name.split("/"))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(target, flags, 0o600)
    written = 0
    try:
        with os.fdopen(fd, "wb") as output:
            while True:
                chunk = stream.read(1 << 20)
                if not chunk:
                    break
                written += len(chunk)
                actual_total += len(chunk)
                if written > entry.size:
                    raise ValueError(
                        f"archive member exceeds its declared size ({entry.name}); refusing"
                    )
                if written > limits.max_member_bytes:
                    raise ValueError(
                        f"archive single-member size exceeds limit ({entry.name}); refusing"
                    )
                if actual_total > limits.max_extracted_bytes:
                    raise ValueError("archive actual extracted-size exceeds limit; refusing")
                output.write(chunk)
        if written != entry.size:
            raise ValueError(
                f"archive member size does not match declaration ({entry.name}); refusing"
            )
    except BaseException:
        try:
            os.unlink(target)
        except FileNotFoundError:
            pass
        raise
    return actual_total


def _safe_extract(
    tf: tarfile.TarFile,
    dest: str,
    limits: InstallLimits | None = None,
) -> None:
    """先完整验证 tar 清单，再逐成员限量写入。"""
    effective = limits or _DEFAULT_LIMITS
    entries: list[_ArchiveEntry] = []
    seen: dict[str, _ArchiveEntry] = {}
    declared_total = 0
    for member in tf:
        if not (member.isfile() or member.isdir()):
            raise ValueError(
                f"unsafe member in tarball ({member.name}); refusing to extract"
            )
        name, key = _member_path(member.name, member.isdir(), effective)
        declared_total = _append_preflight_entry(
            entries,
            seen,
            _ArchiveEntry(name, key, member.size, member.isdir(), member),
            declared_total,
            effective,
        )
    entries = _finish_preflight(entries, seen)

    root = _ensure_extract_root(dest)
    actual_total = 0
    for entry in entries:
        if entry.is_dir:
            _ensure_directory(root, entry.name)
            continue
        source = tf.extractfile(entry.source)  # type: ignore[arg-type]
        if source is None:
            raise ValueError(f"cannot read archive member ({entry.name}); refusing")
        with source:
            actual_total = _write_stream(source, root, entry, actual_total, effective)


def _safe_extract_zip(
    zf: zipfile.ZipFile,
    dest: str,
    limits: InstallLimits | None = None,
) -> None:
    """先完整验证 zip 中央目录，再逐成员限量写入。"""
    effective = limits or _DEFAULT_LIMITS
    entries: list[_ArchiveEntry] = []
    seen: dict[str, _ArchiveEntry] = {}
    declared_total = 0
    infos = zf.infolist()
    if len(infos) > effective.max_members:
        raise ValueError(
            f"archive member count exceeds limit ({len(infos)} > {effective.max_members})"
        )
    for info in infos:
        if info.flag_bits & 0x1:
            raise ValueError(f"encrypted zip member is not supported ({info.filename}); refusing")
        mode = (info.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(mode)
        if file_type == stat.S_IFLNK:
            raise ValueError(f"zip symlink is unsafe ({info.filename}); refusing")
        if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ValueError(f"zip special member is unsafe ({info.filename}); refusing")
        is_dir = info.is_dir() or file_type == stat.S_IFDIR
        name, key = _member_path(info.filename, is_dir, effective)
        declared_total = _append_preflight_entry(
            entries,
            seen,
            _ArchiveEntry(name, key, info.file_size, is_dir, info),
            declared_total,
            effective,
        )
    entries = _finish_preflight(entries, seen)

    root = _ensure_extract_root(dest)
    actual_total = 0
    for entry in entries:
        if entry.is_dir:
            _ensure_directory(root, entry.name)
            continue
        with zf.open(entry.source, "r") as source:  # type: ignore[arg-type]
            actual_total = _write_stream(source, root, entry, actual_total, effective)


def _extract_archive(
    path: str,
    dest: str,
    limits: InstallLimits | None = None,
) -> None:
    """按内容识别压缩格式并安全解压到 dest。

    支持 .tar.{bz2,gz,xz}、纯 .tar（`r:*` 自动识别压缩）与 .zip。识别只看 magic bytes，
    不看扩展名 —— `pull` 的 download_url / `add-model --url` 给什么后缀都不影响。
    """
    effective = limits or _DEFAULT_LIMITS
    if tarfile.is_tarfile(path):
        with tarfile.open(path, "r:*") as tf:
            _safe_extract(tf, dest, effective)
    elif zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            _safe_extract_zip(zf, dest, effective)
    else:
        raise ValueError(
            "unsupported archive format (not a recognizable tar.* or zip); "
            "asrkit expects a .tar.bz2/.gz/.xz or .zip model bundle")


def _destination_lock(dest: str) -> threading.Lock:
    # 这里解决同一进程内的重复 pull；跨进程锁需要稳定的锁文件协议，留待后续单独设计。
    key = os.path.normcase(
        os.path.join(os.path.realpath(os.path.dirname(dest)), os.path.basename(dest))
    )
    with _PULL_LOCKS_GUARD:
        lock = _PULL_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PULL_LOCKS[key] = lock
        return lock


def _publish_staging(staging: str, dest: str) -> None:
    """发布已验证 staging；回滚也失败时必须把旧目录保留在工作区之外。"""
    if os.path.islink(dest):
        raise ValueError(f"refusing to replace linked model directory: {dest}")
    if os.path.lexists(dest) and not os.path.isdir(dest):
        raise ValueError(f"managed model path is not a directory: {dest}")

    had_previous = os.path.isdir(dest)
    backup = ""
    if had_previous:
        backup = tempfile.mkdtemp(
            prefix=f".{os.path.basename(dest)}.backup-",
            dir=os.path.dirname(dest),
        )
        os.rmdir(backup)
        os.rename(dest, backup)
    try:
        os.rename(staging, dest)
    except BaseException:
        if had_previous and not os.path.lexists(dest):
            try:
                os.rename(backup, dest)
            except BaseException as restore_error:
                raise RuntimeError(
                    "model publish and rollback both failed; previous install was "
                    f"preserved at: {backup}"
                ) from restore_error
        raise
    else:
        if backup:
            shutil.rmtree(backup, ignore_errors=True)


def pull(
    meta: AdapterMeta,
    config: dict | None = None,
    log: Callable[[str], Any] = print,
    *,
    url: str | None = None,
    limits: InstallLimits | None = None,
) -> str:
    """下载并安装本地模型（原子）。已装则直接返回模型目录。url 覆盖 meta.download_url（限 http/https）。"""
    if meta.source != "local":
        raise ValueError(f"{meta.id} is not a local model; no pull needed")
    if config and config.get("model_dir"):
        raise ValueError("model_dir is a runtime-only override; pull only writes to the managed models root")
    if limits is not None and not isinstance(limits, InstallLimits):
        raise TypeError("limits must be an InstallLimits instance")
    effective_limits = limits or _DEFAULT_LIMITS
    validate_models_root(models_root(config))
    dest = managed_model_dir(meta.id, config)
    effective_url = url or meta.download_url

    parent = os.path.dirname(os.path.abspath(dest))
    os.makedirs(parent, exist_ok=True)
    with _destination_lock(dest):
        # 锁内必须重查：等待锁的第二个线程直接复用第一个线程完成的安装。
        if is_installed(meta, config):
            log(f"already installed: {dest}")
            return dest
        if os.path.islink(dest):
            raise ValueError(
                f"{meta.id} points to an incomplete external model directory; "
                "fix its files or remove the link before pulling")
        if os.path.lexists(dest) and not os.path.isdir(dest):
            raise ValueError(f"managed model path is not a directory: {dest}")
        if os.path.isdir(dest):
            raise ValueError(
                "managed model directory already exists but is incomplete; "
                f"refusing to replace it: {dest}"
            )
        if not effective_url:
            raise ValueError(f"{meta.id} has no download URL")
        _validate_download_url(effective_url)

        # 下载、解包、staging 均属于本次 pull 的私有目录；绝不触碰共享 *.partial。
        work_dir = tempfile.mkdtemp(prefix=".asrkit-pull-", dir=parent)
        try:
            arc_path = os.path.join(work_dir, _ARCHIVE_NAME)
            extract_dir = os.path.join(work_dir, "extract")
            staging = os.path.join(work_dir, "staging")
            os.mkdir(extract_dir)

            log(f"downloading {effective_url}")
            with _download_limit(effective_limits.max_download_bytes):
                _download(effective_url, arc_path, log)
            _verify_sha256(arc_path, meta.sha256, log)
            log("extracting ...")
            _extract_archive(arc_path, extract_dir, effective_limits)

            entries = [os.path.join(extract_dir, name) for name in os.listdir(extract_dir)]
            subdirs = [entry for entry in entries if os.path.isdir(entry)]
            if len(entries) == 1 and len(subdirs) == 1:
                os.rename(subdirs[0], staging)  # sherpa 常见：单顶层目录
            else:
                os.mkdir(staging)
                for entry in entries:
                    os.rename(entry, os.path.join(staging, os.path.basename(entry)))

            if not _install_files_ok(meta, staging):
                raise ValueError(f"{meta.id} install incomplete (missing files)")
            # 其它进程可能在本次下载期间先完成；能识别的成品永不覆盖。
            if is_installed(meta, config):
                log(f"already installed: {dest}")
                return dest
            _publish_staging(staging, dest)
            log(f"done → {dest}")
            return dest
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
