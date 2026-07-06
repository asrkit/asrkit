"""本地模型存储与下载（Ollama 式 pull）。

布局：$ASRKIT_MODELS_ROOT/<folder>/  （folder = 模型 id 去掉 "local/"）。
pull = 下载 tarball → 解压 → 把内容放进模型目录（保留原文件名，adapter 用 glob 找）。
"""
from __future__ import annotations

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


def is_installed(meta: AdapterMeta, config: dict | None = None) -> bool:
    d = model_dir(meta, config)
    if not os.path.isdir(d):
        return False
    for _root, _dirs, files in os.walk(d):
        if any(f.endswith((".onnx", ".ort")) for f in files):
            return True
    return False


def _download(url: str, path: str, log) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "asrkit"})
    with urllib.request.urlopen(req) as r, open(path, "wb") as f:
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


def pull(meta: AdapterMeta, config: dict | None = None, log=print) -> str:
    """下载并安装一个本地模型，返回模型目录。已装则直接返回。"""
    if meta.source != "local":
        raise ValueError(f"{meta.id} 不是本地模型，无需 pull")
    dest = model_dir(meta, config)
    if is_installed(meta, config):
        log(f"已安装：{dest}")
        return dest
    if not meta.download_url:
        raise ValueError(f"{meta.id} 未登记下载地址")

    os.makedirs(dest, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="asrkit_pull_")
    try:
        tar_path = os.path.join(tmp, "m.tar.bz2")
        log(f"下载 {meta.download_url}")
        _download(meta.download_url, tar_path, log)
        log("解压 ...")
        with tarfile.open(tar_path, "r:bz2") as tf:
            tf.extractall(tmp)
        # sherpa tarball 通常解压出一个顶层子目录
        subdirs = [os.path.join(tmp, n) for n in os.listdir(tmp)
                   if os.path.isdir(os.path.join(tmp, n))]
        src = subdirs[0] if len(subdirs) == 1 else tmp
        for name in os.listdir(src):
            if name == "m.tar.bz2":
                continue
            s = os.path.join(src, name)
            d = os.path.join(dest, name)
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True)
            else:
                shutil.copy2(s, d)
        log(f"完成 → {dest}")
        return dest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
