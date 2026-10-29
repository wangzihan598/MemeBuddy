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
    """按关键词命中数选择情绪；无命中回落到 generic。同分时库中靠前者优先。

    计数采用最长匹配消重：按词长降序命中，已命中的文本区间不再参与
    后续计数——避免子串关键词（如"哈哈哈"与"哈哈哈哈"）对同一处
    文本重复计分导致误判。
    """
    best, best_score = None, 0
    for mood in lib["moods"]:
        remaining = text
        score = 0
        for kw in sorted(mood["keywords"], key=len, reverse=True):
            if kw in remaining:
                score += 1
                remaining = remaining.replace(kw, "\u0000" * len(kw))
        if score > best_score:
            best, best_score = mood, score
    if best is None:
        best = next(m for m in lib["moods"] if m["id"] == "generic")
    return best


def recommend_effect(text: str, lib: dict | None = None) -> dict:
    """按情绪推荐动画效果（映射集中管理在 moods.json 的
    suggested_effect / effect_reason / suggested_amplitude 字段）。

    返回: {mood, mood_name, effect, reason, amplitude, is_default}
    - 未命中任何情绪 → generic 默认 bounce，is_default=True（调用方应告知用户）
    - 同分时库中靠前的情绪优先（具体情绪条目排在 generic 之前）
    """
    if lib is None:
        lib = load_library()
    mood = match_mood(text, lib)
    return {
        "mood": mood["id"],
        "mood_name": mood["name"],
        "effect": mood.get("suggested_effect", "bounce"),
        "reason": mood.get("effect_reason", "通用默认效果"),
        "amplitude": mood.get("suggested_amplitude", 1.0),
        "is_default": mood.get("is_default", False) or mood["id"] == "generic",
    }


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


def _edge_expand(img: Image.Image, m: int) -> Image.Image:
    """把图像四周用边缘像素复制延展 m 像素（用于位移后填充，避免纯黑边）。"""
    W, H = img.size
    out = Image.new("RGB", (W + 2 * m, H + 2 * m))
    out.paste(img, (m, m))
    if m > 0:
        out.paste(img.crop((0, 0, 1, H)).resize((m, H)), (0, m))            # 左
        out.paste(img.crop((W - 1, 0, W, H)).resize((m, H)), (m + W, m))    # 右
        out.paste(img.crop((0, 0, W, 1)).resize((W, m)), (m, 0))            # 上
        out.paste(img.crop((0, H - 1, W, H)).resize((W, m)), (m, m + H))    # 下
        out.paste(img.crop((0, 0, 1, 1)).resize((m, m)), (0, 0))            # 四角
        out.paste(img.crop((W - 1, 0, W, 1)).resize((m, m)), (m + W, 0))
        out.paste(img.crop((0, H - 1, 1, H)).resize((m, m)), (0, m + H))
        out.paste(img.crop((W - 1, H - 1, W, H)).resize((m, m)), (m + W, m + H))
    return out


def render_to_image(img: Image.Image, text: str, position: str = "bottom",
                    band: bool = False, margin_ratio: float = 0.05,
                    font_scale: float = 1.0, offset_y: int = 0,
                    scale_img: float = 1.0, shift: tuple[int, int] = (0, 0)) -> Image.Image:
    """把配文渲染到 PIL 图像上（返回新图像，不落盘）。

    offset_y: 文字整体垂直偏移（动图逐帧弹跳用）
    scale_img: 底图缩放系数（>1 放大后居中裁回原尺寸，动图缩放脉冲用）
    shift: 底图平移像素（动图抖动用）
    """
    src = img.convert("RGB")
    W, H = src.size

    if scale_img != 1.0 or shift != (0, 0):
        if scale_img != 1.0:
            sw, sh = int(W * scale_img), int(H * scale_img)
            src = src.resize((sw, sh), Image.LANCZOS)
            left = max(0, (sw - W) // 2)
            top = max(0, (sh - H) // 2)
            src = src.crop((left, top, left + W, top + H))
        if shift != (0, 0):
            # 边缘延展后裁取平移窗口：露出的边缘是原图边缘像素的延续，无黑边
            m = max(abs(shift[0]), abs(shift[1])) + 2
            exp = _edge_expand(src, m)
            src = exp.crop((m - shift[0], m - shift[1],
                            m - shift[0] + W, m - shift[1] + H))

    draw = ImageDraw.Draw(src)
    raw_lines = [seg.strip() for seg in text.split("|") if seg.strip()]
    if not raw_lines:
        return src

    max_width = int(W * (1 - 2 * margin_ratio))
    for size in range(max(18, int(W // 8 * font_scale)), 11, -2):
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
          "center": (H - block_h) // 2}[position] + offset_y

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
    return src


def render_caption(image_path: str | Path, text: str, out_path: str | Path,
                   position: str = "bottom", band: bool = False,
                   margin_ratio: float = 0.05, font_scale: float = 1.0) -> Path:
    """把配文渲染到底图并保存（静态成品，动图请用 animate）。"""
    src = Image.open(image_path)
    out = render_to_image(src, text, position=position, band=band,
                          margin_ratio=margin_ratio, font_scale=font_scale)
    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_p)
    return out_p


# ---------------------------------------------------------------- 动图（GIF）

def animate_gif(image_path: str | Path, text: str, out_path: str | Path,
                effect: str = "bounce", frames: int = 16, fps: int = 12,
                position: str = "bottom", band: bool = False,
                font_scale: float = 0.62, max_width: int = 480,
                loop: int = 0, amplitude: float = 1.0) -> Path:
    """生成动图 GIF（纯本地逐帧渲染，零积分）。

    effect: bounce(文字弹跳) / shake(整图抖动) / zoom(缩放脉冲)
    frames/fps: 帧数与帧率；max_width: 降采样宽度（控制文件体积）
    amplitude: 动效幅度倍率（0.2–2.0）
    """
    # ---- 参数校验（友好错误，不裸崩） ----
    if not (2 <= frames <= 60):
        raise ValueError(f"frames 必须在 2–60 之间，当前: {frames}")
    if not (1 <= fps <= 60):
        raise ValueError(f"fps 必须在 1–60 之间，当前: {fps}")
    if max_width < 160:
        raise ValueError(f"max_width 不能小于 160（保证文字可读），当前: {max_width}")
    if not (0.2 <= amplitude <= 2.0):
        raise ValueError(f"amplitude 必须在 0.2–2.0 之间，当前: {amplitude}")
    src_path = Path(image_path)
    if not src_path.exists():
        raise FileNotFoundError(f"底图文件不存在: {src_path}")

    # GIF 帧延以厘秒存储且最小 20ms（低于会被播放器钳制成 100ms 导致变慢）
    duration_ms = max(20, round(1000 / fps))
    if fps > 50:
        print("提示：GIF 帧延最小 20ms，fps>50 会被播放器钳制，建议 8–25。")

    import math
    src = Image.open(src_path).convert("RGB")
    if src.width > max_width:
        ratio = max_width / src.width
        src = src.resize((max_width, int(src.height * ratio)), Image.LANCZOS)

    frame_imgs = []
    for i in range(frames):
        t = i / frames * 2 * math.pi
        if effect == "bounce":
            # 幅度 0.035·H：320px 下约 11px，缩略图尺寸可感知
            dy = -round(abs(math.sin(t)) * src.height * 0.035 * amplitude)
            f = render_to_image(src, text, position=position, band=band,
                                font_scale=font_scale, offset_y=dy)
        elif effect == "shake":
            dx = round(math.sin(t * 2) * src.width * 0.010 * amplitude)
            dy = round(math.cos(t * 3) * src.height * 0.008 * amplitude)
            f = render_to_image(src, text, position=position, band=band,
                                font_scale=font_scale,
                                shift=(dx, dy))
        elif effect == "zoom":
            # 幅度 0.08：缩放脉冲在缩略图下可感知
            z = 1.0 + 0.08 * amplitude * (0.5 - 0.5 * math.cos(t))
            f = render_to_image(src, text, position=position, band=band,
                                font_scale=font_scale, scale_img=z)
        else:
            raise ValueError(f"未知效果: {effect}（可选 bounce/shake/zoom）")
        frame_imgs.append(f)

    out = Path(out_path)
    if out.exists():
        raise FileExistsError(f"输出文件已存在，为避免静默覆盖请先移除或更换路径: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    frame_imgs[0].save(out, save_all=True, append_images=frame_imgs[1:],
                       duration=duration_ms, loop=loop, optimize=True)
    return out


def compare_effects(image_path: str | Path, text: str, out_prefix: str | Path,
                    frames: int = 12, fps: int = 10, position: str = "bottom",
                    band: bool = False, font_scale: float = 0.62,
                    max_width: int = 320, amplitude: float = 1.0) -> list[dict]:
    """三效果并排预览：同底图、同文案、同规格生成 bounce/shake/zoom。

    每个效果独立生成（单个失败不影响其余），文件名带效果标签避免覆盖，
    另产出一张多帧静态对比图（_对比图.png）作为快速比较入口——
    动态效果请分别打开各 GIF 查看（CLI 环境无动态 GUI，如实说明）。
    返回逐效果结果列表: {effect, path, ok, size_kb, error}
    """
    prefix = Path(out_prefix)
    results = []
    for eff in ("bounce", "shake", "zoom"):
        out = prefix.parent / f"{prefix.name}_{eff}.gif"
        item = {"effect": eff, "path": out, "ok": False,
                "size_kb": 0, "error": None}
        try:
            animate_gif(image_path, text, out, effect=eff, frames=frames,
                        fps=fps, position=position, band=band,
                        font_scale=font_scale, max_width=max_width,
                        amplitude=amplitude)
            item["ok"] = True
            item["size_kb"] = out.stat().st_size // 1024
        except Exception as e:  # 单效果失败不中断其余
            item["error"] = f"{type(e).__name__}: {e}"
        results.append(item)

    ok_items = [r for r in results if r["ok"]]
    if ok_items:
        tiles = []
        for r in ok_items:
            im = Image.open(r["path"])
            n = getattr(im, "n_frames", 1)
            picks = sorted({0, n // 3, (2 * n) // 3})
            frames_img = []
            for idx in picks:
                im.seek(idx)
                f = im.convert("RGB")
                f.thumbnail((220, 220))
                frames_img.append(f)
            tiles.append((r, frames_img))
            im.seek(0)
        tile_w = max(f.width for _, fs in tiles for f in fs)
        tile_h = max(f.height for _, fs in tiles for f in fs)
        label_h = 20
        sheet = Image.new("RGB", (len(tiles) * (3 * (tile_w + 4) + 10) + 6,
                                  tile_h + label_h + 8), (250, 250, 250))
        d = ImageDraw.Draw(sheet)
        for i, (r, fs) in enumerate(tiles):
            x0 = 6 + i * (3 * (tile_w + 4) + 10)
            for j, f in enumerate(fs):
                sheet.paste(f, (x0 + j * (tile_w + 4), 4))
            d.text((x0 + 2, tile_h + 8),
                   f"{r['effect']} {r['size_kb']}KB", fill=(0, 0, 0))
        sheet_path = prefix.parent / f"{prefix.name}_对比图.png"
        sheet.save(sheet_path)
    return results

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
    pr.add_argument("--font-scale", type=float, default=1.0,
                    help="字号缩放系数（默认 1.0；人像照片建议 0.5-0.7 避让脸部）")

    pa = sub.add_parser("animate", help="生成动图 GIF（纯本地逐帧动画，零积分）")
    pa.add_argument("image", help="底图路径")
    pa.add_argument("--text", required=True, help="配文，多行用 | 分隔")
    pa.add_argument("--out", required=True, help="输出 GIF 路径")
    pa.add_argument("--effect", default="auto",
                    choices=["auto", "bounce", "shake", "zoom"],
                    help="动画效果：auto=按情绪自动推荐（默认）/ bounce / shake / zoom；手动指定优先于推荐")
    pa.add_argument("--frames", type=int, default=16, help="帧数（默认 16）")
    pa.add_argument("--fps", type=int, default=12, help="帧率（默认 12）")
    pa.add_argument("--position", default="bottom", choices=["top", "bottom", "center"])
    pa.add_argument("--band", action="store_true", help="文字区加半透明黑底条")
    pa.add_argument("--font-scale", type=float, default=0.62, help="字号缩放系数")
    pa.add_argument("--max-width", type=int, default=480, help="降采样宽度（控制 GIF 体积，≥160）")
    pa.add_argument("--amplitude", type=float, default=None,
                    help="动效幅度倍率（0.2–2.0；缺省时 auto 模式采用情绪推荐值，否则 1.0）")

    pcmp = sub.add_parser("compare", help="三效果并排预览：同底图同文案生成 bounce/shake/zoom + 对比图")
    pcmp.add_argument("image", help="底图路径")
    pcmp.add_argument("--text", required=True, help="配文，多行用 | 分隔")
    pcmp.add_argument("--out-prefix", required=True,
                      help="输出前缀：生成 <前缀>_bounce.gif / _shake.gif / _zoom.gif / _对比图.png")
    pcmp.add_argument("--frames", type=int, default=12, help="帧数（默认 12）")
    pcmp.add_argument("--fps", type=int, default=10, help="帧率（默认 10）")
    pcmp.add_argument("--position", default="bottom", choices=["top", "bottom", "center"])
    pcmp.add_argument("--band", action="store_true", help="文字区加半透明黑底条")
    pcmp.add_argument("--font-scale", type=float, default=0.62, help="字号缩放系数")
    pcmp.add_argument("--max-width", type=int, default=320, help="降采样宽度（≥160）")
    pcmp.add_argument("--amplitude", type=float, default=None,
                      help="动效幅度倍率（0.2–2.0；缺省时采用情绪推荐值）")

    args = p.parse_args(argv)

    try:
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
                                 position=args.position, band=args.band,
                                 font_scale=args.font_scale)
            print(f"已生成: {out}")
            return 0

        if args.cmd == "animate":
            if args.effect == "auto":
                rec = recommend_effect(args.text)
                effect = rec["effect"]
                amp = args.amplitude if args.amplitude is not None else rec["amplitude"]
                print(f"自动推荐：识别情绪「{rec['mood_name']}」→ 效果 {effect}（{rec['reason']}）")
                if rec["is_default"]:
                    print("提示：未命中特定情绪，使用默认效果 bounce。")
            else:
                effect = args.effect  # 用户手动指定，优先于自动推荐
                amp = args.amplitude if args.amplitude is not None else 1.0
            out = animate_gif(args.image, args.text, args.out,
                              effect=effect, frames=args.frames, fps=args.fps,
                              position=args.position, band=args.band,
                              font_scale=args.font_scale, max_width=args.max_width,
                              amplitude=amp)
            size_kb = out.stat().st_size // 1024
            print(f"已生成: {out}（{size_kb} KB）")
            return 0

        if args.cmd == "compare":
            rec = recommend_effect(args.text)
            amp = args.amplitude if args.amplitude is not None else rec["amplitude"]
            print(f"情绪参考：{rec['mood_name']}（推荐 {rec['effect']}，{rec['reason']}）")
            print("三效果生成中（同底图/同文案/同规格，文件名带效果标签）...")
            results = compare_effects(args.image, args.text, args.out_prefix,
                                      frames=args.frames, fps=args.fps,
                                      position=args.position, band=args.band,
                                      font_scale=args.font_scale,
                                      max_width=args.max_width, amplitude=amp)
            for r in results:
                if r["ok"]:
                    print(f"  [{r['effect']:6}] ✓ {r['path']}（{r['size_kb']} KB）")
                else:
                    print(f"  [{r['effect']:6}] ✗ 生成失败: {r['error']}")
            sheet = Path(str(args.out_prefix) + "_对比图.png")
            if sheet.exists():
                print(f"对比图: {sheet}（各效果 3 帧抽样；动态效果请分别打开 GIF 查看）")
            if not any(r["ok"] for r in results):
                print("错误：三种效果全部失败", file=sys.stderr)
                return 2
            return 0
    except (ValueError, FileNotFoundError, FileExistsError) as e:
        print(f"错误：{e}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
