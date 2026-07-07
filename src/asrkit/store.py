"""本地模型存储与下载（Ollama 式 pull）。

安全（H-01/03）：tar/zip 路径穿越防护、下载超时、可选 sha256 校验。
原子（H-02）：解压到 `.partial` → 全部就位后 os.rename 换入；is_installed 只认完成的目录。
格式：按内容（magic bytes）识别，支持 .tar.{bz2,gz,xz}、纯 .tar、.zip —— 不看 URL 扩展名。
"""
from __future__ import annotations

import glob
import hashlib
import os
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile

from .types import AdapterMeta

# 下载落盘用的中性文件名；实际格式在解压时按 magic bytes 识别，与扩展名无关。
_ARCHIVE_NAME = "download.archive"


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


def model_dir(meta: AdapterMeta, config: dict | None = None) -> str:
    if config and config.get("model_dir"):
        return config["model_dir"]
    folder = meta.id.split("/", 1)[-1]
    root = models_root(config)
    d = os.path.join(root, folder)
    # 防御纵深：拒绝 id 里的路径穿越（如 local/../../x），否则 rm/symlink 会越界操作
    rroot = os.path.realpath(root)
    if os.path.realpath(d) != rroot and not os.path.realpath(d).startswith(rroot + os.sep):
        raise ValueError(f"model id '{meta.id}' escapes the models root; refusing")
    return d


def _install_files_ok(meta: AdapterMeta, d: str) -> bool:
    """H-02：有 install_files 则逐项校验（支持 glob/目录）；否则退回"存在任意 .onnx/.ort"。"""
    if getattr(meta, "install_files", None):
        for pat in meta.install_files:
            if pat.endswith("/"):
                if not os.path.isdir(os.path.join(d, pat.rstrip("/"))):
                    return False
            elif not glob.glob(os.path.join(d, pat)):
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


def remove(meta: AdapterMeta, config: dict | None = None):
    """删除已下载的本地模型目录，返回被删路径（未安装则 None）。"""
    d = model_dir(meta, config)
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
        return d
    return None


def _download(url: str, path: str, log, timeout: int = 30) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "asrkit"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(path, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = last = 0
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
            done += len(b)
            if total and done - last >= (10 << 20):
                log(f"  {done >> 20}/{total >> 20} MB")
                last = done


def _verify_sha256(path: str, expected: str, log) -> None:
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


def _safe_extract(tf: tarfile.TarFile, dest: str) -> None:
    """H-01：拒绝路径穿越与 symlink/hardlink/device 成员。"""
    base = os.path.realpath(dest)
    for m in tf.getmembers():
        if m.issym() or m.islnk() or m.isdev():
            raise ValueError(f"unsafe member in tarball ({m.name}); refusing to extract")
        tgt = os.path.realpath(os.path.join(dest, m.name))
        if tgt != base and not tgt.startswith(base + os.sep):
            raise ValueError(f"tarball member escapes target dir ({m.name}); refusing")
    try:
        tf.extractall(dest, filter="data")   # Python 3.12+
    except TypeError:
        tf.extractall(dest)                  # 旧版：已手工校验成员


def _safe_extract_zip(zf: zipfile.ZipFile, dest: str) -> None:
    """H-01（zip 版）：逐成员拒绝路径穿越/绝对路径逃逸。
    注：Python 的 zipfile 不还原 symlink（按普通文件解出），故无 symlink 逃逸面，只需防穿越。"""
    base = os.path.realpath(dest)
    for name in zf.namelist():
        tgt = os.path.realpath(os.path.join(dest, name))
        if tgt != base and not tgt.startswith(base + os.sep):
            raise ValueError(f"zip member escapes target dir ({name}); refusing")
    zf.extractall(dest)


def _extract_archive(path: str, dest: str) -> None:
    """按内容识别压缩格式并安全解压到 dest。

    支持 .tar.{bz2,gz,xz}、纯 .tar（`r:*` 自动识别压缩）与 .zip。识别只看 magic bytes，
    不看扩展名 —— `pull` 的 download_url / `add-model --url` 给什么后缀都不影响。
    """
    if tarfile.is_tarfile(path):
        with tarfile.open(path, "r:*") as tf:
            _safe_extract(tf, dest)
    elif zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            _safe_extract_zip(zf, dest)
    else:
        raise ValueError(
            "unsupported archive format (not a recognizable tar.* or zip); "
            "asrkit expects a .tar.bz2/.gz/.xz or .zip model bundle")


def pull(meta: AdapterMeta, config: dict | None = None, log=print, *, url: str | None = None) -> str:
    """下载并安装本地模型（原子）。已装则直接返回模型目录。url 覆盖 meta.download_url（限 http/https）。"""
    if meta.source != "local":
        raise ValueError(f"{meta.id} is not a local model; no pull needed")
    dest = model_dir(meta, config)
    if is_installed(meta, config):
        log(f"already installed: {dest}")
        return dest
    effective_url = url or meta.download_url
    if not effective_url:
        raise ValueError(f"{meta.id} has no download URL")
    if not effective_url.startswith(("http://", "https://")):
        raise ValueError(f"refusing non-http(s) download URL: {effective_url}")

    parent = os.path.dirname(os.path.abspath(dest))
    os.makedirs(parent, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="asrkit_pull_", dir=parent)  # 同分区，便于原子 rename
    staging = dest + ".partial"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        arc_path = os.path.join(tmp, _ARCHIVE_NAME)
        log(f"downloading {effective_url}")
        _download(effective_url, arc_path, log)
        _verify_sha256(arc_path, meta.sha256, log)
        log("extracting ...")
        _extract_archive(arc_path, tmp)     # 按内容识别 tar.*/zip，安全解压

        entries = [os.path.join(tmp, n) for n in os.listdir(tmp) if n != _ARCHIVE_NAME]
        subdirs = [e for e in entries if os.path.isdir(e)]
        if len(entries) == 1 and len(subdirs) == 1:
            os.rename(subdirs[0], staging)                  # sherpa 常见：单顶层目录
        else:
            os.makedirs(staging)
            for e in entries:
                os.rename(e, os.path.join(staging, os.path.basename(e)))

        if os.path.isdir(dest):
            shutil.rmtree(dest, ignore_errors=True)
        os.rename(staging, dest)                            # 原子换入

        if not _install_files_ok(meta, dest):
            shutil.rmtree(dest, ignore_errors=True)
            raise ValueError(f"{meta.id} install incomplete (missing files)")
        log(f"done → {dest}")
        return dest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)
