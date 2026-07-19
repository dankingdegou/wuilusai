from __future__ import annotations

import argparse

import rclpy
from rclpy.action import ActionClient

from wuliusai_stepper_msgs.action import ExecuteScoop


def main() -> None:
    parser = argparse.ArgumentParser(description="发送一铲取料比赛任务")
    parser.add_argument("bean_type", choices=("mung_bean", "soybean", "white_bean"))
    parser.add_argument("slot", type=int, choices=(4, 5, 6, 7))
    args = parser.parse_args()
    rclpy.init()
    node = rclpy.create_node("competition_task_client")
    client = ActionClient(node, ExecuteScoop, "/competition/execute_scoop")
    try:
        if not client.wait_for_server(timeout_sec=5.0):
            raise RuntimeError("competition demo action server is unavailable")
        goal = ExecuteScoop.Goal(); goal.bean_type = args.bean_type; goal.target_slot = args.slot
        handle = client.send_goal_async(goal, feedback_callback=lambda event: print(
            f"[{event.feedback.phase}] x={event.feedback.x:.1f}, y={event.feedback.y:.1f}, "
            f"z={event.feedback.z:.0f} pulses"))
        rclpy.spin_until_future_complete(node, handle)
        goal_handle = handle.result()
        if not goal_handle.accepted:
            raise RuntimeError("task rejected: calibration or destination is incomplete")
        done = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(node, done)
        result = done.result().result
        print(f"success={result.success}; {result.message}")
        print(f"source=({result.source_x:.1f}, {result.source_y:.1f}), target=({result.target_x:.1f}, {result.target_y:.1f})")
    finally:
        node.destroy_node(); rclpy.shutdown()


if __name__ == "__main__":
    main()
