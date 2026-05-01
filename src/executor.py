"""执行器 — 运行生成的控制脚本并收集执行结果。

支持两种模式：
1. 直接执行 Python 脚本文件
2. 内存中直接调用内置动作（绕过代码生成，更快速）
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from src.config import settings
from src.logger import setup_logger
from src.models import (
    Action,
    ErrorLog,
    ExecutionReport,
    ExecutionResult,
    TaskPlan,
)

logger = setup_logger("executor", "EXECUTOR")


class Executor:
    """脚本执行引擎。"""

    def execute_script(self, script_path: Path) -> ExecutionReport:
        """执行生成的 Python 脚本并解析输出。

        Args:
            script_path: 生成的脚本文件路径

        Returns:
            ExecutionReport: 执行结果报告
        """
        logger.info(f"执行脚本: {script_path}")
        t0 = time.time()

        try:
            result = subprocess.run(
                ["python3", str(script_path)],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(settings.workspace_dir),
            )

            report = ExecutionReport(
                plan_id=script_path.stem.replace("plan_", ""),
                total_duration_ms=(time.time() - t0) * 1000,
            )

            # 解析 stdout 中的 JSON 结果
            if result.stdout.strip():
                try:
                    # 找最后一行 JSON
                    for line in reversed(result.stdout.strip().split("\n")):
                        try:
                            results_data = json.loads(line)
                            if isinstance(results_data, list):
                                report.results = [
                                    ExecutionResult(**r) for r in results_data
                                ]
                                break
                        except json.JSONDecodeError:
                            continue
                except Exception as e:
                    logger.warning(f"解析执行结果失败: {e}")

            # 检查 stderr 是否有错误
            if result.returncode != 0 or result.stderr:
                logger.error(f"脚本执行异常: {result.stderr}")
                report.overall_success = False
            else:
                report.overall_success = all(r.success for r in report.results)

            logger.info(
                f"执行完成: {len(report.results)} 个动作, "
                f"成功={report.overall_success}, "
                f"耗时={report.total_duration_ms:.0f}ms"
            )
            return report

        except subprocess.TimeoutExpired:
            logger.error("脚本执行超时 (120s)")
            return ExecutionReport(
                plan_id=script_path.stem.replace("plan_", ""),
                overall_success=False,
                total_duration_ms=120000,
            )
        except Exception as e:
            logger.error(f"执行器异常: {e}")
            return ExecutionReport(
                plan_id=script_path.stem.replace("plan_", ""),
                overall_success=False,
                total_duration_ms=(time.time() - t0) * 1000,
            )

    def execute_builtin(self, plan: TaskPlan) -> ExecutionReport:
        """内置执行器 — 不调用外部脚本，直接在内存中模拟/执行动作。

        适用于：
        - Mock 模式快速验证
        - 代码生成失败时的回退
        """
        logger.info(f"内置执行器开始，{len(plan.flat_sequence)} 个动作")
        report = ExecutionReport(plan_id=plan.plan_id)
        t0 = time.time()

        for action in plan.flat_sequence:
            action_t0 = time.time()
            try:
                logger.info(f"执行: [{action.action_type.value}] {action.description}")
                self._dispatch(action)
                dt = (time.time() - action_t0) * 1000
                report.results.append(
                    ExecutionResult(
                        action_id=action.action_id,
                        success=True,
                        message="OK",
                        duration_ms=dt,
                    )
                )
            except Exception as e:
                dt = (time.time() - action_t0) * 1000
                report.results.append(
                    ExecutionResult(
                        action_id=action.action_id,
                        success=False,
                        message=str(e),
                        duration_ms=dt,
                    )
                )
                logger.error(f"动作执行失败: {e}")

        report.total_duration_ms = (time.time() - t0) * 1000
        report.overall_success = all(r.success for r in report.results)
        return report

    def _dispatch(self, action: Action) -> None:
        """分发到具体动作处理器。"""
        handler = {
            "move_arm": self._move_arm,
            "grip_open": self._grip_open,
            "grip_close": self._grip_close,
            "move_vehicle": self._move_vehicle,
            "detect_object": self._detect_object,
            "wait": self._wait,
            "custom": self._custom,
        }
        fn = handler.get(action.action_type.value, self._custom)
        fn(action.params)

    def _move_arm(self, params: dict) -> None:
        if settings.ros.use_mock:
            import time as _t
            _t.sleep(0.5)
        else:
            self._ros_move_arm(params)

    def _grip_open(self, params: dict) -> None:
        if settings.ros.use_mock:
            import time as _t
            _t.sleep(0.3)
        else:
            self._ros_grip(params, open_grip=True)

    def _grip_close(self, params: dict) -> None:
        if settings.ros.use_mock:
            import time as _t
            _t.sleep(0.3)
        else:
            self._ros_grip(params, open_grip=False)

    def _move_vehicle(self, params: dict) -> None:
        if settings.ros.use_mock:
            import time as _t
            duration = params.get("duration", 1.0)
            _t.sleep(duration)
        else:
            self._ros_move_vehicle(params)

    def _detect_object(self, params: dict) -> None:
        if settings.ros.use_mock:
            import time as _t
            _t.sleep(0.5)
        else:
            self._ros_detect(params)

    def _wait(self, params: dict) -> None:
        import time as _t
        _t.sleep(params.get("duration", 1.0))

    def _custom(self, params: dict) -> None:
        logger.warning(f"自定义动作: {params}")

    # ── ROS 真实硬件调用（按需加载 rospy） ──

    def _ros_move_arm(self, params: dict) -> None:
        import rospy
        from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
        pub = rospy.Publisher(settings.ros.arm_topic, JointTrajectory, queue_size=10)
        traj = JointTrajectory()
        point = JointTrajectoryPoint()
        point.positions = [
            params.get("x", 0), params.get("y", 0), params.get("z", 0),
            params.get("roll", 0), params.get("pitch", 0), params.get("yaw", 0),
        ]
        point.time_from_start = rospy.Duration(3.0)
        traj.points.append(point)
        pub.publish(traj)

    def _ros_grip(self, params: dict, open_grip: bool) -> None:
        import rospy
        from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
        pub = rospy.Publisher(settings.ros.arm_topic, JointTrajectory, queue_size=10)
        traj = JointTrajectory()
        point = JointTrajectoryPoint()
        point.positions = [params.get("width", 0.08 if open_grip else 0.0)]
        point.time_from_start = rospy.Duration(1.0)
        traj.points.append(point)
        pub.publish(traj)

    def _ros_move_vehicle(self, params: dict) -> None:
        import rospy
        from geometry_msgs.msg import Twist
        pub = rospy.Publisher(settings.ros.vehicle_topic, Twist, queue_size=10)
        twist = Twist()
        twist.linear.x = params.get("linear_x", 0.0)
        twist.angular.z = params.get("angular_z", 0.0)
        rate = rospy.Rate(10)
        duration = params.get("duration", 1.0)
        start = rospy.Time.now()
        while (rospy.Time.now() - start).to_sec() < duration:
            pub.publish(twist)
            rate.sleep()

    def _ros_detect(self, params: dict) -> None:
        # TODO: 集成实际视觉节点
        logger.info(f"detect_object: {params}")


def collect_errors(
    report: ExecutionReport,
    plan: TaskPlan,
) -> list[ErrorLog]:
    """从执行报告中提取错误日志。"""
    import uuid
    from datetime import datetime

    errors = []
    action_map = {a.action_id: a for a in plan.flat_sequence}

    for result in report.failed_results:
        action = action_map.get(result.action_id)
        errors.append(
            ErrorLog(
                error_id=uuid.uuid4().hex[:12],
                action_id=result.action_id,
                action_type=action.action_type.value if action else "unknown",
                error_message=result.message,
                context={
                    "params": action.params if action else {},
                    "description": action.description if action else "",
                },
                timestamp=datetime.now().isoformat(),
            )
        )
    return errors
