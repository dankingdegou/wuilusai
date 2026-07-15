from __future__ import annotations

import threading
import time

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from wuliusai_stepper_msgs.action import MoveAxis, MoveGantry
from wuliusai_stepper_msgs.msg import StepperState
from wuliusai_stepper_msgs.srv import SetAxisZero, SetGantryZero, StopAxis

from .protocol import (
    ALL_AXES, STATUS_ACCEPTED, STATUS_BUSY, STATUS_DONE, STATUS_ERROR,
    STATUS_STOPPED, StepperSerial,
)


class StepperController(Node):
    def __init__(self) -> None:
        super().__init__("stepper_controller")
        self._group = ReentrantCallbackGroup()
        self.declare_parameter("port", "/dev/stepper_controller")
        self.declare_parameter("baudrate", 115200)
        self.declare_parameter("state_rate_hz", 10.0)
        self._axes = [self._load_axis(index) for index in range(2)]
        self.declare_parameter("gantry.enabled", True)
        self.declare_parameter("gantry.allow_individual_axis", False)
        self.declare_parameter("gantry.max_theoretical_skew", 0.5)
        self._gantry_enabled = self.get_parameter("gantry.enabled").value
        self._allow_individual_axis = self.get_parameter("gantry.allow_individual_axis").value
        self._max_theoretical_skew = self.get_parameter("gantry.max_theoretical_skew").value
        if self._gantry_enabled and self._axes[0]["unit"] != self._axes[1]["unit"]:
            raise ValueError("gantry rails must use the same physical unit")
        self._axis_locks = [threading.Lock(), threading.Lock()]
        self._gantry_lock = threading.Lock()
        self._serial_lock = threading.Lock()
        self._serial: StepperSerial | None = None
        self._was_connected = False
        self._next_request_id = 1
        self._last_error = "not connected"

        self._state_pub = self.create_publisher(StepperState, "~/state", 10)
        self._set_zero = self.create_service(SetAxisZero, "~/set_zero", self._set_zero_callback,
                                             callback_group=self._group)
        self._set_gantry_zero = self.create_service(SetGantryZero, "~/set_gantry_zero", self._set_gantry_zero_callback,
                                                    callback_group=self._group)
        self._stop = self.create_service(StopAxis, "~/stop", self._stop_callback, callback_group=self._group)
        self._action = ActionServer(self, MoveAxis, "~/move_axis", execute_callback=self._execute_move,
                                    goal_callback=self._goal_callback, cancel_callback=self._cancel_callback,
                                    callback_group=self._group)
        self._gantry_action = ActionServer(self, MoveGantry, "~/move_gantry", execute_callback=self._execute_gantry_move,
                                           goal_callback=self._gantry_goal_callback, cancel_callback=self._cancel_callback,
                                           callback_group=self._group)
        period = 1.0 / max(self.get_parameter("state_rate_hz").value, 1.0)
        self.create_timer(period, self._publish_state, callback_group=self._group)
        self.create_timer(1.0, self._reconnect, callback_group=self._group)

    def _load_axis(self, index: int) -> dict:
        prefix = f"axis_{index}."
        defaults = {
            "name": f"axis_{index}", "unit": "mm", "pulses_per_unit": 100.0,
            "direction": 1, "min_position": -1.0e9, "max_position": 1.0e9,
            "max_speed": 300.0, "acceleration": 500.0,
        }
        values = {}
        for key, default in defaults.items():
            self.declare_parameter(prefix + key, default)
            values[key] = self.get_parameter(prefix + key).value
        values.update(position=0.0, steps=0, referenced=False, state=STATUS_DONE, current_speed=0.0)
        if values["pulses_per_unit"] <= 0 or values["direction"] not in (-1, 1):
            raise ValueError(f"axis_{index} needs positive pulses_per_unit and direction +/-1")
        return values

    def _ensure_connected(self) -> StepperSerial:
        with self._serial_lock:
            if self._serial and self._serial.connected:
                return self._serial
            if self._serial:
                self._serial.close()
            transport = StepperSerial(self.get_parameter("port").value, self.get_parameter("baudrate").value)
            transport.on_status = self._on_status
            version = transport.connect()
            if version[0] != 1 or version[2] != 2:
                transport.close()
                raise RuntimeError(f"unexpected STM32 protocol {version}")
            self._serial = transport
            for axis in self._axes:
                axis["referenced"] = False
                axis["state"] = STATUS_DONE
            self._last_error = "manual zero required after board connection"
            self.get_logger().info(f"connected to stepper board: protocol {version[0]}.{version[1]}, {version[2]} axes")
            return transport

    def _reconnect(self) -> None:
        if self._serial and self._serial.connected:
            return
        try:
            self._ensure_connected()
        except Exception as exc:
            self._last_error = str(exc)

    def _on_status(self, status) -> None:
        if status.axis >= len(self._axes):
            return
        axis = self._axes[status.axis]
        axis["state"] = status.code
        if status.code in (STATUS_DONE, STATUS_STOPPED, STATUS_ERROR, STATUS_BUSY):
            axis["current_speed"] = 0.0

    def _goal_callback(self, goal: MoveAxis.Goal) -> GoalResponse:
        if goal.axis >= len(self._axes) or goal.max_speed < 0.0 or (self._gantry_enabled and not self._allow_individual_axis):
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _gantry_goal_callback(self, goal: MoveGantry.Goal) -> GoalResponse:
        if not self._gantry_enabled or goal.max_speed < 0.0:
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _cancel_callback(self, _goal_handle) -> CancelResponse:
        return CancelResponse.ACCEPT

    def _request_id(self) -> int:
        value = self._next_request_id
        self._next_request_id = 1 if value >= 0xFFFF else value + 1
        return value

    def _execute_move(self, goal_handle):
        goal = goal_handle.request
        axis_id = goal.axis
        result = MoveAxis.Result()
        axis = self._axes[axis_id]
        if not self._axis_locks[axis_id].acquire(blocking=False):
            result.success = False; result.message = "axis is already executing a move"; result.final_position = axis["position"]
            goal_handle.abort(); return result
        try:
            if not goal.relative and not axis["referenced"]:
                result.success = False; result.message = "absolute move requires set_zero after power-up"; result.final_position = axis["position"]
                goal_handle.abort(); return result
            target = axis["position"] + goal.target if goal.relative else goal.target
            if axis["referenced"] and not (axis["min_position"] <= target <= axis["max_position"]):
                result.success = False; result.message = "target exceeds configured soft limits"; result.final_position = axis["position"]
                goal_handle.abort(); return result
            delta = target - axis["position"]
            steps = round(delta * axis["pulses_per_unit"] * axis["direction"])
            if steps == 0:
                result.success = True; result.message = "already at target"; result.final_position = axis["position"]
                goal_handle.succeed(); return result
            speed = goal.max_speed if goal.max_speed > 0.0 else axis["max_speed"]
            pps = max(100, min(5000, round(speed * axis["pulses_per_unit"])))
            acceleration = max(100, min(20000, round(axis["acceleration"] * axis["pulses_per_unit"])))
            request_id = self._request_id()
            start_position = axis["position"]
            raw_direction = 1 if steps > 0 else -1
            transport = self._ensure_connected()
            transport.move(axis_id, steps, pps, acceleration, request_id)
            accepted = transport.wait_status(axis_id, request_id, {STATUS_ACCEPTED, STATUS_BUSY, STATUS_ERROR}, 1.0)
            if accepted.code != STATUS_ACCEPTED:
                result.success = False; result.message = "STM32 rejected move"; result.final_position = axis["position"]
                goal_handle.abort(); return result
            axis["state"] = STATUS_ACCEPTED; axis["current_speed"] = speed
            timeout = max(5.0, abs(steps) / max(pps, 1) * 3.0 + 2.0)
            deadline = time.monotonic() + timeout
            while True:
                if goal_handle.is_cancel_requested:
                    transport.stop(axis_id)
                    try:
                        status = transport.wait_status(axis_id, request_id, {STATUS_STOPPED}, 1.0)
                        moved = raw_direction * status.executed_steps / (axis["pulses_per_unit"] * axis["direction"])
                        axis["position"] = start_position + moved
                        axis["steps"] += raw_direction * status.executed_steps
                    except TimeoutError:
                        self._last_error = "cancel sent but STM32 stop confirmation timed out"
                    goal_handle.canceled()
                    result.success = False; result.message = "move canceled"; result.final_position = axis["position"]
                    return result
                try:
                    status = transport.wait_status(axis_id, request_id, {STATUS_DONE, STATUS_STOPPED, STATUS_ERROR}, 0.15)
                    break
                except TimeoutError:
                    feedback = MoveAxis.Feedback()
                    feedback.current_position = axis["position"]
                    feedback.current_speed = axis["current_speed"]
                    feedback.state = "moving"
                    goal_handle.publish_feedback(feedback)
                    if time.monotonic() >= deadline:
                        transport.stop(axis_id)
                        raise TimeoutError("move timed out; stop command sent")
            if status.code == STATUS_DONE:
                axis["position"] = target
                axis["steps"] += steps
                result.success = True; result.message = "completed"; result.final_position = target
                goal_handle.succeed()
            else:
                moved = raw_direction * status.executed_steps / (axis["pulses_per_unit"] * axis["direction"])
                axis["position"] = start_position + moved
                axis["steps"] += raw_direction * status.executed_steps
                result.success = False; result.message = "stopped" if status.code == STATUS_STOPPED else "STM32 reported error"
                result.final_position = axis["position"]
                goal_handle.abort()
            return result
        except Exception as exc:
            self._last_error = str(exc)
            result.success = False; result.message = str(exc); result.final_position = axis["position"]
            goal_handle.abort(); return result
        finally:
            axis["current_speed"] = 0.0
            self._axis_locks[axis_id].release()

    def _invalidate_gantry_reference(self, reason: str) -> None:
        for axis in self._axes:
            axis["referenced"] = False
            axis["current_speed"] = 0.0
        self._last_error = reason

    def _execute_gantry_move(self, goal_handle):
        goal = goal_handle.request
        result = MoveGantry.Result()
        if not self._gantry_lock.acquire(blocking=False):
            result.success = False; result.message = "gantry is already executing a move"; result.final_position = 0.0
            goal_handle.abort(); return result
        locked = []
        try:
            for lock in self._axis_locks:
                if not lock.acquire(blocking=False):
                    result.success = False; result.message = "one gantry rail is busy"; result.final_position = 0.0
                    goal_handle.abort(); return result
                locked.append(lock)
            left, right = self._axes
            skew = abs(left["position"] - right["position"])
            if skew > self._max_theoretical_skew:
                result.success = False; result.message = "theoretical rail skew exceeds configured limit"; result.final_position = 0.0
                goal_handle.abort(); return result
            if not goal.relative and (not left["referenced"] or not right["referenced"]):
                result.success = False; result.message = "absolute gantry move requires set_gantry_zero after power-up"; result.final_position = 0.0
                goal_handle.abort(); return result
            current = (left["position"] + right["position"]) / 2.0
            target = current + goal.target if goal.relative else goal.target
            if not all(axis["min_position"] <= target <= axis["max_position"] for axis in self._axes):
                result.success = False; result.message = "target exceeds configured gantry rail soft limits"; result.final_position = current
                goal_handle.abort(); return result
            steps = [round((target - axis["position"]) * axis["pulses_per_unit"] * axis["direction"])
                     for axis in self._axes]
            if steps[0] == 0 or steps[1] == 0:
                result.success = False; result.message = "target is too small for one rail's configured resolution"; result.final_position = current
                goal_handle.abort(); return result
            speed = goal.max_speed if goal.max_speed > 0.0 else min(left["max_speed"], right["max_speed"])
            pps = max(100, min(5000, round(speed * max(left["pulses_per_unit"], right["pulses_per_unit"]))))
            acceleration = max(100, min(20000, round(min(left["acceleration"], right["acceleration"]) *
                                                       max(left["pulses_per_unit"], right["pulses_per_unit"]))))
            request_id = self._request_id()
            transport = self._ensure_connected()
            transport.move_sync(steps[0], steps[1], pps, acceleration, request_id)
            for axis_id in (0, 1):
                accepted = transport.wait_status(axis_id, request_id, {STATUS_ACCEPTED, STATUS_BUSY, STATUS_ERROR}, 1.0)
                if accepted.code != STATUS_ACCEPTED:
                    transport.stop(ALL_AXES)
                    raise RuntimeError("STM32 rejected synchronized gantry move")
            for axis in self._axes:
                axis["state"] = STATUS_ACCEPTED; axis["current_speed"] = speed
            timeout = max(5.0, max(abs(steps[0]), abs(steps[1])) / max(pps, 1) * 3.0 + 2.0)
            pending = {0, 1}
            deadline = time.monotonic() + timeout
            while pending:
                if goal_handle.is_cancel_requested:
                    transport.stop(ALL_AXES)
                    self._invalidate_gantry_reference("gantry move canceled; manual zero required")
                    goal_handle.canceled()
                    result.success = False; result.message = "gantry move canceled"; result.final_position = current
                    return result
                try:
                    status = transport.wait_request_status(request_id, {STATUS_DONE, STATUS_STOPPED, STATUS_ERROR}, 0.15)
                    if status.code != STATUS_DONE:
                        transport.stop(ALL_AXES)
                        self._invalidate_gantry_reference("gantry interrupted; manual zero required")
                        result.success = False; result.message = "gantry stopped or STM32 reported an error"; result.final_position = current
                        goal_handle.abort(); return result
                    pending.discard(status.axis)
                except TimeoutError:
                    feedback = MoveGantry.Feedback()
                    feedback.left_position = left["position"]
                    feedback.right_position = right["position"]
                    feedback.current_speed = speed
                    feedback.state = "moving"
                    goal_handle.publish_feedback(feedback)
                    if time.monotonic() >= deadline:
                        transport.stop(ALL_AXES)
                        self._invalidate_gantry_reference("gantry timeout; manual zero required")
                        raise TimeoutError("synchronized gantry move timed out; stop command sent")
            for axis, raw_steps in zip(self._axes, steps):
                axis["position"] = target
                axis["steps"] += raw_steps
                axis["current_speed"] = 0.0
            result.success = True; result.message = "gantry move completed"; result.final_position = target
            goal_handle.succeed()
            return result
        except Exception as exc:
            self._last_error = str(exc)
            result.success = False; result.message = str(exc)
            result.final_position = (self._axes[0]["position"] + self._axes[1]["position"]) / 2.0
            goal_handle.abort(); return result
        finally:
            for lock in reversed(locked):
                lock.release()
            self._gantry_lock.release()

    def _set_gantry_zero_callback(self, request, response):
        if not self._gantry_lock.acquire(blocking=False):
            response.success = False; response.message = "gantry is moving"; return response
        locked = []
        try:
            for lock in self._axis_locks:
                if not lock.acquire(blocking=False):
                    response.success = False; response.message = "one gantry rail is moving"; return response
                locked.append(lock)
            for axis in self._axes:
                axis["position"] = request.position
                axis["steps"] = 0
                axis["referenced"] = True
            self._last_error = ""
            response.success = True; response.message = "both gantry rails set to manual zero"
            return response
        finally:
            for lock in reversed(locked):
                lock.release()
            self._gantry_lock.release()

    def _set_zero_callback(self, request, response):
        if self._gantry_enabled and not self._allow_individual_axis:
            response.success = False; response.message = "use set_gantry_zero for mechanically coupled rails"; return response
        if request.axis >= len(self._axes):
            response.success = False; response.message = "invalid axis"; return response
        if not self._axis_locks[request.axis].acquire(blocking=False):
            response.success = False; response.message = "cannot set zero while axis is moving"; return response
        axis = self._axes[request.axis]
        try:
            axis["position"] = request.position
            axis["steps"] = 0
            axis["referenced"] = True
            self._last_error = ""
            response.success = True; response.message = "manual zero set"
        finally:
            self._axis_locks[request.axis].release()
        return response

    def _stop_callback(self, request, response):
        if request.axis != ALL_AXES and request.axis >= len(self._axes):
            response.success = False; response.message = "invalid axis"; return response
        try:
            self._ensure_connected().stop(request.axis)
            response.success = True; response.message = "stop command sent"
        except Exception as exc:
            self._last_error = str(exc)
            response.success = False; response.message = str(exc)
        return response

    def _publish_state(self) -> None:
        message = StepperState()
        message.name = [axis["name"] for axis in self._axes]
        message.unit = [axis["unit"] for axis in self._axes]
        message.position = [axis["position"] for axis in self._axes]
        message.steps = [axis["steps"] for axis in self._axes]
        message.state = [axis["state"] for axis in self._axes]
        message.referenced = [axis["referenced"] for axis in self._axes]
        message.last_error = self._last_error
        self._state_pub.publish(message)

    def destroy_node(self) -> bool:
        if self._serial:
            self._serial.close()
        return super().destroy_node()


def main() -> None:
    rclpy.init()
    node = StepperController()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()
