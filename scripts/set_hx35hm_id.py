#!/usr/bin/env python3
"""Interactive HX-35HM ID setter through the RRC STM32 controller.

The PC talks to the RRC board protocol (AA 55, 1 Mbps). The STM32 board
then talks to the HX-35HM servo over its USART6 bus-servo interface.
Connect exactly one servo while discovering or changing its ID.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

try:
    import serial
except ImportError:
    print("缺少 pyserial，请先执行: python3 -m pip install pyserial", file=sys.stderr)
    sys.exit(2)


DEFAULT_PORT = "/dev/ros_robot_controller"
BAUDRATE = 1_000_000
RRC_HEADER = b"\xAA\x55"
RRC_BUS_SERVO_FUNCTION = 5
BUS_SERVO_ID_WRITE = 0x10
BUS_SERVO_ID_READ = 0x12
BROADCAST_ID = 0xFE


CRC8_TABLE = [
    0, 94, 188, 226, 97, 63, 221, 131, 194, 156, 126, 32, 163, 253, 31, 65,
    157, 195, 33, 127, 252, 162, 64, 30, 95, 1, 227, 189, 62, 96, 130, 220,
    35, 125, 159, 193, 66, 28, 254, 160, 225, 191, 93, 3, 128, 222, 60, 98,
    190, 224, 2, 92, 223, 129, 99, 61, 124, 34, 192, 158, 29, 67, 161, 255,
    70, 24, 250, 164, 39, 121, 155, 197, 132, 218, 56, 102, 229, 187, 89, 7,
    219, 133, 103, 57, 186, 228, 6, 88, 25, 71, 165, 251, 120, 38, 196, 154,
    101, 59, 217, 135, 4, 90, 184, 230, 167, 249, 27, 69, 198, 152, 122, 36,
    248, 166, 68, 26, 153, 199, 37, 123, 58, 100, 134, 216, 91, 5, 231, 185,
    140, 210, 48, 110, 237, 179, 81, 15, 78, 16, 242, 172, 47, 113, 147, 205,
    17, 79, 173, 243, 112, 46, 204, 146, 211, 141, 111, 49, 178, 236, 14, 80,
    175, 241, 19, 77, 206, 144, 114, 44, 109, 51, 209, 143, 12, 82, 176, 238,
    50, 108, 142, 208, 83, 13, 239, 177, 240, 174, 76, 18, 145, 207, 45, 115,
    202, 148, 118, 40, 171, 245, 23, 73, 8, 86, 180, 234, 105, 55, 213, 139,
    87, 9, 235, 181, 54, 104, 138, 212, 149, 203, 41, 119, 244, 170, 72, 22,
    233, 183, 85, 11, 136, 214, 52, 106, 43, 117, 151, 201, 74, 20, 246, 168,
    116, 42, 200, 150, 21, 75, 169, 247, 182, 232, 10, 84, 215, 137, 107, 53,
]


def crc8(data: bytes) -> int:
    value = 0
    for byte in data:
        value = CRC8_TABLE[value ^ byte]
    return value


def make_rrc_packet(data: bytes) -> bytes:
    body = bytes((RRC_BUS_SERVO_FUNCTION, len(data))) + data
    return RRC_HEADER + body + bytes((crc8(body),))


def read_rrc_packet(port: serial.Serial, timeout: float = 1.0) -> Optional[bytes]:
    deadline = time.monotonic() + timeout
    data = bytearray()
    while time.monotonic() < deadline:
        byte = port.read(1)
        if not byte:
            continue
        data += byte
        if len(data) >= 2 and data[:2] != RRC_HEADER:
            data = data[-1:]
            continue
        if len(data) >= 4:
            length = data[3]
            total = 2 + 1 + 1 + length + 1
            if len(data) >= total:
                packet = bytes(data[:total])
                if crc8(packet[2:-1]) == packet[-1]:
                    return packet
                data.clear()
    return None


def validate_id(value: int, name: str) -> int:
    if not 0 <= value <= 253:
        raise argparse.ArgumentTypeError(f"{name} 必须在 0~253 之间")
    return value


def input_id(prompt: str) -> int:
    while True:
        try:
            return validate_id(int(input(prompt).strip()), "ID")
        except ValueError:
            print("请输入 0~253 之间的整数。")
        except argparse.ArgumentTypeError as exc:
            print(exc)


def board_request_id(port: serial.Serial, servo_id: int) -> Optional[int]:
    port.reset_input_buffer()
    packet = make_rrc_packet(bytes((BUS_SERVO_ID_READ, servo_id)))
    print(f"发送 RRC 读取 ID: {' '.join(f'{b:02X}' for b in packet)}")
    port.write(packet)
    port.flush()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        response = read_rrc_packet(port, timeout=deadline - time.monotonic())
        if response is None:
            break

        function = response[2]
        payload = response[4:-1]
        # 控制板会周期性上传 IMU、按键等消息；只处理总线舵机 ID 回包。
        if function != RRC_BUS_SERVO_FUNCTION:
            print(f"跳过异步 RRC 回报（功能码 0x{function:02X}）。")
            continue
        if len(payload) < 2 or payload[1] != BUS_SERVO_ID_READ:
            sub_command = payload[1] if len(payload) >= 2 else None
            print(f"跳过其它总线舵机回报（子命令 {sub_command}）。")
            continue

        print(f"收到 ID 回报: {' '.join(f'{b:02X}' for b in response)}")
        # Report: queried_id, sub-command, success, args[0].
        if len(payload) < 4:
            print(f"RRC 回报数据长度异常: {len(payload)}")
            return None
        if payload[2] != 0:
            print(f"STM32 读取舵机失败，返回状态码: {payload[2]}（0 表示成功）")
            return None
        return payload[3]

    print("没有收到 STM32 的总线舵机 ID 回报帧。")
    return None


def set_id(port_name: str, old_id: int, new_id: int) -> bool:
    with serial.Serial(port_name, BAUDRATE, timeout=0.05, write_timeout=1.0) as port:
        packet = make_rrc_packet(bytes((BUS_SERVO_ID_WRITE, old_id, new_id)))
        print(f"发送 RRC 改号指令: {' '.join(f'{b:02X}' for b in packet)}")
        port.write(packet)
        port.flush()
        time.sleep(0.2)
        result = board_request_id(port, new_id)
        if result == new_id:
            print(f"改号成功：{old_id} -> {new_id}")
            return True
        print("改号指令已发送，但回读失败。")
        return False


def interactive_mode(port_name: str) -> int:
    print("\n=== HX-35HM 总线舵机 ID 设置 ===")
    print(f"RRC 串口: {port_name}，波特率: {BAUDRATE}")
    print("注意：设置 ID 时总线上只能连接一只舵机。")

    while True:
        choice = input("是否知道当前 ID？[1=知道，2=不知道]: ").strip()
        if choice in ("1", "2"):
            break
        print("请输入 1 或 2。")

    try:
        with serial.Serial(port_name, BAUDRATE, timeout=0.05, write_timeout=1.0) as port:
            if choice == "2":
                print("正在通过 RRC 广播查询当前 ID...")
                old_id = board_request_id(port, BROADCAST_ID)
                if old_id is None:
                    print("查询失败：STM32 没有返回舵机 ID。")
                    print("请检查舵机电源、信号线、共地，以及当前固件是否为 RRC/ROS 控制板固件。")
                    return 1
                print(f"检测到当前舵机 ID: {old_id}")
            else:
                old_id = input_id("请输入当前舵机 ID: ")

            new_id = input_id("请输入新的舵机 ID: ")
            print(f"即将设置: {old_id} -> {new_id}")
            if input("确认发送？输入 YES 才继续: ").strip() != "YES":
                print("已取消。")
                return 0

            packet = make_rrc_packet(bytes((BUS_SERVO_ID_WRITE, old_id, new_id)))
            print(f"发送 RRC 改号指令: {' '.join(f'{b:02X}' for b in packet)}")
            port.write(packet)
            port.flush()
            time.sleep(0.2)
            result = board_request_id(port, new_id)
            if result == new_id:
                print(f"改号成功：{old_id} -> {new_id}")
                return 0
            print("改号指令已发送，但回读失败。")
            return 1
    except serial.SerialException as exc:
        print(f"串口打开或通信失败: {exc}", file=sys.stderr)
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="通过 RRC STM32 控制板设置 HX-35HM 舵机 ID")
    parser.add_argument("old_id", nargs="?", type=lambda v: validate_id(int(v), "old_id"))
    parser.add_argument("new_id", nargs="?", type=lambda v: validate_id(int(v), "new_id"))
    parser.add_argument("-p", "--port", default=DEFAULT_PORT)
    args = parser.parse_args()

    if args.old_id is None and args.new_id is None:
        return interactive_mode(args.port)
    if args.old_id is None or args.new_id is None:
        parser.error("需要同时提供 old_id 和 new_id，或不提供参数使用交互模式")
    try:
        return 0 if set_id(args.port, args.old_id, args.new_id) else 1
    except serial.SerialException as exc:
        print(f"串口打开或通信失败: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
