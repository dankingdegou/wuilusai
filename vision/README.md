# 比赛视觉第一版

这是固定场景、三箱豆类的第一阶段工具，不依赖 ROS2：它使用固定相机路径采图，提取每个箱子 ROI 的 Lab 鲁棒颜色特征，并输出 JSON 与标注调试图。

## Jetson 安装与标定

```bash
cd ~/wuliusai_competition/vision
cp config/boxes.example.yaml config/boxes.yaml
../scripts/capture_camera.sh --once
../.venv-camera/bin/python -s calibrate_rois.py --config config/boxes.yaml --image ~/Pictures/orbbec_archive/<刚拍的照片>.jpg
```

在弹出的三个窗口中依次框选三个箱子的**内部区域**，避免把箱框、标签和桌面纳入 ROI。完成后配置会保存。

## PC 手动拍摄标定图

先把相机固定为俯视三个箱子的角度，然后执行：

```bash
cd /home/rog/ros2_ws/wuliusai/vision
python3 capture_vision_rgb.py
```

它与项目根目录的 `capture_orbbec_rgb.py` 使用完全相同的交互方式：预览中按 Space / Enter 拍照，按 Q / Esc 退出。默认拍摄 `1280×960` 的 MJPG 图像，保存到 `vision/data/calibration/`；这与后续 ROI 和视觉推理使用的分辨率完全一致。若只拍一张并退出，可追加 `--once`。

## 运行

```bash
cd ~/wuliusai_competition/vision
./run_vision.sh --config config/boxes.yaml
```

输出会写到 `output/`：原始图、CLAHE 调试图和 JSON 结果。尚未填写 `prototypes` 时类别为 `unconfigured`，这是正常且安全的行为。

下一步是分别拍摄已知类别的三箱样本，使用输出 JSON 中每个箱子的 `L/a/b` 数值填写 `prototypes`，再评估不同光照下的稳定性。

## 批量样本标注与原型生成

多组连续照片只需标注一次。打开标注窗口后，在终端按 `left center right` 的顺序输入 `1/2/3/0`：`1=绿豆、2=黄豆、3=白豆、0=空箱`。

```bash
python3 label_dataset_groups.py
python3 build_color_prototypes.py
```

前者输出 `data/labels.yaml`，后者用所有非空标注样本生成鲁棒 Lab 原型，写入 `config/boxes.yaml`。

## 正式分类器（推荐）

单一 Lab 原型会受阴影影响，因此正式使用 SVM 颜色分布分类器。训练和验证均在 `vision/.venv` 中运行：

```bash
./.venv/bin/python train_bean_classifier.py
./run_vision_pc.sh --image data/calibration/orbbec_20260715_140453_006_2048x1536.jpg
```

训练会生成 `models/bean_classifier.joblib` 和按整组照片留出验证的 `output/cross_validation.json`。日常相机推理直接运行 `./run_vision_pc.sh`。

## 一键完整测试

```bash
./run_vision_test.sh
```

它会检查配置、模型、依赖、固定相机路径和三个 ROI，实际采集一帧并保存原图、标注图、JSON。若测试时三个箱子已按预期放好，可启用严格验收：

```bash
./run_vision_test.sh \
  --expect left=mung_bean,center=soybean,right=white_bean \
  --min-confidence 0.80
```

任一类别错误或置信度不足时，脚本以退出码 `2` 失败；这适合比赛前逐项验收。
