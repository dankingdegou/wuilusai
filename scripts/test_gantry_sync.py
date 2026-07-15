#!/usr/bin/env python3
"""Interactive direct test of the STM32 synchronized gantry command."""

import argparse
import time

from stepper_test_common import (
    STATUS_ACCEPTED, STATUS_BUSY, STATUS_DONE, STATUS_ERROR, STATUS_STOPPED,
    StepperSerial, ask_int, default_port, print_status, require_confirmation, require_latest_firmware,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="interactive synchronized dual-stepper gantry test")
    parser.add_argument("--port", default=default_port())
    args = parser.parse_args()
    print("=== 双电机龙门同步测试 ===")
    print("初次测试建议每侧仅 100 脉冲。两侧要让龙门向同一物理方向移动，原始脉冲符号可能相同也可能相反，取决于驱动器接线。")
    left_steps = ask_int("axis 0（左轨）脉冲数", 100, -1000000, 1000000)
    right_steps = ask_int("axis 1（右轨）脉冲数", 100, -1000000, 1000000)
    if left_steps == 0 or right_steps == 0:
        raise ValueError("同步测试的两侧脉冲数都不能为 0")
    pps = ask_int("较快一侧的最大速度 pps", 200, 100, 5000)
    accel = ask_int("较快一侧的加速度 pps²", 500, 100, 20000)
    require_confirmation(f"即将同步运动: axis0={left_steps} steps, axis1={right_steps} steps, "
                         f"max_speed={pps} pps, accel={accel} pps²")
    board = StepperSerial(args.port)
    try:
        print(f"STM32 info: {require_latest_firmware(board)}")
        request_id = 201
        board.move_sync(left_steps, right_steps, pps, accel, request_id)
        for axis in (0, 1):
            ack = board.wait_status(axis, request_id, {STATUS_ACCEPTED, STATUS_BUSY, STATUS_ERROR}, 1.0)
            print_status("应答", ack)
            if ack.code != STATUS_ACCEPTED:
                raise RuntimeError("STM32 未接受同步运动命令")
        pending = {0, 1}
        timeout = max(3.0, max(abs(left_steps), abs(right_steps)) / pps * 3.0 + 1.0)
        deadline = time.monotonic() + timeout
        while pending:
            status = board.wait_request_status(request_id, {STATUS_DONE, STATUS_STOPPED, STATUS_ERROR},
                                               max(0.1, deadline - time.monotonic()))
            print_status("结果", status)
            if status.code != STATUS_DONE:
                board.stop(0xFF)
                raise RuntimeError("任一侧未完成，已发送全部停止命令")
            pending.discard(status.axis)
        print("双电机同步测试通过。请目视确认龙门没有跑斜或卡滞。")
    except KeyboardInterrupt:
        print("\n检测到 Ctrl-C，发送全部停止命令...")
        board.stop(0xFF)
    finally:
        board.close()


if __name__ == "__main__":
    main()
