"""自纠错 Agent — 分析执行错误日志并重写控制逻辑，实现闭环。

核心流程：
1. 接收执行失败的错误日志
2. LLM 分析根因：是代码问题、环境问题还是规划问题
3. 根据分析结果选择策略：
   - 代码 Bug → 重写生成控制脚本
   - 规划不合理 → 触发重新规划
   - 环境异常 → 调整参数后重试
4. 返回修正后的脚本或新的计划
"""

from __future__ import annotations

from typing import Any

from src.agents.codegen_agent import CodeGenAgent
from src.agents.planning_agent import PlanningAgent
from src.config import settings
from src.llm_client import LLMClient
from src.logger import setup_logger
from src.models import ErrorLog, ExecutionReport, TaskPlan

logger = setup_logger("self_correct_agent", "SELF_FIX")

ANALYSIS_SYSTEM_PROMPT = """你是一个具身智能系统的自纠错专家。你的任务是分析执行失败的日志，
找出根因并给出修正方案。

## 常见的错误类型
1. CODE_BUG: 生成的控制代码存在语法错误或逻辑缺陷
2. PLANNING_ERROR: 任务规划不合理，如前置条件不满足、动作顺序错误
3. HARDWARE_LIMIT: 硬件能力不足，如到达限位、扭矩不足
4. ENVIRONMENT_CHANGE: 环境变化导致执行失败，如物体被移动、障碍物出现
5. TIMEOUT: 动作执行超时，可能卡死或传感器无响应
6. COMMUNICATION_ERROR: ROS 通信中断或话题未发布

## 输出 JSON 格式
{
    "analysis": "详细的根因分析",
    "error_type": "CODE_BUG|PLANNING_ERROR|HARDWARE_LIMIT|ENVIRONMENT_CHANGE|TIMEOUT|COMMUNICATION_ERROR",
    "confidence": 0.0-1.0,
    "fix_strategy": "具体的修正方案描述",
    "needs_replan": true/false,
    "needs_regen": true/false,
    "needs_param_adjust": true/false,
    "param_adjustments": {"key": "new_value"}
}"""


class SelfCorrectAgent:
    """自纠错 Agent。"""

    def __init__(
        self,
        llm: LLMClient | None = None,
        planning_agent: PlanningAgent | None = None,
        codegen_agent: CodeGenAgent | None = None,
    ) -> None:
        self.llm = llm or LLMClient()
        self.planning_agent = planning_agent or PlanningAgent(self.llm)
        self.codegen_agent = codegen_agent or CodeGenAgent(self.llm)

    def analyze_and_fix(
        self,
        report: ExecutionReport,
        plan: TaskPlan,
        errors: list[ErrorLog],
    ) -> TaskPlan | None:
        """分析错误并自动修复。

        Args:
            report: 执行报告
            plan: 原始计划
            errors: 错误日志列表

        Returns:
            修正后的新 TaskPlan，或 None（如果无法修复）
        """
        logger.info(f"自纠错启动: {len(errors)} 个错误需要分析")

        # Step 1: 分析根因
        analysis = self._analyze_errors(errors, plan)
        logger.info(
            f"分析结果: type={analysis['error_type']}, "
            f"confidence={analysis['confidence']}, "
            f"replan={analysis['needs_replan']}, "
            f"regen={analysis['needs_regen']}"
        )

        # Step 2: 根据策略修复
        if analysis["needs_replan"] or analysis["error_type"] == "PLANNING_ERROR":
            return self._fix_by_replan(plan, analysis, errors)

        if analysis["needs_regen"]:
            return self._fix_by_regen(plan, analysis)

        if analysis["needs_param_adjust"]:
            return self._fix_by_adjust(plan, analysis)

        logger.warning("无法确定修复策略")
        return None

    def _analyze_errors(
        self, errors: list[ErrorLog], plan: TaskPlan
    ) -> dict[str, Any]:
        """调用 LLM 分析错误日志。"""
        error_texts = []
        for i, e in enumerate(errors, 1):
            error_texts.append(
                f"  错误 {i}: action={e.action_id} ({e.action_type})\n"
                f"    message: {e.error_message}\n"
                f"    context: {e.context}"
            )

        user_prompt = (
            f"任务计划: {plan.original_instruction}\n\n"
            f"推理链: {plan.reasoning_chain[:500]}\n\n"
            f"执行错误日志:\n" + "\n".join(error_texts) + "\n\n"
            f"请分析根因并给出修正方案。"
        )

        schema = {
            "type": "object",
            "required": [
                "analysis", "error_type", "confidence",
                "fix_strategy", "needs_replan", "needs_regen",
                "needs_param_adjust",
            ],
            "properties": {
                "analysis": {"type": "string"},
                "error_type": {
                    "type": "string",
                    "enum": [
                        "CODE_BUG", "PLANNING_ERROR", "HARDWARE_LIMIT",
                        "ENVIRONMENT_CHANGE", "TIMEOUT", "COMMUNICATION_ERROR",
                    ],
                },
                "confidence": {"type": "number"},
                "fix_strategy": {"type": "string"},
                "needs_replan": {"type": "boolean"},
                "needs_regen": {"type": "boolean"},
                "needs_param_adjust": {"type": "boolean"},
                "param_adjustments": {"type": "object"},
            },
        }

        return self.llm.chat_json(
            ANALYSIS_SYSTEM_PROMPT, user_prompt, schema=schema,
        )

    def _fix_by_replan(
        self, plan: TaskPlan, analysis: dict, errors: list[ErrorLog],
    ) -> TaskPlan | None:
        """通过重新规划来修复。"""
        logger.info("策略: 重新规划任务")
        error_context = (
            f"分析: {analysis['analysis']}\n"
            f"修复方案: {analysis['fix_strategy']}\n"
            f"错误详情: {[e.error_message for e in errors]}"
        )
        return self.planning_agent.replan(plan.original_instruction, error_context)

    def _fix_by_regen(
        self, plan: TaskPlan, analysis: dict,
    ) -> TaskPlan | None:
        """通过重新生成代码来修复。"""
        logger.info("策略: 重新生成控制脚本")
        # 更新计划中的动作参数（如果有调整建议）
        if analysis.get("param_adjustments"):
            for action in plan.flat_sequence:
                for key, val in analysis["param_adjustments"].items():
                    if key in action.params:
                        action.params[key] = val
        return plan  # 返回原计划，由编排器触发代码重新生成

    def _fix_by_adjust(
        self, plan: TaskPlan, analysis: dict,
    ) -> TaskPlan | None:
        """通过调整参数来修复。"""
        logger.info("策略: 调整参数后重试")
        adjustments = analysis.get("param_adjustments", {})
        for action in plan.flat_sequence:
            for key, val in adjustments.items():
                action.params[key] = val
        return plan
