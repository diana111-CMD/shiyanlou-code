"""FastAPI 服务 — HTTP REST + WebSocket 接口，供前端或外部系统调用。

接口：
  POST /api/v1/task          提交任务指令（同步，返回完整结果）
  POST /api/v1/task/stream   提交任务指令（WebSocket 流式推送进度）
  GET  /api/v1/plans         查询历史计划
  GET  /api/v1/health        健康检查
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from pydantic import BaseModel

from src.config import settings
from src.logger import setup_default_logger
from src.models import TaskPlan

logger = setup_default_logger()


class TaskRequest(BaseModel):
    instruction: str
    use_builtin_executor: bool = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Embodied AI Agent System 启动")
    yield
    logger.info("系统关闭")


app = FastAPI(
    title="Embodied AI Agent System",
    description="具身智能任务规划系统 — 大模型驱动的机械臂与智能车控制",
    version="0.1.0",
    lifespan=lifespan,
)


# ── 懒加载 orchestrator，避免启动时初始化 LLM ──

_orchestrator = None


def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        from src.orchestrator import Orchestrator
        _orchestrator = Orchestrator()
    return _orchestrator


# ── REST 接口 ──

@app.post("/api/v1/task")
async def create_task(req: TaskRequest):
    """提交自然语言指令，同步等待完整执行结果。"""
    orch = get_orchestrator()
    orch.use_builtin = req.use_builtin_executor

    def progress(stage: str, message: str):
        logger.info(f"[API] [{stage}] {message}")

    orch.on_progress = progress
    report = orch.run(req.instruction)
    return {
        "plan_id": report.plan_id,
        "success": report.overall_success,
        "total_duration_ms": report.total_duration_ms,
        "actions": [
            {
                "action_id": r.action_id,
                "success": r.success,
                "message": r.message,
                "duration_ms": r.duration_ms,
            }
            for r in report.results
        ],
    }


@app.websocket("/api/v1/task/stream")
async def stream_task(websocket: WebSocket):
    """WebSocket 流式推送任务执行进度。"""
    await websocket.accept()
    data = await websocket.receive_json()
    instruction = data.get("instruction", "")

    orch = get_orchestrator()
    orch.use_builtin = data.get("use_builtin_executor", True)

    try:
        async for event in orch.run_stream(instruction):
            if event["type"] == "progress":
                await websocket.send_json({
                    "type": "progress",
                    "stage": event["stage"],
                    "message": event["message"],
                })
            elif event["type"] == "result":
                report = event["report"]
                await websocket.send_json({
                    "type": "result",
                    "plan_id": report.plan_id,
                    "success": report.overall_success,
                    "total_duration_ms": report.total_duration_ms,
                    "actions": [
                        {
                            "action_id": r.action_id,
                            "success": r.success,
                            "message": r.message,
                            "duration_ms": r.duration_ms,
                        }
                        for r in report.results
                    ],
                })
                break
    except Exception as e:
        await websocket.send_json({"type": "error", "message": str(e)})


@app.get("/api/v1/plans")
async def list_plans():
    """查询历史生成的脚本文件。"""
    workspace = settings.workspace_dir
    if not workspace.exists():
        return {"plans": []}
    scripts = list(workspace.glob("plan_*.py"))
    return {
        "plans": [
            {
                "plan_id": f.stem.replace("plan_", ""),
                "file": str(f),
                "modified": f.stat().st_mtime,
            }
            for f in sorted(scripts, key=lambda f: f.stat().st_mtime, reverse=True)
        ]
    }


@app.get("/api/v1/health")
async def health():
    return {
        "status": "ok",
        "mock_mode": settings.ros.use_mock,
        "model": settings.llm.model,
    }
