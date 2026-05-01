"""感知与规划 Agent — 将人类自然语言模糊指令拆解为原子动作序列树。

核心流程：
1. 接收自然语言指令
2. 通过长链推理（Chain of Thought）理解意图与环境约束
3. 将宏观目标拆解为有序的任务树
4. 扁平化为可执行的线性动作序列
"""

from __future__ import annotations

import uuid
from typing import Any

from src.config import settings
from src.llm_client import LLMClient
from src.logger import setup_logger
from src.models import (
    Action,
    ActionType,
    TaskNode,
    TaskPlan,
    TaskStatus,
)

logger = setup_logger("planning_agent", "PLANNING")

# ── JSON Schema for task plan output ──

ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["action_id", "action_type", "description", "params", "preconditions", "expected_outcome"],
    "properties": {
        "action_id": {"type": "string"},
        "action_type": {
            "type": "string",
            "enum": [e.value for e in ActionType],
        },
        "description": {"type": "string"},
        "params": {"type": "object"},
        "preconditions": {"type": "array", "items": {"type": "string"}},
        "expected_outcome": {"type": "string"},
    },
}

TASK_NODE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["task_id", "name", "description", "action", "children"],
    "properties": {
        "task_id": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "action": ACTION_SCHEMA,
        "children": {
            "type": "array",
            "items": {"$ref": "#"},
        },
    },
}

PLAN_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["plan_id", "reasoning_chain", "task_tree", "flat_sequence"],
    "properties": {
        "plan_id": {"type": "string"},
        "reasoning_chain": {"type": "string"},
        "task_tree": TASK_NODE_SCHEMA,
        "flat_sequence": {
            "type": "array",
            "items": ACTION_SCHEMA,
        },
    },
}

SYSTEM_PROMPT = """你是一个具身智能任务规划专家。你负责接收人类的自然语言指令，
将其拆解为精确的、包含时间顺序的原子动作序列。

## 可用动作类型
- move_arm: 机械臂移动到目标位姿，参数包含 {x, y, z, roll, pitch, yaw}
- grip_open: 夹爪张开，参数包含 {width}
- grip_close: 夹爪闭合，参数包含 {width, force}
- move_vehicle: 智能车移动，参数包含 {x, y, theta} 或 {linear_x, angular_z, duration}
- detect_object: 视觉检测，参数包含 {target_class, camera_frame}
- wait: 等待，参数包含 {duration}
- custom: 自定义动作，参数自由定义

## 规划原则
1. 每个复杂任务必须先检测环境/物体位置，再执行操作
2. 机械臂操作遵循：移动到预位 → 张开夹爪 → 移动到抓取位 → 闭合夹爪 → 抬起 → 移动到放置位 → 张开夹爪
3. 智能车移动前先确认路径无障碍
4. 子任务之间必须有明确的前置条件 (preconditions)
5. 拆解深度不超过 {max_depth} 层

## 输出格式
你必须输出严格的 JSON，包含：
- plan_id: 唯一计划 ID
- reasoning_chain: 详细的长链推理过程，说明你是如何理解指令并拆解的
- task_tree: 层次化的任务树
- flat_sequence: 扁平化后的线性动作序列（叶子节点的执行顺序）"""


class PlanningAgent:
    """感知与规划 Agent。"""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    def plan(self, instruction: str) -> TaskPlan:
        """接收自然语言指令，输出完整任务计划。

        Args:
            instruction: 人类的自然语言模糊指令

        Returns:
            TaskPlan: 包含任务树和线性动作序列的计划
        """
        logger.info(f"收到指令: {instruction}")

        system_prompt = SYSTEM_PROMPT.format(max_depth=settings.agent.max_planning_depth)
        user_prompt = f"请对以下指令进行任务规划：\n\n{instruction}"

        raw = self.llm.chat_json(
            system_prompt,
            user_prompt,
            schema=PLAN_OUTPUT_SCHEMA,
            max_tokens=settings.llm.max_tokens,
        )

        plan = self._parse_plan(raw, instruction)
        logger.info(f"计划生成完成: {len(plan.flat_sequence)} 个原子动作")
        return plan

    def _parse_plan(self, raw: dict, instruction: str) -> TaskPlan:
        """将 LLM 输出的 JSON 解析为 TaskPlan 对象。"""
        plan_id = raw.get("plan_id", uuid.uuid4().hex[:12])
        reasoning = raw.get("reasoning_chain", "")

        task_tree = self._build_task_tree(raw.get("task_tree", {}))
        flat_sequence = [
            Action(**a) for a in raw.get("flat_sequence", [])
        ]

        return TaskPlan(
            plan_id=plan_id,
            original_instruction=instruction,
            task_tree=task_tree,
            reasoning_chain=reasoning,
            flat_sequence=flat_sequence,
        )

    def _build_task_tree(self, data: dict) -> TaskNode:
        """递归构建任务树。"""
        action_data = data.get("action")
        action = Action(**action_data) if action_data else None

        children = [
            self._build_task_tree(c) for c in data.get("children", [])
        ]

        return TaskNode(
            task_id=data.get("task_id", uuid.uuid4().hex[:8]),
            name=data.get("name", ""),
            description=data.get("description", ""),
            action=action,
            children=children,
            status=TaskStatus.PENDING,
        )

    def replan(
        self,
        original_instruction: str,
        error_context: str,
    ) -> TaskPlan:
        """根据执行失败的上下文重新规划。

        Args:
            original_instruction: 原始自然语言指令
            error_context: 失败原因和当前环境状态
        """
        logger.info(f"重新规划，原因: {error_context}")

        system_prompt = SYSTEM_PROMPT.format(max_depth=settings.agent.max_planning_depth)
        user_prompt = (
            f"原始指令: {original_instruction}\n\n"
            f"执行失败上下文: {error_context}\n\n"
            f"请根据上述失败信息重新规划任务。"
        )

        raw = self.llm.chat_json(
            system_prompt,
            user_prompt,
            schema=PLAN_OUTPUT_SCHEMA,
        )
        return self._parse_plan(raw, original_instruction)
