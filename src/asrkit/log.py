"""集中日志:作为库导入零副作用(NullHandler);CLI 用 setup() 点亮 stderr。"""
from __future__ import annotations

import logging
import sys
from typing import Optional

_NAME = "asrkit"
logging.getLogger(_NAME).addHandler(logging.NullHandler())   # 库安全:import 不刷屏

_HANDLER: Optional[logging.Handler] = None


def get_logger(name: Optional[str] = None) -> logging.Logger:
    return logging.getLogger(_NAME if not name else f"{_NAME}.{name}")


def setup(verbose: int = 0) -> None:
    """按 verbose 计数配 stderr 日志。0=WARNING,1=INFO,>=2=DEBUG。幂等。"""
    global _HANDLER
    level = logging.DEBUG if verbose >= 2 else logging.INFO if verbose == 1 else logging.WARNING
    logger = logging.getLogger(_NAME)
    logger.setLevel(level)
    if _HANDLER is None:
        _HANDLER = logging.StreamHandler(sys.stderr)
        _HANDLER.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logger.addHandler(_HANDLER)
        logger.propagate = False


def ensure_configured() -> None:
    """仅当未配置过才装 WARNING stderr handler(不覆盖 CLI 已设等级)。"""
    if _HANDLER is None:
        setup(0)


def _reset() -> None:
    """测试用:复位 asrkit logger 到初始态。"""
    global _HANDLER
    logger = logging.getLogger(_NAME)
    if _HANDLER is not None:
        logger.removeHandler(_HANDLER)
        _HANDLER = None
    logger.propagate = True
    logger.setLevel(logging.WARNING)
