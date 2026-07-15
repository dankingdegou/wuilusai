#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# 使用 STM32 控制板修改 HX-35HM 总线舵机 ID 的示例
#
# 依赖：
# - 已在 ROS2 工作区中添加 ros_robot_controller-ros2
# - 从该工作区环境中运行本脚本，可以直接导入 Board 类

import time

from ros_robot_controller.ros_robot_controller_sdk import Board


def change_servo_id(
    device: str = "/dev/so101_follower",
    old_id: int = 254,
    new_id: int = 1,
) -> None:
    """
    修改总线舵机 ID 并回读验证。

    参数说明：
    - device: 控制板在 Linux 下的串口设备名，比如 "/dev/so101_follower"
    - old_id: 当前舵机 ID。254 通常表示“广播”，用于不确定当前 ID 时。
    - new_id: 想要设置成的新 ID（0~253，且总线上必须唯一）。
    """
    print(f"打开串口 {device} ...")
    board = Board(device=device)
    board.enable_reception()
    print("串口已打开，开始修改 ID")

    # 1. 设置新 ID
    print(f"将舵机 ID 从 {old_id} 修改为 {new_id} ...")
    board.bus_servo_set_id(old_id, new_id)
    # 数据在总线上传播需要一点时间
    time.sleep(0.1)

    # 2. 回读新 ID 验证（用广播 ID 254 读取）
    print("回读舵机 ID 以确认修改结果 ...")
    res = board.bus_servo_read_id(254)  # 广播读取当前接入舵机的 ID
    if res is None:
        print("读取失败：没有收到舵机回应，请检查接线、电源和单舵机接入。")
        return

    # bus_servo_read_id 返回形如 (id, success, ...) 的信息，这里取第一个元素作为 ID
    present_id = res[0]
    print(f"读取到当前舵机 ID = {present_id}")

    if present_id == new_id:
        print(f"ID 修改成功：{old_id} -> {new_id}")
    else:
        print(f"ID 修改结果异常：期望 {new_id}，实际 {present_id}，请检查。")


if __name__ == "__main__":
    # 示例：把当前 ID 未知（用广播 254）的舵机改成 ID=1
    # 使用前请：
    # 1）只接一个舵机到总线
    # 2）确保已安装 udev 规则并出现 /dev/so101_follower
    change_servo_id(
        device="/dev/so101_follower",  # 由 udev 规则固定的设备名
        old_id=254,                          # 当前 ID，如果完全不确定就用 254 广播
        new_id=6,                            # 想要设定的新 ID
    )
