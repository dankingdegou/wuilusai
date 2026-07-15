#!/usr/bin/env python3
"""Interactive, low-speed test of one STEP/DIR channel."""

import argparse

from stepper_test_common import (
    STATUS_ACCEPTED, STATUS_BUSY, STATUS_DONE, STATUS_ERROR, STATUS_STOPPED,
    StepperSerial, ask_int, default_port, print_status, require_confirmation, require_latest_firmware,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="interactive single-stepper test")
    parser.add_argument("--port", default=default_port())
    args = parser.parse_args()
    print("=== 单步进电机测试 ===")
    print(f"串口: {args.port}；请先确保龙门两侧没有机械联接，或只做很小的安全脉冲测试。")
    axis = ask_int("选择轴（0=YL，1=YR）", 0, 0, 1)
    steps = ask_int("脉冲数（正/负决定该驱动器方向）", 100, -1000000, 1000000)
    if steps == 0:
        raise ValueError("脉冲数不能为 0")
    pps = ask_int("速度 pps", 200, 100, 5000)
    accel = ask_int("加速度 pps²", 500, 100, 20000)
    require_confirmation(f"即将测试 axis {axis}: steps={steps}, speed={pps} pps, accel={accel} pps²")
    board = StepperSerial(args.port)
    try:
        print(f"STM32 info: {require_latest_firmware(board)}")
        request_id = 101 + axis
        board.move(axis, steps, pps, accel, request_id)
        ack = board.wait_status(axis, request_id, {STATUS_ACCEPTED, STATUS_BUSY, STATUS_ERROR}, 1.0)
        print_status("应答", ack)
        if ack.code != STATUS_ACCEPTED:
            raise RuntimeError("STM32 未接受运动命令")
        done = board.wait_status(axis, request_id, {STATUS_DONE, STATUS_STOPPED, STATUS_ERROR},
                                 max(3.0, abs(steps) / pps * 3.0 + 1.0))
        print_status("结果", done)
        if done.code != STATUS_DONE:
            raise RuntimeError("运动未正常完成")
    except KeyboardInterrupt:
        print("\n检测到 Ctrl-C，发送当前轴停止命令...")
        board.stop(axis)
    finally:
        board.close()


if __name__ == "__main__":
    main()
