"""代码生成 Agent — 将任务计划中的动作序列转化为可执行的 Python/ROS 控制脚本。

核心流程：
1. 接收扁平化的动作序列 (TaskPlan.flat_sequence)
2. 通过 LLM 生成完整的可执行 Python 脚本
3. 脚本包含 ROS 通信、错误处理和安全检查
4. 输出到 workspace 目录供执行器运行
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

from src.config import settings
from src.llm_client import LLMClient
from src.logger import setup_logger
from src.models import Action, ActionType, TaskPlan

logger = setup_logger("code_gen_agent", "CODEGEN")

SYSTEM_PROMPT = """你是一个具身智能控制代码生成专家。你需要将抽象的动作序列
转化为可直接执行的 Python 控制脚本。

## 代码要求
1. 使用 Python 3，脚本必须自包含、可直接运行
2. 使用 ROS (rospy) 进行通信（如果 ros.use_mock=False）
3. 每个动作执行前后都要有日志输出
4. 包含基本的异常处理，失败时抛出详细的 RuntimeError
5. 脚本末尾返回 JSON 格式的执行结果到 stdout
6. 包含超时保护，每个动作执行时间不超过 15 秒

## 硬件接口

### 机械臂
- 话题: {arm_topic}
- 消息类型: trajectory_msgs/JointTrajectory
- 位姿控制: 通过关节角度 {joint1..joint6} 或笛卡尔坐标 {x,y,z,roll,pitch,yaw}

### 智能车
- 话题: {vehicle_topic}
- 消息类型: geometry_msgs/Twist
- 速度控制: linear.x (前进/后退), angular.z (转向)

### 相机
- 话题: {camera_topic}
- 消息类型: sensor_msgs/Image

## 输出格式
仅输出 Python 代码，不要任何 markdown 标记或额外文字。"""


class CodeGenAgent:
    """代码生成 Agent。"""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()
        self._workspace = settings.workspace_dir
        self._workspace.mkdir(parents=True, exist_ok=True)

    def generate(self, plan: TaskPlan) -> Path:
        """根据任务计划生成可执行 Python 脚本。

        Args:
            plan: 已扁平化的任务计划

        Returns:
            Path: 生成的脚本文件路径
        """
        logger.info(f"开始生成脚本，动作数: {len(plan.flat_sequence)}")

        system_prompt = SYSTEM_PROMPT.format(
            arm_topic=settings.ros.arm_topic,
            vehicle_topic=settings.ros.vehicle_topic,
            camera_topic=settings.ros.camera_topic,
        )

        action_descriptions = self._format_actions(plan.flat_sequence)
        user_prompt = (
            f"请为以下动作序列生成可执行的 Python 控制脚本：\n\n"
            f"计划 ID: {plan.plan_id}\n"
            f"动作序列:\n{action_descriptions}\n\n"
            f"模式: {'mock (模拟执行，无需 ROS)' if settings.ros.use_mock else 'ROS (真实硬件)'}\n\n"
            f"生成的脚本需要：\n"
            f"1. 按顺序执行上述动作\n"
            f"2. 每个动作执行结果记录到 results 列表\n"
            f"3. 最后打印 JSON 结果: print(json.dumps(results))\n"
            f"4. 包含 def main() 函数和 if __name__ == '__main__' 入口"
        )

        code = self.llm.chat(
            system_prompt,
            user_prompt,
            max_tokens=settings.llm.max_tokens,
        )

        # 清理可能的 markdown 围栏
        code = self._strip_markdown(code)

        script_path = self._workspace / f"plan_{plan.plan_id}.py"
        script_path.write_text(code, encoding="utf-8")
        logger.info(f"脚本已生成: {script_path}")
        return script_path

    def generate_from_template(
        self,
        plan: TaskPlan,
    ) -> Path:
        """基于内置模板生成脚本（比 LLM 更快、更可靠）。

        当 LLM 生成结果不稳定时，回退到此方法。
        """
        logger.info("使用模板方式生成脚本")

        actions = plan.flat_sequence
        code_lines = [
            '#!/usr/bin/env python3',
            '"""Auto-generated control script by CodeGen Agent."""',
            'import json',
            'import time',
            'import traceback',
            '',
        ]

        if not settings.ros.use_mock:
            code_lines += [
                'import rospy',
                'from geometry_msgs.msg import Twist, PoseStamped',
                'from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint',
                '',
            ]

        code_lines += [
            'import logging',
            'logging.basicConfig(level=logging.INFO)',
            'logger = logging.getLogger("executor")',
            '',
            'results = []',
            '',
            'def record(action_id, success, message="", duration=0):',
            '    results.append({',
            '        "action_id": action_id,',
            '        "success": success,',
            '        "message": message,',
            '        "duration_ms": duration,',
            '    })',
            '',
        ]

        if settings.ros.use_mock:
            code_lines += self._mock_functions()
        else:
            code_lines += self._ros_functions()

        code_lines.append('def main():')
        for action in actions:
            code_lines += self._action_call(action)

        code_lines += [
            '',
            '    print(json.dumps(results))',
            '',
            'if __name__ == "__main__":',
            '    main()',
        ]

        script_path = self._workspace / f"plan_{plan.plan_id}.py"
        script_path.write_text("\n".join(code_lines), encoding="utf-8")
        logger.info(f"模板脚本已生成: {script_path}")
        return script_path

    def _format_actions(self, actions: list[Action]) -> str:
        lines = []
        for i, a in enumerate(actions, 1):
            lines.append(f"  {i}. [{a.action_type.value}] {a.description}")
            lines.append(f"     params: {a.params}")
            if a.preconditions:
                lines.append(f"     preconditions: {a.preconditions}")
            lines.append("")
        return "\n".join(lines)

    def _strip_markdown(self, code: str) -> str:
        code = code.strip()
        if code.startswith("```python"):
            code = code[len("```python"):].strip()
        if code.startswith("```"):
            code = code[3:].strip()
        if code.endswith("```"):
            code = code[:-3].strip()
        return code

    def _mock_functions(self) -> list[str]:
        return [
            'def move_arm_mock(x, y, z, roll=0, pitch=0, yaw=0):',
            '    logger.info(f"[MOCK] move_arm to ({x},{y},{z}, r={roll},p={pitch},y={yaw})")',
            '    time.sleep(0.5)',
            '',
            'def grip_open_mock(width=0.08):',
            '    logger.info(f"[MOCK] grip_open width={width}")',
            '    time.sleep(0.3)',
            '',
            'def grip_close_mock(width=0.0, force=10.0):',
            '    logger.info(f"[MOCK] grip_close width={width} force={force}")',
            '    time.sleep(0.3)',
            '',
            'def move_vehicle_mock(x=0, y=0, theta=0, linear_x=0, angular_z=0, duration=1.0):',
            '    logger.info(f"[MOCK] move_vehicle x={x} y={y} theta={theta}")',
            '    time.sleep(duration)',
            '',
            'def detect_object_mock(target_class="object", camera_frame="base_link"):',
            '    logger.info(f"[MOCK] detect_object target={target_class}")',
            '    time.sleep(0.5)',
            '    return {"detected": True, "position": {"x": 0.3, "y": 0.1, "z": 0.2}}',
            '',
            'def wait_mock(duration=1.0):',
            '    logger.info(f"[MOCK] wait {duration}s")',
            '    time.sleep(duration)',
            '',
        ]

    def _ros_functions(self) -> list[str]:
        return [
            f'ARM_TOPIC = "{settings.ros.arm_topic}"',
            f'VEHICLE_TOPIC = "{settings.ros.vehicle_topic}"',
            '',
            'def move_arm_ros(x, y, z, roll=0, pitch=0, yaw=0, timeout=10.0):',
            '    pub = rospy.Publisher(ARM_TOPIC, JointTrajectory, queue_size=10)',
            '    traj = JointTrajectory()',
            '    point = JointTrajectoryPoint()',
            '    point.positions = [x, y, z, roll, pitch, yaw]',
            '    point.time_from_start = rospy.Duration(timeout)',
            '    traj.points.append(point)',
            '    pub.publish(traj)',
            '    logger.info(f"move_arm published to {ARM_TOPIC}")',
            '',
            'def grip_open_ros(width=0.08, timeout=5.0):',
            '    pub = rospy.Publisher(ARM_TOPIC, JointTrajectory, queue_size=10)',
            '    traj = JointTrajectory()',
            '    point = JointTrajectoryPoint()',
            '    point.positions = [width]',
            '    point.time_from_start = rospy.Duration(timeout)',
            '    traj.points.append(point)',
            '    pub.publish(traj)',
            '',
            'def grip_close_ros(width=0.0, force=10.0, timeout=5.0):',
            '    pub = rospy.Publisher(ARM_TOPIC, JointTrajectory, queue_size=10)',
            '    traj = JointTrajectory()',
            '    point = JointTrajectoryPoint()',
            '    point.positions = [width, force]',
            '    point.time_from_start = rospy.Duration(timeout)',
            '    traj.points.append(point)',
            '    pub.publish(traj)',
            '',
            'def move_vehicle_ros(linear_x=0.0, angular_z=0.0, duration=1.0):',
            '    pub = rospy.Publisher(VEHICLE_TOPIC, Twist, queue_size=10)',
            '    twist = Twist()',
            '    twist.linear.x = linear_x',
            '    twist.angular.z = angular_z',
            '    rate = rospy.Rate(10)',
            '    start = rospy.Time.now()',
            '    while (rospy.Time.now() - start).to_sec() < duration:',
            '        pub.publish(twist)',
            '        rate.sleep()',
            '',
            'def detect_object_ros(target_class="object"):',
            '    logger.info(f"detect_object: {target_class} (TODO: integrate vision node)")',
            '    return {"detected": False, "position": {}}',
            '',
            'def wait_ros(duration=1.0):',
            '    rospy.sleep(duration)',
            '',
        ]

    def _action_call(self, action: Action) -> list[str]:
        prefix = "mock" if settings.ros.use_mock else "ros"
        action_type = action.action_type.value
        params = action.params

        call_map = {
            "move_arm": f"move_arm_{prefix}",
            "grip_open": f"grip_open_{prefix}",
            "grip_close": f"grip_close_{prefix}",
            "move_vehicle": f"move_vehicle_{prefix}",
            "detect_object": f"detect_object_{prefix}",
            "wait": f"wait_{prefix}",
            "custom": "custom_action",
        }

        func = call_map.get(action_type, f"move_arm_{prefix}")
        param_str = ", ".join(f"{k}={v!r}" for k, v in params.items()) if params else ""

        return [
            f'    try:',
            f'        t0 = time.time()',
            f'        {func}({param_str})',
            f'        dt = (time.time() - t0) * 1000',
            f'        record("{action.action_id}", True, "OK", dt)',
            f'    except Exception as e:',
            f'        record("{action.action_id}", False, str(e), 0)',
            f'        traceback.print_exc()',
            f'',
        ]
