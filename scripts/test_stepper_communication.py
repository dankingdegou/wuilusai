#!/usr/bin/env python3
"""Only query the STM32; this script never sends a motor-motion command."""

import argparse

from stepper_test_common import StepperSerial, default_port, print_status, require_latest_firmware


def main() -> None:
    parser = argparse.ArgumentParser(description="bjdj STM32 communication-only test (no motor movement)")
    parser.add_argument("--port", default=default_port())
    args = parser.parse_args()
    board = StepperSerial(args.port)
    try:
        print(f"打开串口: {args.port}")
        print(f"STM32 info: {require_latest_firmware(board)}")
        board.clear_statuses()
        board.request_state(0xFF)
        for axis in (0, 1):
            print_status("当前状态", board.wait_axis_status(axis, {0x01, 0x20}, 1.0))
        print("通信测试通过：未发送任何步进脉冲。")
    finally:
        board.close()


if __name__ == "__main__":
    main()
