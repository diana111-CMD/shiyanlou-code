#!/usr/bin/env python3
"""机械臂 ROS 节点封装 — 提供统一的控制接口。

此节点在真实 ROS 环境中运行，接收来自执行器的动作指令
并发布到机械臂控制话题。

用法：
  roslaunch 或在 roscore 运行后：
  python src/hardware/arm_node.py
"""

from __future__ import annotations

import json
import sys

try:
    import rospy
    from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
    from sensor_msgs.msg import JointState
except ImportError:
    print("ROS 环境未安装，请确保已 source /opt/ros/noetic/setup.bash")
    sys.exit(1)


class ArmController:
    """机械臂控制器 — 封装关节位姿和笛卡尔位姿控制。"""

    def __init__(
        self,
        cmd_topic: str = "/arm_controller/command",
        feedback_topic: str = "/arm_controller/feedback",
    ):
        self.pub = rospy.Publisher(cmd_topic, JointTrajectory, queue_size=10)
        self._current_state: dict = {}

        if feedback_topic:
            rospy.Subscriber(
                feedback_topic, JointState, self._state_callback,
            )

    def _state_callback(self, msg: JointState) -> None:
        self._current_state = {
            name: pos for name, pos in zip(msg.name, msg.position)
        }

    def move_to_pose(
        self,
        x: float, y: float, z: float,
        roll: float = 0, pitch: float = 0, yaw: float = 0,
        timeout: float = 10.0,
    ) -> bool:
        """移动到笛卡尔位姿。"""
        traj = JointTrajectory()
        traj.joint_names = [f"joint_{i}" for i in range(1, 7)]
        point = JointTrajectoryPoint()
        point.positions = [x, y, z, roll, pitch, yaw]
        point.time_from_start = rospy.Duration(timeout)
        traj.points.append(point)

        self.pub.publish(traj)
        rospy.loginfo(f"Arm move_to_pose published: ({x},{y},{z})")
        return True

    def move_joints(self, joint_positions: list[float], timeout: float = 10.0) -> bool:
        """直接控制关节角度。"""
        traj = JointTrajectory()
        traj.joint_names = [f"joint_{i}" for i in range(1, 7)]
        point = JointTrajectoryPoint()
        point.positions = joint_positions
        point.time_from_start = rospy.Duration(timeout)
        traj.points.append(point)

        self.pub.publish(traj)
        rospy.loginfo(f"Arm move_joints published: {joint_positions}")
        return True

    def open_gripper(self, width: float = 0.08) -> bool:
        """张开夹爪。"""
        return self.move_joints([width], timeout=1.0)

    def close_gripper(self, width: float = 0.0, force: float = 10.0) -> bool:
        """闭合夹爪。"""
        return self.move_joints([width, force], timeout=1.0)

    def get_current_pose(self) -> dict:
        """获取当前位姿。"""
        return self._current_state


def main():
    rospy.init_node("embodied_arm_controller")
    controller = ArmController()
    rospy.loginfo("Arm controller node started")
    rospy.spin()


if __name__ == "__main__":
    main()
