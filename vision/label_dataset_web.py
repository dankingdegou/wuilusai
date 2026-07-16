#!/usr/bin/env python3
"""在浏览器中按连续拍摄组标注三个箱子的豆类，不依赖 OpenCV GUI。"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import cv2
import yaml


def captured_at(path: Path) -> datetime:
    match = re.search(r"(20\d{6}_\d{6})", path.name)
    if not match:
        raise ValueError(f"文件名缺少时间戳：{path.name}")
    return datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")


def make_groups(paths: list[Path], gap_seconds: float) -> list[list[Path]]:
    batches: list[list[Path]] = []
    for path in paths:
        if not batches or (captured_at(path) - captured_at(batches[-1][-1])).total_seconds() > gap_seconds:
            batches.append([path])
        else:
            batches[-1].append(path)
    return batches


def draw_rois(image, boxes, group_index: int):
    canvas = image.copy()
    for name, box in boxes.items():
        x, y, w, h = (int(box[key]) for key in ("x", "y", "w", "h"))
        cv2.rectangle(canvas, (x, y), (x + w, y + h), (0, 255, 255), 2)
        cv2.putText(canvas, name, (x, max(25, y - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    cv2.putText(canvas, f"GROUP {group_index:02d}", (25, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 255), 3)
    return canvas


PAGE = """<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>豆类样本分组标注</title>
<style>body{font-family:sans-serif;background:#f4f6f8;margin:24px}h1{margin-bottom:4px}.hint{color:#555}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:18px}.card{background:#fff;border-radius:10px;padding:12px;box-shadow:0 1px 4px #bbb}.card img{width:100%;height:auto;border-radius:6px}.controls{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}.controls label{font-weight:bold}.controls select{display:block;width:100%;padding:6px;margin-top:4px}.save{margin-top:10px;padding:8px 16px;background:#1677ff;color:white;border:0;border-radius:5px;font-size:15px}.saved{color:#198754;font-weight:bold;margin-left:8px}</style>
</head><body><h1>Jetson 豆类样本分组标注</h1><p class='hint'>每张图代表一次摆放组；按 left / center / right 选择类别并保存。0=空箱。保存后自动应用到本组全部连续照片。</p>
<div id='groups' class='grid'></div><script>
const labels=['mung_bean','soybean','white_bean','empty'];
fetch('/api/groups').then(r=>r.json()).then(groups=>{const root=document.querySelector('#groups');groups.forEach(g=>{const card=document.createElement('section');card.className='card';const options=(selected)=>labels.map(x=>`<option ${x===selected?'selected':''}>${x}</option>`).join('');card.innerHTML=`<h2>组 ${String(g.index).padStart(2,'0')}（${g.count} 张）</h2><p>${g.first}<br>至 ${g.last}</p><img src='${g.image}'><div class='controls'>${['left','center','right'].map(name=>`<label>${name}<select data-box='${name}'>${options(g.labels[name]||'mung_bean')}</select></label>`).join('')}</div><button class='save'>保存本组</button><span class='saved'></span>`;card.querySelector('.save').onclick=()=>{const values={};card.querySelectorAll('select').forEach(s=>values[s.dataset.box]=s.value);fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({index:g.index,labels:values})}).then(r=>r.json()).then(x=>{card.querySelector('.saved').textContent=x.ok?'已保存':'保存失败';});};root.appendChild(card);});});
</script></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="浏览器式豆类分组标注")
    parser.add_argument("--config", default="config/boxes.yaml")
    parser.add_argument("--images-dir", required=True)
    parser.add_argument("--since", required=True, help="YYYYMMDD_HHMMSS")
    parser.add_argument("--output", default="data/jetson_labels.yaml")
    parser.add_argument("--gallery-dir", default="data/jetson_label_gallery")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    since = datetime.strptime(args.since, "%Y%m%d_%H%M%S")
    paths = [path for path in sorted(Path(args.images_dir).glob("orbbec_*.jpg"), key=captured_at) if captured_at(path) >= since]
    batches = make_groups(paths, 4.0)
    if not batches:
        raise SystemExit("没有匹配的图片。")
    gallery = Path(args.gallery_dir)
    gallery.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(args.output)
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"classes": ["mung_bean", "soybean", "white_bean"], "labels": {}}
    group_data = []
    for index, batch in enumerate(batches, 1):
        image_path = gallery / f"group_{index:02d}.jpg"
        image = cv2.imread(str(batch[0]))
        if image is None:
            continue
        cv2.imwrite(str(image_path), draw_rois(image, config["boxes"], index), [cv2.IMWRITE_JPEG_QUALITY, 92])
        saved = manifest["labels"].get(batch[0].name, {})
        group_data.append({"index": index, "count": len(batch), "first": batch[0].name, "last": batch[-1].name, "image": f"/images/{image_path.name}", "labels": saved})

    class Handler(BaseHTTPRequestHandler):
        def send_bytes(self, content: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                self.send_bytes(PAGE.encode(), "text/html; charset=utf-8")
            elif path == "/api/groups":
                self.send_bytes(json.dumps(group_data, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            elif path.startswith("/images/"):
                file_path = gallery / Path(path).name
                if file_path.is_file():
                    self.send_bytes(file_path.read_bytes(), "image/jpeg")
                else:
                    self.send_bytes(b"not found", "text/plain", 404)
            else:
                self.send_bytes(b"not found", "text/plain", 404)

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/save":
                self.send_bytes(b"not found", "text/plain", 404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(size))
                batch = batches[int(data["index"]) - 1]
                values = data["labels"]
                if set(values) != {"left", "center", "right"} or any(value not in {*manifest["classes"], "empty"} for value in values.values()):
                    raise ValueError("invalid labels")
                for image_path in batch:
                    manifest["labels"][image_path.name] = values
                manifest_path.parent.mkdir(parents=True, exist_ok=True)
                manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
                self.send_bytes(b'{"ok":true}', "application/json")
            except Exception as exc:
                self.send_bytes(json.dumps({"ok": False, "error": str(exc)}).encode(), "application/json", 400)

        def log_message(self, format: str, *values) -> None:
            print("[web] " + format % values)

    print(f"已生成 {len(group_data)} 个摆放组。")
    print(f"请在浏览器打开：http://<Jetson_IP>:{args.port}/")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
