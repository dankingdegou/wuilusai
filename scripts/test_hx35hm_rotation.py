#!/usr/bin/env python3
"""Interactively sweep one HX-35HM servo through the RRC controller range.

The supplied RRC firmware and ROS2 SDK use position 0..1000.  The script
therefore tests that complete controller-supported range in both directions.
"""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial
except ImportError:
    print("缺少 pyserial，请先执行: python3 -m pip install pyserial", file=sys.stderr)
    raise SystemExit(2)

from set_hx35hm_id import BAUDRATE, DEFAULT_PORT, RRC_BUS_SERVO_FUNCTION, make_rrc_packet


MIN_POSITION = 0
MAX_POSITION = 1000


def send_position(port: serial.Serial, servo_id: int, position: int, duration_ms: int) -> None:
    # RRC total-bus-servo command:
    # [0x01, duration_low, duration_high, servo_count, id, position_low, position_high]
    data = bytes((
        0x01,
        duration_ms & 0xFF,
        (duration_ms >> 8) & 0xFF,
        1,
        servo_id,
        position & 0xFF,
        (position >> 8) & 0xFF,
    ))
    packet = make_rrc_packet(data)
    print(f"位置 {position:4d}: {' '.join(f'{byte:02X}' for byte in packet)}")
    port.write(packet)
    port.flush()


def prompt_int(prompt: str, default: int, low: int, high: int) -> int:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("请输入整数。")
            continue
        if low <= value <= high:
            return value
        print(f"请输入 {low}～{high} 之间的数值。")


def main() -> int:
    parser = argparse.ArgumentParser(description="通过 RRC STM32 扫描测试 HX-35HM 角度范围")
    parser.add_argument("-p", "--port", default=DEFAULT_PORT)
    args = parser.parse_args()

    print("\n=== HX-35HM 全行程测试（RRC 位置 0～1000）===")
    print(f"串口: {args.port}，波特率: {BAUDRATE}")
    print("请先确认舵机舵盘、夹爪和线束附近没有会被碰撞的物体。")

    servo_id = prompt_int("舵机 ID", 1, 0, 253)
    duration_ms = prompt_int("每段运动时间（毫秒）", 1200, 100, 10000)
    pause_ms = prompt_int("每段到位后的观察时间（毫秒）", 500, 0, 10000)
    positions = [0, 250, 500, 750, 1000, 750, 500, 250, 0]

    print(f"\n将按以下位置扫描：{positions}")
    if input("确认开始？输入 YES 才会运动: ").strip() != "YES":
        print("已取消。")
        return 0

    try:
        with serial.Serial(args.port, BAUDRATE, timeout=0.05, write_timeout=1.0) as port:
            for index, position in enumerate(positions, start=1):
                print(f"[{index}/{len(positions)}] ", end="")
                send_position(port, servo_id, position, duration_ms)
                time.sleep((duration_ms + pause_ms) / 1000.0)
    except serial.SerialException as exc:
        print(f"串口通信失败: {exc}", file=sys.stderr)
        return 2

    print("测试完成，舵机已回到位置 0。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
