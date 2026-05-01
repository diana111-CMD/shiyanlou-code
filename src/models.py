"""系统核心数据模型 — 任务、动作、执行结果、错误日志等。"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ─────────────────────────── 任务树 ───────────────────────────

class ActionType(str, Enum):
    """原子动作类型枚举。"""
    MOVE_ARM = "move_arm"            # 机械臂移动到目标位姿
    GRIP_OPEN = "grip_open"          # 夹爪张开
    GRIP_CLOSE = "grip_close"        # 夹爪闭合
    MOVE_VEHICLE = "move_vehicle"    # 智能车移动到目标点
    DETECT_OBJECT = "detect_object"  # 视觉检测
    WAIT = "wait"                    # 等待/延时
    CUSTOM = "custom"                # 自定义动作


class Action(BaseModel):
    """原子动作 — 任务树的叶子节点。"""
    action_id: str
    action_type: ActionType
    description: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    preconditions: list[str] = Field(default_factory=list)
    expected_outcome: str = ""


class TaskNode(BaseModel):
    """任务分解树的节点。"""
    task_id: str
    name: str
    description: str = ""
    action: Action | None = None
    children: list[TaskNode] = Field(default_factory=list)
    status: TaskStatus = Field(default=TaskStatus.PENDING)

    def is_leaf(self) -> bool:
        return len(self.children) == 0


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ─────────────────────────── 任务计划 ───────────────────────────

class TaskPlan(BaseModel):
    """完整的任务计划 — 由感知与规划 Agent 产出。"""
    plan_id: str
    original_instruction: str
    task_tree: TaskNode
    reasoning_chain: str = Field(description="长链推理过程的文本")
    flat_sequence: list[Action] = Field(
        default_factory=list,
        description="任务树扁平化后的线性动作序列",
    )


# ─────────────────────────── 执行结果 ───────────────────────────

class ExecutionResult(BaseModel):
    action_id: str
    success: bool
    message: str = ""
    duration_ms: float = 0
    sensor_data: dict[str, Any] = Field(default_factory=dict)


class ExecutionReport(BaseModel):
    """一次任务执行的完整报告。"""
    plan_id: str
    results: list[ExecutionResult] = Field(default_factory=list)
    overall_success: bool = True
    total_duration_ms: float = 0

    @property
    def failed_results(self) -> list[ExecutionResult]:
        return [r for r in self.results if not r.success]


# ─────────────────────────── 错误日志 ───────────────────────────

class ErrorLog(BaseModel):
    """执行失败时的错误日志 — 供自纠错 Agent 分析。"""
    error_id: str
    action_id: str
    action_type: str
    error_message: str
    traceback: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = ""
