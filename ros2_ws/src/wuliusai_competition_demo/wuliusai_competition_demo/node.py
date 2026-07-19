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

from wuliusai_stepper_msgs.action import ExecuteScoop, MoveAxis, MoveGantry
from wuliusai_stepper_msgs.srv import StopAxis

from .calibration import valid_waypoint, within_field
from .vision_pipeline import SUPPORTED_BEANS, ScoopVision


class CompetitionDemo(Node):
    """One scoop task with a real X gantry and real pulse-relative Z axis."""
    def __init__(self) -> None:
        super().__init__("competition_demo")
        self.declare_parameter("config_file", "")
        raw_path = str(self.get_parameter("config_file").value)
        if not raw_path:
            raise ValueError("set the required config_file parameter")
        self.config_path = Path(raw_path).expanduser().resolve()
        with self.config_path.open(encoding="utf-8") as stream:
            self.config: dict[str, Any] = yaml.safe_load(stream) or {}
        self._validate_motion_config()
        self.vision = ScoopVision(self.config, self.config_path)
        self.group = ReentrantCallbackGroup()
        motion = self.config.get("motion", {})
        self.gantry = ActionClient(self, MoveGantry, str(motion.get("gantry_action", "/stepper_controller/move_gantry")),
                                   callback_group=self.group)
        self.z_axis = ActionClient(self, MoveAxis, str(motion.get("z_action", "/yz_controller/move_axis")),
                                   callback_group=self.group)
        self.x_stop = self.create_client(StopAxis, str(motion.get("stop_service", "/stepper_controller/stop")),
                                         callback_group=self.group)
        self.z_stop = self.create_client(StopAxis, str(motion.get("z_stop_service", "/yz_controller/stop")),
                                         callback_group=self.group)
        self.server = ActionServer(self, ExecuteScoop, "/competition/execute_scoop", self.execute,
                                   goal_callback=self.goal_callback, cancel_callback=self.cancel_callback,
                                   callback_group=self.group)
        tool = self.config.get("tool", {})
        self.get_logger().info(
            f"competition demo ready: X real; Z axis={int(tool.get('z_axis', 1))} real; Y/bucket simulated")

    def _validate_motion_config(self) -> None:
        tool = self.config.get("tool", {})
        required = ("z_simulated", "z_axis", "z_down_direction", "z_travel_pulses", "z_speed_pps")
        missing = [name for name in required if name not in tool]
        if missing:
            raise ValueError(f"real Z configuration is incomplete; missing tool fields: {', '.join(missing)}")
        if bool(tool.get("z_simulated", False)):
            raise ValueError("tool.z_simulated must be false: this demo uses the real Y/Z STM32 Z axis")
        z_axis = int(tool.get("z_axis", 1))
        if z_axis not in (0, 1):
            raise ValueError("tool.z_axis must be 0 or 1; PA2/PA3 is axis 1")
        direction = int(tool.get("z_down_direction", 1))
        if direction not in (-1, 1):
            raise ValueError("tool.z_down_direction must be 1 or -1")
        pulses = float(tool.get("z_travel_pulses", 1600.0))
        speed = float(tool.get("z_speed_pps", 500.0))
        if not 0.0 < pulses <= 1_000_000.0:
            raise ValueError("tool.z_travel_pulses must be in (0, 1000000]")
        if not 0.0 < speed <= 5000.0:
            raise ValueError("tool.z_speed_pps must be in (0, 5000]")

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
    def _feedback(goal_handle, phase: str, point: tuple[float, float], z: float = 0.0) -> None:
        feedback = ExecuteScoop.Feedback()
        feedback.phase, feedback.x, feedback.y, feedback.z = phase, point[0], point[1], z
        goal_handle.publish_feedback(feedback)

    async def _stop_all(self) -> None:
        for name, client in (("X", self.x_stop), ("Z", self.z_stop)):
            if not client.service_is_ready():
                client.wait_for_service(timeout_sec=0.5)
            if not client.service_is_ready():
                continue
            request = StopAxis.Request()
            request.axis = 255
            try:
                await client.call_async(request)
            except Exception as exc:
                self.get_logger().error(f"{name} emergency stop service failed: {exc}")

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

    async def _move_z(self, goal_handle, delta_pulses: float, point: tuple[float, float],
                      phase: str, z_position: float, ignore_cancel: bool = False) -> tuple[bool, str]:
        if goal_handle.is_cancel_requested and not ignore_cancel:
            return False, "task canceled before Z move"
        self._feedback(goal_handle, phase, point, z_position + delta_pulses)
        if not self.z_axis.server_is_ready():
            timeout = float(self.config.get("motion", {}).get("action_wait_s", 5.0))
            if not self.z_axis.wait_for_server(timeout_sec=timeout):
                return False, "Z action server unavailable"
        tool = self.config.get("tool", {})
        request = MoveAxis.Goal()
        request.axis = int(tool.get("z_axis", 1))
        request.relative = True
        request.target = float(delta_pulses)
        request.max_speed = float(tool.get("z_speed_pps", 500.0))
        child = await self.z_axis.send_goal_async(request)
        if not child.accepted:
            return False, "Z controller rejected move goal"
        result = (await child.get_result_async()).result
        if goal_handle.is_cancel_requested and not ignore_cancel:
            await self._stop_all()
            return False, "task canceled during Z move"
        return bool(result.success), str(result.message)

    async def _tool_phase(self, goal_handle, phase: str, point: tuple[float, float],
                          z_position: float, seconds: float) -> tuple[bool, str]:
        self._feedback(goal_handle, phase, point, z_position)
        # Bucket actuation is still simulated. Y is also not commissioned yet.
        await asyncio.sleep(max(0.0, seconds))
        return (False, "task canceled") if goal_handle.is_cancel_requested else (True, "simulated")

    async def execute(self, goal_handle):
        request = goal_handle.request
        result = ExecuteScoop.Result()
        result.source_x = result.source_y = result.target_x = result.target_y = 0.0
        safe = valid_waypoint(self.config.get("field", {}).get("safe_point_mm"))
        moved = False
        z_position = 0.0
        z_lowered = False
        z_recovery_allowed = False
        tool = self.config.get("tool", {})
        z_delta = float(tool.get("z_down_direction", 1)) * abs(float(tool.get("z_travel_pulses", 1600.0)))
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
            ok, message = await self._move_z(goal_handle, z_delta, source, "Z_DESCEND_SOURCE", z_position)
            if not ok:
                raise RuntimeError(message)
            z_position += z_delta
            z_lowered = True
            z_recovery_allowed = True
            ok, message = await self._tool_phase(goal_handle, "SCOOP_SIM", source, z_position,
                                                 float(self.config.get("tool", {}).get("scoop_seconds", 1.2)))
            if not ok:
                raise RuntimeError(message)
            z_recovery_allowed = False
            ok, message = await self._move_z(goal_handle, -z_delta, source, "Z_ASCEND_SOURCE", z_position)
            if not ok:
                raise RuntimeError(message)
            z_position -= z_delta
            z_lowered = False
            ok, message = await self._move_x(goal_handle, destination[0], destination[1], "MOVE_TO_TARGET")
            moved = moved or ok
            if not ok:
                raise RuntimeError(message)
            ok, message = await self._move_z(goal_handle, z_delta, destination, "Z_DESCEND_TARGET", z_position)
            if not ok:
                raise RuntimeError(message)
            z_position += z_delta
            z_lowered = True
            z_recovery_allowed = True
            ok, message = await self._tool_phase(goal_handle, "DROP_SIM", destination, z_position,
                                                 float(self.config.get("tool", {}).get("drop_seconds", 0.8)))
            if not ok:
                raise RuntimeError(message)
            z_recovery_allowed = False
            ok, message = await self._move_z(goal_handle, -z_delta, destination, "Z_ASCEND_TARGET", z_position)
            if not ok:
                raise RuntimeError(message)
            z_position -= z_delta
            z_lowered = False
            if safe is None:
                raise RuntimeError("field.safe_point_mm is not configured")
            ok, message = await self._move_x(goal_handle, safe[0], safe[1], "RETURN_SAFE")
            if not ok:
                raise RuntimeError(message)
            result.success, result.message = True, "one scoop task completed; X/Z real, Y/bucket simulated"
            goal_handle.succeed()
            return result
        except Exception as exc:
            # If a later simulated/tool stage failed while Z is known to be at
            # the bottom, first attempt the exact inverse pulse move.  If that
            # cannot be confirmed, stop both controllers and leave X in place.
            z_recovered = True
            if z_lowered and z_recovery_allowed:
                recovery_point = safe or (0.0, 0.0)
                z_recovered, recovery_message = await self._move_z(
                    goal_handle, -z_delta, recovery_point, "Z_RECOVERY_ASCEND", z_position, ignore_cancel=True)
                if z_recovered:
                    z_position -= z_delta
                    z_lowered = False
                else:
                    self.get_logger().error(f"Z recovery failed: {recovery_message}")
                    await self._stop_all()
            elif z_lowered:
                z_recovered = False
                self.get_logger().error("Z position is uncertain after a failed Z move; stopping both controllers")
                await self._stop_all()
            if goal_handle.is_cancel_requested:
                await self._stop_all()
                result.message = f"canceled: {exc}"
                goal_handle.canceled()
            else:
                # Do not invent a vision point.  If X had already moved, make a
                # best-effort safe return; a real gantry error remains an abort.
                if z_recovered and moved and safe is not None:
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
