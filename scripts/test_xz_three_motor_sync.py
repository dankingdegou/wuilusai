#!/usr/bin/env python3
"""Safely test the two X gantry motors and one Z motor at nearly the same time."""

from __future__ import annotations

import argparse
import time

from stepper_test_common import (
    STATUS_ACCEPTED, STATUS_BUSY, STATUS_DONE, STATUS_ERROR, STATUS_STOPPED,
    StepperSerial, ask_int, print_status, require_confirmation, require_latest_firmware,
)


def _state(board: StepperSerial, title: str) -> None:
    board.request_state(0xFF)
    for axis in (0, 1):
        status = board.wait_status(axis, 0, {STATUS_DONE, 0x20}, 1.0)
        print_status(title, status)


def _stop_all(*boards: StepperSerial) -> None:
    for board in boards:
        try:
            board.stop(0xFF)
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="同步测试 X 左右电机 + Z 单电机")
    parser.add_argument("--x-port", default="/dev/x_gantry_controller",
                        help="X 双电机 STM32 固定串口")
    parser.add_argument("--yz-port", default="/dev/yz_controller",
                        help="Y/Z STM32 固定串口")
    parser.add_argument("--z-axis", type=int, default=1, choices=(0, 1),
                        help="Z 所接的协议轴；当前 PA2/PA3 为 axis 1")
    args = parser.parse_args()

    print("=== X 左右 + Z 三电机同步脉冲测试 ===")
    print("X 板：axis 0 和 axis 1 使用同步运动命令。")
    print(f"Y/Z 板：axis {args.z_axis} 作为 Z 轴；当前 PA2/PA3 对应 axis 1。")
    print("首次建议 100 脉冲、200 pps。确认 Z 轴有足够安全行程。")
    x0_steps = ask_int("X 左轨 axis 0 脉冲数", 100, -1_000_000, 1_000_000)
    x1_steps = ask_int("X 右轨 axis 1 脉冲数", 100, -1_000_000, 1_000_000)
    z_steps = ask_int("Z 轴脉冲数", 100, -1_000_000, 1_000_000)
    if 0 in (x0_steps, x1_steps, z_steps):
        raise ValueError("三路脉冲数都不能为 0")
    pps = ask_int("最大速度 pps", 200, 100, 5000)
    accel = ask_int("加速度 pps²", 500, 100, 20000)
    require_confirmation(
        f"即将发送：X axis0={x0_steps}, axis1={x1_steps}; "
        f"Z axis{args.z_axis}={z_steps}; speed={pps} pps, accel={accel} pps²"
    )

    x_board = StepperSerial(args.x_port)
    yz_board = StepperSerial(args.yz_port)
    x_request, z_request = 401, 402
    try:
        print(f"打开 X 板: {args.x_port}")
        print(f"X STM32 info: {require_latest_firmware(x_board)}")
        _state(x_board, "X 当前状态")
        print(f"打开 Y/Z 板: {args.yz_port}")
        print(f"Y/Z STM32 info: {require_latest_firmware(yz_board)}")
        _state(yz_board, "Y/Z 当前状态")

        # The two frames are written back-to-back.  They start independently on
        # their STM32s; host-side skew is only the two USB CDC write durations.
        x_board.move_sync(x0_steps, x1_steps, pps, accel, x_request)
        yz_board.move(args.z_axis, z_steps, pps, accel, z_request)

        x_acks = [x_board.wait_status(axis, x_request,
                                     {STATUS_ACCEPTED, STATUS_BUSY, STATUS_ERROR}, 1.0)
                  for axis in (0, 1)]
        z_ack = yz_board.wait_status(args.z_axis, z_request,
                                     {STATUS_ACCEPTED, STATUS_BUSY, STATUS_ERROR}, 1.0)
        for status in x_acks:
            print_status("X 应答", status)
        print_status("Z 应答", z_ack)
        if any(status.code != STATUS_ACCEPTED for status in x_acks) or z_ack.code != STATUS_ACCEPTED:
            raise RuntimeError("至少一路 STM32 未接受运动命令")

        deadline = time.monotonic() + max(5.0, max(abs(x0_steps), abs(x1_steps), abs(z_steps)) / pps * 3.0 + 2.0)
        x_pending, z_done = {0, 1}, False
        while x_pending or not z_done:
            if time.monotonic() >= deadline:
                raise TimeoutError("运动超时")
            if x_pending:
                try:
                    status = x_board.wait_request_status(x_request, {STATUS_DONE, STATUS_STOPPED, STATUS_ERROR}, 0.15)
                    print_status("X 结果", status)
                    if status.code != STATUS_DONE:
                        raise RuntimeError("X 龙门未正常完成")
                    x_pending.discard(status.axis)
                except TimeoutError:
                    pass
            if not z_done:
                try:
                    status = yz_board.wait_status(args.z_axis, z_request,
                                                   {STATUS_DONE, STATUS_STOPPED, STATUS_ERROR}, 0.15)
                    print_status("Z 结果", status)
                    if status.code != STATUS_DONE:
                        raise RuntimeError("Z 轴未正常完成")
                    z_done = True
                except TimeoutError:
                    pass
        print("三电机测试通过。请目视确认 X 未跑斜、Z 未撞限位。")
    except KeyboardInterrupt:
        print("\n检测到 Ctrl-C，发送两块板全轴停止命令...")
        _stop_all(x_board, yz_board)
    except Exception:
        _stop_all(x_board, yz_board)
        raise
    finally:
        x_board.close()
        yz_board.close()


if __name__ == "__main__":
    main()
