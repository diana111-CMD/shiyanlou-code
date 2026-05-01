#!/usr/bin/env python3
"""智能车 ROS 节点封装 — 提供速度控制和里程计反馈。

用法：
  roslaunch 或在 roscore 运行后：
  python src/hardware/vehicle_node.py
"""

from __future__ import annotations

import sys

try:
    import rospy
    from geometry_msgs.msg import Twist, Pose
    from nav_msgs.msg import Odometry
except ImportError:
    print("ROS 环境未安装，请确保已 source /opt/ros/noetic/setup.bash")
    sys.exit(1)


class VehicleController:
    """智能车控制器 — 封装速度指令和位置反馈。"""

    def __init__(
        self,
        cmd_topic: str = "/vehicle/cmd_vel",
        odom_topic: str = "/vehicle/odom",
    ):
        self.pub = rospy.Publisher(cmd_topic, Twist, queue_size=10)
        self._current_pose = Pose()

        if odom_topic:
            rospy.Subscriber(odom_topic, Odometry, self._odom_callback)

    def _odom_callback(self, msg: Odometry) -> None:
        self._current_pose = msg.pose.pose

    def move(
        self,
        linear_x: float = 0.0,
        angular_z: float = 0.0,
        duration: float = 1.0,
    ) -> bool:
        """以指定速度行驶指定时长。"""
        twist = Twist()
        twist.linear.x = linear_x
        twist.angular.z = angular_z

        rate = rospy.Rate(10)
        start = rospy.Time.now()
        while (rospy.Time.now() - start).to_sec() < duration:
            self.pub.publish(twist)
            rate.sleep()

        # 停止
        self.pub.publish(Twist())
        rospy.loginfo(f"Vehicle move: linear={linear_x}, angular={angular_z}, duration={duration}s")
        return True

    def move_to(self, x: float, y: float, theta: float) -> bool:
        """移动到目标位置（简易实现，实际需集成导航栈）。"""
        # TODO: 集成 move_base / nav2
        rospy.logwarn("move_to: 需要集成导航栈，当前为占位实现")
        return False

    def stop(self) -> None:
        """紧急停止。"""
        self.pub.publish(Twist())
        rospy.loginfo("Vehicle STOP")

    def get_current_pose(self) -> Pose:
        """获取当前位置。"""
        return self._current_pose


def main():
    rospy.init_node("embodied_vehicle_controller")
    controller = VehicleController()
    rospy.loginfo("Vehicle controller node started")
    rospy.spin()


if __name__ == "__main__":
    main()
