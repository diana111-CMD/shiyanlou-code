"""统一日志工具 — 按 Agent 角色分色输出 + 文件归档。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from src.config import settings


def setup_logger(name: str, role: str = "system") -> logging.Logger:
    """为每个 Agent 创建带角色标识的 logger。

    Args:
        name: logger 名称，通常与 Agent 类名一致
        role: 角色标签，显示在日志前缀中
    """
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"embodied.{name}")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    # 控制台: RichHandler 彩色输出
    console_handler = RichHandler(
        console=Console(stderr=True),
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
    )
    console_handler.setFormatter(
        logging.Formatter(f"[bold cyan]{role:>12}[/] %(message)s")
    )
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

    # 文件: 按角色归档
    file_handler = logging.FileHandler(
        settings.log_dir / f"{role}.log", encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    return logger


def setup_default_logger() -> logging.Logger:
    """主程序默认 logger。"""
    return setup_logger("main", "MAIN")
