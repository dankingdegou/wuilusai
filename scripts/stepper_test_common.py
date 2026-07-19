"""Shared helpers for safe, direct bjdj STM32 stepper-board tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path


_repo_package_source = (
    Path(__file__).resolve().parents[1]
    / "ros2_ws" / "src" / "wuliusai_stepper_controller"
)
_legacy_package_source = Path.home() / "ros2_ws" / "src" / "wuliusai_stepper_controller"
# Use the repository beside this script whenever it exists.  The old Jetson
# ~/ros2_ws checkout is only a compatibility fallback and must never override
# the deployed repository version.
PACKAGE_SOURCE = _repo_package_source if _repo_package_source.is_dir() else _legacy_package_source
if PACKAGE_SOURCE.is_dir() and str(PACKAGE_SOURCE) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SOURCE))

from wuliusai_stepper_controller.protocol import (  # noqa: E402
    STATUS_ACCEPTED,
    STATUS_BUSY,
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_STOPPED,
    StepperSerial,
)


def default_port() -> str:
    """Use only the STM32 native-USB CDC fixed alias unless explicitly overridden."""
    override = os.environ.get("WULIUSAI_STEPPER_PORT")
    if override:
        return override
    # Do not silently fall back to ttyACM0/ttyUSB0: their numbers can change
    # when a camera or another USB serial device is plugged in.  Reinstall the
    # udev rule if this alias is absent, or deliberately pass --port to test a
    # different transport.
    if os.path.exists("/dev/stepper_controller"):
        return "/dev/stepper_controller"
    return "/dev/stepper_controller"


def require_latest_firmware(board: StepperSerial) -> tuple[int, int, int]:
    info = board.connect()
    if info[0] != 1 or info[2] != 2:
        board.close()
        raise RuntimeError(f"不是预期的双轴步进板协议：{info}")
    if info[1] < 1:
        board.close()
        raise RuntimeError(f"检测到旧固件 {info}；双电机同步测试需要重新烧录 v1.1 或更高版本")
    return info


def ask_int(label: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = input(f"{label} [{default}]: ").strip()
    value = default if not raw else int(raw)
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} 不能小于 {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} 不能大于 {maximum}")
    return value


def require_confirmation(summary: str) -> None:
    print("\n" + summary)
    print("确认机构有安全余量，手和工具已离开运动区域。")
    if input("输入 YES 才发送运动命令: ").strip() != "YES":
        raise RuntimeError("已取消，未发送任何运动命令")


def print_status(prefix: str, status) -> None:
    names = {
        STATUS_ACCEPTED: "ACCEPTED",
        STATUS_DONE: "DONE",
        STATUS_STOPPED: "STOPPED",
        STATUS_ERROR: "ERROR",
        STATUS_BUSY: "BUSY",
    }
    print(f"{prefix}: axis={status.axis}, state={names.get(status.code, hex(status.code))}, "
          f"request={status.request_id}, executed_steps={status.executed_steps}")
