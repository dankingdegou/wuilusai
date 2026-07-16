#!/usr/bin/env python3
"""按连续拍摄组给 left/center/right 三个 ROI 标注豆类类别。"""
from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

import cv2
import yaml


def captured_at(path: Path) -> datetime:
    match = re.search(r"(20\d{6}_\d{6})", path.name)
    if match:
        return datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
    return datetime.fromtimestamp(path.stat().st_mtime)


def groups(paths: list[Path], max_gap: float) -> list[list[Path]]:
    output: list[list[Path]] = []
    for path in paths:
        if not output or (captured_at(path) - captured_at(output[-1][-1])).total_seconds() > max_gap:
            output.append([path])
        else:
            output[-1].append(path)
    return output


def preview(image, boxes, title: str):
    canvas = image.copy()
    for name, box in boxes.items():
        x, y, w, h = (int(box[key]) for key in ("x", "y", "w", "h"))
        cv2.rectangle(canvas, (x, y), (x + w, y + h), (0, 255, 255), 2)
        cv2.putText(canvas, name, (x, max(25, y - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    cv2.imshow(title, canvas)
    cv2.waitKey(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="按连续拍摄组标注三箱豆类")
    parser.add_argument("--config", default="config/boxes.yaml")
    parser.add_argument("--images-dir", default="data/calibration")
    parser.add_argument("--output", default="data/labels.yaml")
    parser.add_argument("--labels", default="mung_bean,soybean,white_bean", help="三种类别名，以逗号分隔")
    parser.add_argument("--gap-seconds", type=float, default=4.0, help="超过此间隔即视作新摆放组")
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    class_names = [item.strip() for item in args.labels.split(",") if item.strip()]
    paths = sorted(Path(args.images_dir).glob("orbbec_*.jpg"), key=captured_at)
    batches = groups(paths, args.gap_seconds)
    if not batches:
        raise SystemExit("未找到 orbbec_*.jpg 图片。")
    output = {"classes": class_names, "labels": {}}
    choices = {str(index + 1): label for index, label in enumerate(class_names)}
    choices["0"] = "empty"
    print("编号：" + "，".join(f"{key}={value}" for key, value in choices.items()))
    print("每组输入三个编号，顺序为 left center right；例如：1 2 3。输入 s 跳过整组。")
    window = "Dataset labels (Q to stop)"
    try:
        for index, batch in enumerate(batches, start=1):
            image = cv2.imread(str(batch[0]))
            if image is None:
                continue
            preview(image, config["boxes"], window)
            print(f"\n组 {index}/{len(batches)}，共 {len(batch)} 张：{batch[0].name}")
            while True:
                answer = input("left center right > ").strip().lower()
                if answer == "q":
                    Path(args.output).write_text(yaml.safe_dump(output, allow_unicode=True, sort_keys=False), encoding="utf-8")
                    return 0
                if answer == "s":
                    break
                values = answer.split()
                if len(values) == 3 and all(value in choices for value in values):
                    labels = dict(zip(("left", "center", "right"), (choices[value] for value in values)))
                    for path in batch:
                        output["labels"][path.name] = labels
                    break
                print("输入无效，请输入三个编号，例如：1 2 3；或输入 s / q。")
    finally:
        cv2.destroyAllWindows()
    Path(args.output).write_text(yaml.safe_dump(output, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"标注已保存：{args.output}，共 {len(output['labels'])} 张图片。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
