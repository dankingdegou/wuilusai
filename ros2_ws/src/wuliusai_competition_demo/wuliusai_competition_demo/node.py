from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import rclpy
import yaml
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from wuliusai_stepper_msgs.action import ExecuteScoop, MoveGantry
from wuliusai_stepper_msgs.srv import StopAxis

from .calibration import valid_waypoint, within_field
from .vision_pipeline import SUPPORTED_BEANS, ScoopVision


class CompetitionDemo(Node):
    """One source-box scoop and one destination drop; X is real, tool axes simulated."""
    def __init__(self) -> None:
        super().__init__("competition_demo")
        self.declare_parameter("config_file", "")
        raw_path = str(self.get_parameter("config_file").value)
        if not raw_path:
            raise ValueError("set the required config_file parameter")
        self.config_path = Path(raw_path).expanduser().resolve()
        with self.config_path.open(encoding="utf-8") as stream:
            self.config: dict[str, Any] = yaml.safe_load(stream) or {}
        self.vision = ScoopVision(self.config, self.config_path)
        self.group = ReentrantCallbackGroup()
        motion = self.config.get("motion", {})
        self.gantry = ActionClient(self, MoveGantry, str(motion.get("gantry_action", "/stepper_controller/move_gantry")),
                                   callback_group=self.group)
        self.stop = self.create_client(StopAxis, str(motion.get("stop_service", "/stepper_controller/stop")),
                                       callback_group=self.group)
        self.server = ActionServer(self, ExecuteScoop, "/competition/execute_scoop", self.execute,
                                   goal_callback=self.goal_callback, cancel_callback=self.cancel_callback,
                                   callback_group=self.group)
        self.get_logger().info("competition demo ready: X gantry real; Y/Z/bucket simulation enabled")

    def goal_callback(self, request: ExecuteScoop.Goal) -> GoalResponse:
        if request.bean_type not in SUPPORTED_BEANS or request.target_slot not in (4, 5, 6, 7):
            return GoalResponse.REJECT
        destination = valid_waypoint(self.config.get("destination_slots_mm", {}).get(str(request.target_slot)))
        if destination is None or not within_field(destination, self.config):
            self.get_logger().error("goal rejected: destination waypoint is not taught")
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    @staticmethod
    def cancel_callback(_goal_handle) -> CancelResponse:
        return CancelResponse.ACCEPT

    @staticmethod
    def _feedback(goal_handle, phase: str, point: tuple[float, float]) -> None:
        feedback = ExecuteScoop.Feedback()
        feedback.phase, feedback.x, feedback.y = phase, point[0], point[1]
        goal_handle.publish_feedback(feedback)

    async def _stop_all(self) -> None:
        if not self.stop.service_is_ready():
            self.stop.wait_for_service(timeout_sec=0.5)
        if self.stop.service_is_ready():
            request = StopAxis.Request()
            request.axis = 255
            try:
                await self.stop.call_async(request)
            except Exception as exc:
                self.get_logger().error(f"emergency stop service failed: {exc}")

    async def _move_x(self, goal_handle, x: float, y: float, phase: str) -> tuple[bool, str]:
        if goal_handle.is_cancel_requested:
            return False, "task canceled before move"
        self._feedback(goal_handle, phase, (x, y))
        if not self.gantry.server_is_ready():
            timeout = float(self.config.get("motion", {}).get("action_wait_s", 5.0))
            if not self.gantry.wait_for_server(timeout_sec=timeout):
                return False, "gantry action server unavailable"
        request = MoveGantry.Goal()
        request.relative, request.target = False, float(x)
        request.max_speed = float(self.config.get("motion", {}).get("max_speed_mm_s", 80.0))
        child = await self.gantry.send_goal_async(request)
        if not child.accepted:
            return False, "gantry rejected move goal"
        result_wrap = await child.get_result_async()
        result = result_wrap.result
        if goal_handle.is_cancel_requested:
            await child.cancel_goal_async()
            await self._stop_all()
            return False, "task canceled during move"
        return bool(result.success), str(result.message)

    async def _tool_phase(self, goal_handle, phase: str, point: tuple[float, float], seconds: float) -> tuple[bool, str]:
        self._feedback(goal_handle, phase, point)
        # This boundary is intentionally explicit. Replace only this method when
        # Y/Z/servo hardware is commissioned; X safety behavior stays unchanged.
        await asyncio.sleep(max(0.0, seconds))
        return (False, "task canceled") if goal_handle.is_cancel_requested else (True, "simulated")

    async def execute(self, goal_handle):
        request = goal_handle.request
        result = ExecuteScoop.Result()
        result.source_x = result.source_y = result.target_x = result.target_y = 0.0
        safe = valid_waypoint(self.config.get("field", {}).get("safe_point_mm"))
        moved = False
        try:
            self._feedback(goal_handle, "SENSE", safe or (0.0, 0.0))
            plan = self.vision.plan(request.bean_type)
            source = tuple(plan["world"])
            destination = valid_waypoint(self.config["destination_slots_mm"][str(request.target_slot)])
            if destination is None:
                raise RuntimeError("destination waypoint missing after goal acceptance")
            result.source_x, result.source_y = source
            result.target_x, result.target_y = destination
            self.get_logger().info(
                f"vision source={request.bean_type} box={plan['box']} confidence={plan['confidence']:.2f} "
                f"density={plan['density']:.2f} point=({source[0]:.1f},{source[1]:.1f})")
            ok, message = await self._move_x(goal_handle, source[0], source[1], "MOVE_TO_SOURCE")
            moved = moved or ok
            if not ok:
                raise RuntimeError(message)
            ok, message = await self._tool_phase(goal_handle, "SCOOP_SIM", source,
                                                 float(self.config.get("tool", {}).get("scoop_seconds", 1.2)))
            if not ok:
                raise RuntimeError(message)
            ok, message = await self._move_x(goal_handle, destination[0], destination[1], "MOVE_TO_TARGET")
            moved = moved or ok
            if not ok:
                raise RuntimeError(message)
            ok, message = await self._tool_phase(goal_handle, "DROP_SIM", destination,
                                                 float(self.config.get("tool", {}).get("drop_seconds", 0.8)))
            if not ok:
                raise RuntimeError(message)
            if safe is None:
                raise RuntimeError("field.safe_point_mm is not configured")
            ok, message = await self._move_x(goal_handle, safe[0], safe[1], "RETURN_SAFE")
            if not ok:
                raise RuntimeError(message)
            result.success, result.message = True, "one scoop task completed; tool phases were simulated"
            goal_handle.succeed()
            return result
        except Exception as exc:
            if goal_handle.is_cancel_requested:
                await self._stop_all()
                result.message = f"canceled: {exc}"
                goal_handle.canceled()
            else:
                # Do not invent a vision point.  If X had already moved, make a
                # best-effort safe return; a real gantry error remains an abort.
                if moved and safe is not None:
                    await self._move_x(goal_handle, safe[0], safe[1], "RETURN_SAFE")
                result.message = str(exc)
                goal_handle.abort()
            result.success = False
            return result


def main() -> None:
    rclpy.init()
    node = CompetitionDemo()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()
