#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MemeBuddy 核心引擎（WorkBuddy 版）

三个子命令：
  idea    根据输入生成表情包创意方案（情绪识别 -> 画面构想 + 配文 + 适用场景）
  render  把配文渲染到一张底图上（中文描边字，保证清晰无乱码）
  plan    idea 的文件版：把创意方案写入 output/ 下的 JSON，供对话流程引用

设计要点：
  - 图片生成模型画中文字容易乱码，因此本工具约定：AI 只生成"无文字"的画面，
    配文由本脚本用本地字体（微软雅黑/黑体）精确渲染。
  - moods.json 是可扩展的情绪/画风库，新场景直接加条目即可，不写死在代码里。
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import unicodedata
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("错误：缺少 Pillow。请先执行: python -m pip install pillow", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = ROOT / "templates"
OUTPUT_DIR = ROOT / "output"

# Windows 自带中文字体，按优先级排列
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",   # 微软雅黑 Bold
    r"C:\Windows\Fonts\msyh.ttc",     # 微软雅黑
    r"C:\Windows\Fonts\simhei.ttf",   # 黑体
]

# ---------------------------------------------------------------- 库加载

def load_library() -> dict:
    with open(TEMPLATES_DIR / "moods.json", encoding="utf-8") as f:
        return json.load(f)


def pick_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size, index=0)
            except OSError:
                continue
    raise RuntimeError("未找到可用的中文字体（msyh/simhei）")

# ---------------------------------------------------------------- 意图识别

def match_mood(text: str, lib: dict) -> dict:
    """按关键词命中数选择情绪；无命中回落到 generic。"""
    best, best_score = None, 0
    for mood in lib["moods"]:
        score = sum(1 for kw in mood["keywords"] if kw in text)
        if score > best_score:
            best, best_score = mood, score
    if best is None:
        best = next(m for m in lib["moods"] if m["id"] == "generic")
    return best


_FILLER = re.compile(r"今天|最近|真的|好想|感觉|突然|已经|又被|怎么|为什么|呜呜|啊啊|啊啊啊|[，。！！？、~～\s]+")

def extract_theme(text: str, max_len: int = 14) -> str:
    """从用户输入中提取主题短语，用于填入配文槽位。"""
    theme = _FILLER.sub("", text).strip("！？?!.。 ")
    if not theme:
        theme = text.strip()
    return theme[:max_len]

# ---------------------------------------------------------------- 创意生成

def gen_ideas(prompt: str, n: int = 3, style_id: str | None = None,
              seed: int | None = None) -> list[dict]:
    """生成 n 个创意方案。随机组合 + 主题注入，自定义主题不会被固定模板锁死。"""
    lib = load_library()
    rng = random.Random(seed)
    mood = match_mood(prompt, lib)
    theme = extract_theme(prompt)

    styles = lib["styles"]
    style = next((s for s in styles if s["id"] == style_id), None) or rng.choice(styles)

    visuals = mood["visual_concepts"][:]
    captions = mood["caption_patterns"][:]
    usages = mood["scene_usages"][:]
    rng.shuffle(visuals)
    rng.shuffle(captions)
    rng.shuffle(usages)

    ideas = []
    for i in range(n):
        caption = captions[i % len(captions)].replace("{theme}", theme)
        visual = visuals[i % len(visuals)]
        image_prompt = f"{visual}，{style['prompt_suffix']}，{lib['negative_prompt']}"
        ideas.append({
            "id": f"idea-{i + 1}",
            "mood": mood["id"],
            "mood_name": mood["name"],
            "style": style["id"],
            "style_name": style["name"],
            "theme": theme,
            "场景描述": f"针对「{prompt.strip()}」的{mood['name']}向表达",
            "画面构想": visual,
            "image_prompt": image_prompt,
            "配文": caption,
            "适用场景": usages[i % len(usages)],
        })
    return ideas

# ---------------------------------------------------------------- 文本渲染

def _wrap_line(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """按像素宽度把一行中文折成多行（支持中英文混排）。"""
    lines, buf, buf_w = [], [], 0
    for ch in text:
        w = font.getbbox(ch)[2] - font.getbbox(ch)[0]
        if buf_w + w > max_width and buf:
            lines.append("".join(buf))
            buf, buf_w = [], 0
        buf.append(ch)
        buf_w += w
    if buf:
        lines.append("".join(buf))
    return lines


def render_caption(image_path: str | Path, text: str, out_path: str | Path,
                   position: str = "bottom", band: bool = False,
                   margin_ratio: float = 0.05) -> Path:
    """把配文渲染到底图上。

    - 多行用 | 分隔（如 "上半句|下半句"）
    - 白字黑描边（经典表情包样式），自动缩放字号避免溢出
    - position: top / bottom / center
    - band: 在文字区加半透明黑底条，提高可读性
    """
    src = Image.open(image_path).convert("RGB")
    W, H = src.size
    draw = ImageDraw.Draw(src)

    raw_lines = [seg.strip() for seg in text.split("|") if seg.strip()]
    if not raw_lines:
        raise ValueError("配文为空")

    max_width = int(W * (1 - 2 * margin_ratio))
    # 从大到小尝试字号，直到整块文字放得下
    for size in range(max(18, W // 8), 11, -2):
        font = pick_font(size)
        stroke = max(2, size // 14)
        wrapped: list[str] = []
        for seg in raw_lines:
            wrapped.extend(_wrap_line(seg, font, max_width) or [""])
        line_h = size + int(size * 0.35)
        block_h = line_h * len(wrapped)
        fits = all(
            (font.getbbox(l)[2] - font.getbbox(l)[0]) <= max_width
            for l in wrapped
        )
        if fits and block_h <= H * 0.45:
            break

    y0 = {"top": int(H * margin_ratio),
          "bottom": H - int(H * margin_ratio) - block_h,
          "center": (H - block_h) // 2}[position]

    if band:
        overlay = Image.new("RGBA", src.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        pad = int(size * 0.35)
        od.rectangle([0, max(0, y0 - pad), W, min(H, y0 + block_h + pad)],
                     fill=(0, 0, 0, 150))
        src = Image.alpha_composite(src.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(src)

    for line in wrapped:
        w = font.getbbox(line)[2] - font.getbbox(line)[0]
        x = (W - w) // 2
        draw.text((x, y0), line, font=font, fill=(255, 255, 255),
                  stroke_width=stroke, stroke_fill=(0, 0, 0))
        y0 += line_h

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    src.save(out)
    return out

# ---------------------------------------------------------------- 命令行入口

def _print_ideas(ideas: list[dict]) -> None:
    for it in ideas:
        print(f"\n【{it['id']}】{it['mood_name']} · {it['style_name']}")
        print(f"  场景描述: {it['场景描述']}")
        print(f"  画面构想: {it['画面构想']}")
        print(f"  配文    : {it['配文']}")
        print(f"  适用场景: {it['适用场景']}")
        print(f"  画图提示词: {it['image_prompt']}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="memebuddy", description="MemeBuddy 表情包核心引擎")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("idea", help="生成表情包创意方案")
    pi.add_argument("prompt", help="用户输入：一句话/情绪/对话/网络梗")
    pi.add_argument("-n", type=int, default=3, help="方案数量（默认 3）")
    pi.add_argument("--style", default=None, help="指定画风 id（见 templates/moods.json styles）")
    pi.add_argument("--seed", type=int, default=None, help="随机种子（可复现）")
    pi.add_argument("--save", action="store_true", help="同时把方案写入 output/ JSON")

    pr = sub.add_parser("render", help="把配文渲染到图片上")
    pr.add_argument("image", help="底图路径")
    pr.add_argument("--text", required=True, help="配文，多行用 | 分隔")
    pr.add_argument("--out", required=True, help="输出图片路径")
    pr.add_argument("--position", default="bottom", choices=["top", "bottom", "center"])
    pr.add_argument("--band", action="store_true", help="文字区加半透明黑底条")

    args = p.parse_args(argv)

    if args.cmd == "idea":
        ideas = gen_ideas(args.prompt, n=args.n, style_id=args.style, seed=args.seed)
        _print_ideas(ideas)
        if args.save:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = OUTPUT_DIR / f"ideas_{ts}.json"
            path.write_text(json.dumps(
                {"input": args.prompt, "ideas": ideas}, ensure_ascii=False, indent=2),
                encoding="utf-8")
            print(f"\n方案已保存: {path}")
        return 0

    if args.cmd == "render":
        out = render_caption(args.image, args.text, args.out,
                             position=args.position, band=args.band)
        print(f"已生成: {out}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
