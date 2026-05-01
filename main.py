#!/usr/bin/env python3
"""具身智能任务规划 Agent 系统 — 主入口。

用法：
  # 交互式 CLI 模式
  python main.py

  # 直接传入指令执行
  python main.py "将工作台上的红色方块放到篮子里"

  # 启动 API 服务
  python main.py --serve
"""

from __future__ import annotations

import argparse
import sys

from src.config import settings
from src.logger import setup_default_logger

logger = setup_default_logger()


def run_interactive():
    """交互式 CLI：持续接收指令并执行。"""
    from src.orchestrator import Orchestrator

    orch = Orchestrator()

    def on_progress(stage: str, msg: str):
        print(f"\n  [{stage}] {msg}\n")

    orch.on_progress = on_progress

    print("=" * 60)
    print("  具身智能任务规划 Agent System")
    print(f"  模式: {'Mock (模拟)' if settings.ros.use_mock else 'ROS (真实硬件)'}")
    print(f"  模型: {settings.llm.model}")
    print("  输入指令开始，输入 'quit' 退出")
    print("=" * 60)

    while True:
        try:
            instruction = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见!")
            break

        if not instruction or instruction.lower() in ("quit", "exit"):
            print("再见!")
            break

        try:
            report = orch.run(instruction)
            _print_report(report)
        except Exception as e:
            logger.error(f"执行异常: {e}", exc_info=True)
            print(f"\n  执行失败: {e}\n")


def run_single(instruction: str):
    """执行单条指令后退出。"""
    from src.orchestrator import Orchestrator

    orch = Orchestrator()
    orch.on_progress = lambda s, m: print(f"  [{s}] {m}")
    report = orch.run(instruction)
    _print_report(report)
    sys.exit(0 if report.overall_success else 1)


def run_server():
    """启动 FastAPI 服务。"""
    import uvicorn
    uvicorn.run(
        "src.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


def _print_report(report) -> None:
    status = "SUCCESS" if report.overall_success else "FAILED"
    print(f"\n{'=' * 50}")
    print(f"  计划: {report.plan_id}")
    print(f"  状态: {status}")
    print(f"  耗时: {report.total_duration_ms:.0f}ms")
    print(f"  动作: {len(report.results)} 个")
    for r in report.results:
        icon = "✓" if r.success else "✗"
        print(f"    {icon} {r.action_id}: {r.message} ({r.duration_ms:.0f}ms)")
    print(f"{'=' * 50}\n")


def main():
    parser = argparse.ArgumentParser(description="具身智能任务规划 Agent 系统")
    parser.add_argument(
        "instruction",
        nargs="?",
        default=None,
        help="自然语言任务指令",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="启动 FastAPI HTTP/WebSocket 服务",
    )
    parser.add_argument(
        "--mock/--no-mock",
        default=settings.ros.use_mock,
        help="Mock 模式 (不连接真实硬件)",
    )
    parser.add_argument(
        "--model",
        default=settings.llm.model,
        help="LLM 模型名称",
    )
    parser.add_argument(
        "--base-url",
        default=settings.llm.base_url,
        help="LLM API Base URL",
    )
    parser.add_argument(
        "--api-key",
        default=settings.llm.api_key,
        help="LLM API Key",
    )

    args = parser.parse_args()

    # 覆盖配置
    settings.ros.use_mock = args.mock
    settings.llm.model = args.model
    if args.base_url:
        settings.llm.base_url = args.base_url
    if args.api_key:
        settings.llm.api_key = args.api_key

    if args.serve:
        run_server()
    elif args.instruction:
        run_single(args.instruction)
    else:
        run_interactive()


if __name__ == "__main__":
    main()
