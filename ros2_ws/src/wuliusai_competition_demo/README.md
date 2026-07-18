# 比赛单铲取料 Demo

该包把固定相机识别、像素到场地坐标转换、X 双电机龙门和一次投放任务串联为 ROS2 Action：

`/competition/execute_scoop` (`wuliusai_stepper_msgs/action/ExecuteScoop`)

一条任务只做一次：识别目标豆箱 → 选取豆子密集且避开边缘的铲取点 → X 移到该点 → 模拟铲取 → X 移到投放位 → 模拟投放 → 返回安全点。当前仅 X 龙门真实运动，Y、Z、夹爪/铲斗阶段明确为模拟，不能误认为已经接入了实际执行器。

## 坐标

内场左下是 `(0, 0)`，右方为 X 正、上方为 Y 正，尺寸 `4000 × 2000 mm`。场地图四角点击顺序固定为：左下、右下、右上、左上。示意图中的三种豆箱名义坐标分别是绿豆 `(400,400)`、黄豆 `(400,1000)`、白豆 `(400,1600)`；实际铲取点由视觉在 ROI 内选取，不使用盲目的名义中心点。

## 首次标定

复制 `config/competition_demo.yaml` 到一个不被 Git 覆盖的运行配置，例如 `~/wuilusai_runtime/competition_demo.yaml`，然后填写：

1. `vision.config_file`：已完成三箱 ROI 标定的 `vision/config/boxes.yaml` 绝对路径。
2. `vision.model_file`：训练好的 `bean_classifier*.joblib` 绝对路径；可留空以临时使用原型分类。
3. `destination_slots_mm` 的 4、5、6、7：每个投放格实际中心的 `[x_mm, y_mm]`。
4. 使用固定相机拍一张完整场地图，执行：

```bash
competition_calibrate_field --image ~/Pictures/field.jpg \
  --config ~/wuilusai_runtime/competition_demo.yaml
```

窗口中依次点左下、右下、右上、左上；`r` 重点，Enter 保存。未完成上述任何一项，任务会拒绝或中止，不会移动到默认中心。

## 启动与任务

先启动并完成 X 龙门回零（`/stepper_controller/set_gantry_zero`），再启动：

```bash
ros2 launch wuliusai_competition_demo competition_demo.launch.py \
  config:=~/wuilusai_runtime/competition_demo.yaml
```

发送单次任务：

```bash
competition_send_task mung_bean 4
competition_send_task soybean 5
competition_send_task white_bean 6
```

Action 会输出阶段反馈：`SENSE`、`MOVE_TO_SOURCE`、`SCOOP_SIM`、`MOVE_TO_TARGET`、`DROP_SIM`、`RETURN_SAFE`。执行前清空运动区域；首次请将 `motion.max_speed_mm_s` 调低到安全值并以空载测试。

## 视觉安全策略

每项任务最多采图 3 次（初始 1 次加最多 2 次重拍）。只有目标类别置信度达到 `vision.minimum_confidence`，并且从当前箱子边缘背景自适应分割出足够的豆粒区域，才会输出铲取点。密度最高点会避开 ROI 边界。任何失败直接 abort；绝不退回到箱子中心盲抓。
