"""本地模型存储与下载（Ollama 式 pull）。

安全（H-01/03）：tar 路径穿越防护、下载超时、可选 sha256 校验。
原子（H-02）：解压到 `.partial` → 全部就位后 os.rename 换入；is_installed 只认完成的目录。
"""
from __future__ import annotations

import glob
import hashlib
import os
import shutil
import tarfile
import tempfile
import urllib.request

from .types import AdapterMeta


def models_root(config: dict | None = None) -> str:
    if config and config.get("models_root"):
        return config["models_root"]
    return os.environ.get("ASRKIT_MODELS_ROOT") or os.path.expanduser("~/.asrkit/models")


def model_dir(meta: AdapterMeta, config: dict | None = None) -> str:
    if config and config.get("model_dir"):
        return config["model_dir"]
    folder = meta.id.split("/", 1)[-1]
    return os.path.join(models_root(config), folder)


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
        raise ValueError(f"下载校验和不匹配（期望 {expected[:12]}…，实际 {got[:12]}…），已拒绝")


def _safe_extract(tf: tarfile.TarFile, dest: str) -> None:
    """H-01：拒绝路径穿越与 symlink/hardlink/device 成员。"""
    base = os.path.realpath(dest)
    for m in tf.getmembers():
        if m.issym() or m.islnk() or m.isdev():
            raise ValueError(f"tarball 含不安全成员（{m.name}），拒绝解压")
        tgt = os.path.realpath(os.path.join(dest, m.name))
        if tgt != base and not tgt.startswith(base + os.sep):
            raise ValueError(f"tarball 成员路径逃逸（{m.name}），拒绝解压")
    try:
        tf.extractall(dest, filter="data")   # Python 3.12+
    except TypeError:
        tf.extractall(dest)                  # 旧版：已手工校验成员


def pull(meta: AdapterMeta, config: dict | None = None, log=print) -> str:
    """下载并安装本地模型（原子）。已装则直接返回模型目录。"""
    if meta.source != "local":
        raise ValueError(f"{meta.id} 不是本地模型，无需 pull")
    dest = model_dir(meta, config)
    if is_installed(meta, config):
        log(f"已安装：{dest}")
        return dest
    if not meta.download_url:
        raise ValueError(f"{meta.id} 未登记下载地址")

    parent = os.path.dirname(os.path.abspath(dest))
    os.makedirs(parent, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="asrkit_pull_", dir=parent)  # 同分区，便于原子 rename
    staging = dest + ".partial"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        tar_path = os.path.join(tmp, "m.tar.bz2")
        log(f"下载 {meta.download_url}")
        _download(meta.download_url, tar_path, log)
        _verify_sha256(tar_path, meta.sha256, log)
        log("解压 ...")
        with tarfile.open(tar_path, "r:bz2") as tf:
            _safe_extract(tf, tmp)

        entries = [os.path.join(tmp, n) for n in os.listdir(tmp) if n != "m.tar.bz2"]
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
            raise ValueError(f"{meta.id} 安装不完整（缺文件）")
        log(f"完成 → {dest}")
        return dest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)
