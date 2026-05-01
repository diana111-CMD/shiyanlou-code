"""Agent 编排协调器 — 串联规划 → 代码生成 → 执行 → 自纠错的完整闭环。

状态机流程：
    用户指令 → PlanningAgent → CodeGenAgent → Executor
                                      ↓ fail
                              SelfCorrectAgent → (replan|regen|adjust)
                                      ↓
                                Executor → (repeat up to max_retries)
                                      ↓ success
                                返回最终报告
"""

from __future__ import annotations

import asyncio
from typing import Callable

from src.agents.codegen_agent import CodeGenAgent
from src.agents.planning_agent import PlanningAgent
from src.agents.self_correct_agent import SelfCorrectAgent
from src.config import settings
from src.executor import Executor, collect_errors
from src.llm_client import LLMClient
from src.logger import setup_logger
from src.models import ExecutionReport, TaskPlan

logger = setup_logger("orchestrator", "ORCH")


class Orchestrator:
    """多 Agent 协作编排器。"""

    def __init__(
        self,
        llm: LLMClient | None = None,
        use_builtin_executor: bool = True,
    ) -> None:
        self.llm = llm or LLMClient()
        self.planning_agent = PlanningAgent(self.llm)
        self.codegen_agent = CodeGenAgent(self.llm)
        self.self_correct_agent = SelfCorrectAgent(
            self.llm, self.planning_agent, self.codegen_agent,
        )
        self.executor = Executor()
        self.use_builtin = use_builtin_executor

        # 进度回调: (stage, message) -> None
        self.on_progress: Callable[[str, str], None] | None = None

    def _progress(self, stage: str, message: str) -> None:
        logger.info(f"[{stage}] {message}")
        if self.on_progress:
            self.on_progress(stage, message)

    def run(self, instruction: str) -> ExecutionReport:
        """执行完整的任务闭环：规划 → 生成 → 执行 → 纠错循环。

        Args:
            instruction: 用户的自然语言指令

        Returns:
            ExecutionReport: 最终执行报告
        """
        self._progress("START", f"收到指令: {instruction}")

        # Stage 1: 规划
        plan = self._stage_plan(instruction)

        # Stage 2: 生成代码
        self._stage_generate(plan)

        # Stage 3: 执行 + 自纠错循环
        report = self._stage_execute_with_correction(plan)

        status = "成功" if report.overall_success else "失败"
        self._progress("DONE", f"任务{status}: {len(report.results)} 个动作")
        return report

    def _stage_plan(self, instruction: str) -> TaskPlan:
        self._progress("PLAN", "开始任务规划...")
        plan = self.planning_agent.plan(instruction)
        self._progress(
            "PLAN",
            f"规划完成: {len(plan.flat_sequence)} 个原子动作\n"
            f"推理: {plan.reasoning_chain[:200]}...",
        )
        return plan

    def _stage_generate(self, plan: TaskPlan) -> None:
        self._progress("CODEGEN", "开始生成控制脚本...")
        # 优先使用模板生成（更快更稳定），LLM 生成作为备选
        script_path = self.codegen_agent.generate_from_template(plan)
        self._progress("CODEGEN", f"脚本生成完成: {script_path}")

    def _stage_execute_with_correction(self, plan: TaskPlan) -> ExecutionReport:
        retries = 0
        max_retries = settings.agent.max_code_retries

        while retries <= max_retries:
            if retries > 0:
                self._progress("RETRY", f"第 {retries} 次重试...")

            # 执行
            if self.use_builtin:
                report = self.executor.execute_builtin(plan)
            else:
                script = self.codegen_agent.generate_from_template(plan)
                report = self.executor.execute_script(script)

            self._progress(
                "EXEC",
                f"执行结果: 成功={report.overall_success}, "
                f"失败动作={len(report.failed_results)}/{len(report.results)}",
            )

            if report.overall_success:
                return report

            # 分析错误
            errors = collect_errors(report, plan)
            self._progress("CORRECT", f"发现 {len(errors)} 个错误，开始自纠错分析...")

            fixed_plan = self.self_correct_agent.analyze_and_fix(report, plan, errors)
            if fixed_plan is not None:
                plan = fixed_plan
                self._progress("CORRECT", "纠错成功，使用新计划重新执行")
            else:
                self._progress("CORRECT", "无法自动修复，停止重试")
                break

            retries += 1

        return report

    # ── 流式 API 支持 ──

    async def run_stream(self, instruction: str):
        """异步流式执行，yield 进度事件和最终结果。

        Yields:
            dict: {"type": "progress", "stage": ..., "message": ...}
               or {"type": "result", "report": ExecutionReport}
        """
        self._progress("START", f"收到指令: {instruction}")
        yield {"type": "progress", "stage": "START", "message": f"收到指令: {instruction}"}

        plan = self._stage_plan(instruction)
        yield {"type": "progress", "stage": "PLAN", "message": plan.reasoning_chain}
        yield {"type": "progress", "stage": "PLAN", "message": f"分解为 {len(plan.flat_sequence)} 个原子动作"}

        self._stage_generate(plan)
        yield {"type": "progress", "stage": "CODEGEN", "message": "脚本已生成"}

        retries = 0
        max_retries = settings.agent.max_code_retries

        while retries <= max_retries:
            if self.use_builtin:
                report = self.executor.execute_builtin(plan)
            else:
                script = self.codegen_agent.generate_from_template(plan)
                report = self.executor.execute_script(script)

            yield {"type": "progress", "stage": "EXEC", "message": f"执行: 成功={report.overall_success}"}

            if report.overall_success:
                yield {"type": "result", "report": report}
                return

            errors = collect_errors(report, plan)
            fixed_plan = self.self_correct_agent.analyze_and_fix(report, plan, errors)

            if fixed_plan is not None:
                plan = fixed_plan
                yield {"type": "progress", "stage": "CORRECT", "message": "已修正，重试"}
            else:
                yield {"type": "progress", "stage": "CORRECT", "message": "无法修复"}
                break

            retries += 1

        yield {"type": "result", "report": report}
