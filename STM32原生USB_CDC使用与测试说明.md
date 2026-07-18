# STM32 原生 USB CDC 使用与测试说明

适用对象：比赛用双轴步进控制 STM32。该板已烧录支持 **STM32 原生 USB CDC 虚拟串口** 的固件，不再需要外接 CH340 或 USB 转 TTL。

## 1. 当前连接方式

使用一根可传数据的 USB-A → Type-C 线：

```text
Jetson USB-A ── USB 数据线 ── STM32 Type-C
```

这根线同时负责供电和通信。连接后，Jetson 内核会创建临时设备，例如 `/dev/ttyACM0`；程序不应直接使用这个临时名称。

当前已建立固定别名：

```text
/dev/stepper_controller -> /dev/ttyACM0
```

该别名由 STM32 固件的 USB 序列号绑定，因此即使重插、设备号从 `ttyACM0` 变为 `ttyACM1`，程序仍使用 `/dev/stepper_controller`。

## 2. 检查串口是否识别

```bash
ls -l /dev/ttyACM* /dev/stepper_controller
udevadm info -q property -n /dev/ttyACM0 | \
  egrep '^(ID_VENDOR_ID|ID_MODEL_ID|ID_SERIAL|DEVLINKS)='
```

本控制板预期属性：

```text
ID_VENDOR_ID=0483
ID_MODEL_ID=5740
ID_SERIAL=Logistics_Team_Stepper_Controller_USB_CDC_5CD86F583630
```

若 `/dev/stepper_controller` 不存在，重新加载规则：

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=tty
ls -l /dev/stepper_controller
```

规则文件是 `/etc/udev/rules.d/99-wuliusai-stepper.rules`。用户必须属于 `dialout` 组：

```bash
id -nG
```

输出中应包含 `dialout`。若没有，执行 `sudo usermod -aG dialout $USER` 后重新登录。

## 3. 更新与构建 ROS2 工作区

```bash
cd ~/wuilusai
git pull --ff-only

cd ros2_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select \
  wuliusai_stepper_msgs \
  wuliusai_stepper_controller \
  wuliusai_competition_demo \
  --symlink-install
```

日常使用统一加载环境：

```bash
cd ~/wuilusai
source scripts/jetson_env.sh
```

该脚本会优先加载 `~/wuilusai/ros2_ws/install`，并规避 Jetson 用户目录中的 NumPy 2.x 与系统 OpenCV 的冲突。

## 4. 零风险通信测试

该测试只读取固件信息和状态，**不会发送步进脉冲**：

```bash
cd ~/wuilusai
source scripts/jetson_env.sh
python3 scripts/test_stepper_communication.py
```

预期关键输出：

```text
打开串口: /dev/stepper_controller
STM32 info: (1, 1, 2)
当前状态: axis=0, state=DONE
当前状态: axis=1, state=DONE
通信测试通过：未发送任何步进脉冲。
```

若出现 `Permission denied`，检查 `dialout` 组；若出现 `TimeoutError`，检查 Type-C 数据线、控制板供电和是否烧录了当前协议固件。

## 5. 单电机测试

仅在机械结构有安全余量、手和工具离开运动区域时执行：

```bash
cd ~/wuilusai
source scripts/jetson_env.sh
python3 scripts/test_single_stepper.py
```

脚本会要求输入轴号、脉冲数、速度和 `YES` 确认。脉冲为负数时，电机应反向旋转；首次建议使用很小的脉冲数，例如 `100`。

## 6. 双电机龙门同步测试

```bash
cd ~/wuilusai
source scripts/jetson_env.sh
python3 scripts/test_gantry_sync.py
```

建议首次参数：

```text
axis 0 steps: 100
axis 1 steps: 100
max speed: 200 pps
acceleration: 500 pps²
```

两侧物理方向必须一致。若两台电机同号脉冲时龙门一侧前进、一侧后退，则将其中一侧脉冲改为相反号；例如 `axis0=100`、`axis1=-100`。测试通过仅表示协议执行完成，仍须目视确认龙门未跑斜、卡滞或撞限位。

## 7. 启动 ROS2 X 龙门控制器

终端 1：

```bash
cd ~/wuilusai
./scripts/jetson_start_stepper.sh
```

上电或控制器重新连接后，绝对移动前必须完成回零或人工设零。当前 X 原点开关尚未接入时，可在机械安全位置执行人工设零：

```bash
source ~/wuilusai/scripts/jetson_env.sh
ros2 service call /stepper_controller/set_gantry_zero \
  wuliusai_stepper_msgs/srv/SetGantryZero "{position: 0.0}"
```

只有确认该物理位置确实对应场地 X=`0 mm` 时才能执行此命令。

## 8. 启动比赛单铲 Demo

Demo 当前状态：X 双电机龙门为真实执行器；Y、Z、铲斗开合仍为模拟阶段。不要将模拟阶段误认为实际抓取已接线。

先准备一份运行配置，例如 `~/wuilusai_runtime/competition_demo.yaml`。它需要填写：

1. 已标定三箱 ROI 的 `vision.config_file` 路径；
2. 四个场地角点 `field.image_corners_px`；
3. 投放格 `4` 至 `7` 的实际 `[x_mm, y_mm]`；
4. 合理的 `motion.max_speed_mm_s`。

启动：

```bash
cd ~/wuilusai
./scripts/jetson_start_competition_demo.sh \
  ~/wuilusai_runtime/competition_demo.yaml
```

另开终端发送任务：

```bash
source ~/wuilusai/scripts/jetson_env.sh
competition_send_task mung_bean 4
```

可用豆类为 `mung_bean`、`soybean`、`white_bean`，投放格只允许 `4`、`5`、`6`、`7`。

视觉低置信度、ROI 无效、未标定场地、未教学投放点时，Demo 会拒绝或中止任务，不会退回到箱子中心盲抓。

## 9. 常见问题

| 现象 | 处理 |
| --- | --- |
| 没有 `/dev/ttyACM*` | 更换为可传数据的 Type-C 线；检查板子供电和 CDC 固件。 |
| 有 `ttyACM0`，但没有固定别名 | 重新加载 udev 规则，检查 `ID_SERIAL` 是否与规则一致。 |
| `Permission denied` | 当前用户未生效加入 `dialout`；重新登录后再试。 |
| `TimeoutError` | 先运行通信测试；确认不是其他程序占用串口，确认固件协议为 `(1,1,2)`。 |
| `cv2` 导入报 NumPy 错误 | 必须先 `source ~/wuilusai/scripts/jetson_env.sh`。 |
| Demo 提示绝对移动需要设零 | 重新进行原点流程，或在已确认的物理零点调用 `set_gantry_zero`。 |
