#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MemeBuddy 核心功能自动化测试。运行: python -m unittest discover tests -v"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from memebuddy import gen_ideas, match_mood, load_library, extract_theme, render_caption, animate_gif
from PIL import Image, ImageDraw


def make_test_image(path, size=(800, 600), color=(120, 180, 220)):
    Image.new("RGB", size, color).save(path)


class TestIdeaGeneration(unittest.TestCase):

    def test_1_bu_xiang_shang_ban(self):
        """验收1：'今天不想上班' 得到合理创意与配文"""
        ideas = gen_ideas("今天不想上班", n=3, seed=42)
        self.assertEqual(len(ideas), 3)
        it = ideas[0]
        self.assertEqual(it["mood"], "no_work")
        for key in ("场景描述", "画面构想", "配文", "适用场景", "image_prompt"):
            self.assertTrue(it[key], f"字段 {key} 不应为空")
        self.assertIn("不要出现任何文字", it["image_prompt"])

    def test_2_yi_du_bu_hui(self):
        """验收2：'对方已读不回' 匹配吐槽语境"""
        ideas = gen_ideas("对方已读不回", n=2, seed=7)
        self.assertEqual(ideas[0]["mood"], "left_on_read")

    def test_3_custom_theme_not_fixed(self):
        """验收3：自定义主题不被固定模板机械返回——主题注入 + 随机组合"""
        custom = "考研二战失败想哭"
        a = gen_ideas(custom, n=3, seed=1)
        b = gen_ideas(custom, n=3, seed=99)
        self.assertEqual(a[0]["theme"], extract_theme(custom))
        # 不同种子应产生不同组合（至少配文或画面不同）
        sig_a = [(i["配文"], i["画面构想"]) for i in a]
        sig_b = [(i["配文"], i["画面构想"]) for i in b]
        self.assertNotEqual(sig_a, sig_b)
        # 无命中的自定义主题应回落 generic 且主题出现在配文中
        g = gen_ideas("猫把我的作业吃了", n=1, seed=3)
        self.assertEqual(g[0]["mood"], "generic")
        self.assertIn(extract_theme("猫把我的作业吃了"), g[0]["配文"])

    def test_4_iteration_style(self):
        """验收4：指定画风可复现地改变创意（迭代修改的基础）"""
        a = gen_ideas("周五下班", n=1, style_id="pixel", seed=5)
        b = gen_ideas("周五下班", n=1, style_id="guofeng", seed=5)
        self.assertEqual(a[0]["style"], "pixel")
        self.assertEqual(b[0]["style"], "guofeng")
        self.assertIn("像素", a[0]["image_prompt"])
        self.assertIn("水墨", b[0]["image_prompt"])


class TestRender(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = str(Path(self.tmp.name) / "base.png")
        make_test_image(self.base)

    def tearDown(self):
        self.tmp.cleanup()

    def test_render_creates_valid_file(self):
        """验收5（本地渲染部分）：输出文件存在且可打开"""
        out = Path(self.tmp.name) / "out.png"
        result = render_caption(self.base, "今天不想上班", out)
        self.assertTrue(result.exists())
        img = Image.open(result)
        img.verify()  # 文件完整性
        self.assertEqual(Image.open(result).size, (800, 600))

    def test_render_multiline_and_band(self):
        """多行配文（|分隔）+ 黑底条模式不报错且产出文件"""
        out = Path(self.tmp.name) / "out2.png"
        render_caption(self.base, "对方已读不回|我发的不是消息，是心情",
                       out, position="bottom", band=True)
        self.assertTrue(out.exists())

    def test_render_actually_draws_pixels(self):
        """确认文字真实绘制：渲染后图像与原图不同"""
        import io
        out = Path(self.tmp.name) / "out3.png"
        render_caption(self.base, "无语子", out, position="center")
        a = Image.open(self.base).convert("L")
        b = Image.open(out).convert("L")
        diff = sum(1 for pa, pb in zip(a.getdata(), b.getdata()) if pa != pb)
        self.assertGreater(diff, 500, "渲染后应产生像素差异（文字已绘制）")

    def test_render_long_text_no_crash(self):
        """超长配文自动缩放换行，不崩溃不溢出"""
        out = Path(self.tmp.name) / "out4.png"
        render_caption(self.base, "这是一条非常长的配文" * 6, out)
        self.assertTrue(out.exists())


class TestAnimate(unittest.TestCase):
    """动图（GIF）功能评测用例"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = str(Path(self.tmp.name) / "base.png")
        # 带图案的底图（纯色图缩放后无像素差异，不适合测 zoom）
        img = Image.new("RGB", (800, 600), (120, 180, 220))
        d = ImageDraw.Draw(img)
        d.ellipse([100, 100, 700, 500], fill=(250, 190, 90))
        d.rectangle([300, 200, 500, 400], fill=(90, 140, 90))
        img.save(self.base)

    def tearDown(self):
        self.tmp.cleanup()

    def test_animate_creates_multiframe_gif(self):
        """GIF 生成：多帧、可打开、已降采样"""
        out = Path(self.tmp.name) / "out.gif"
        result = animate_gif(self.base, "无语子", out,
                             effect="bounce", frames=8, fps=10)
        self.assertTrue(result.exists())
        im = Image.open(result)
        self.assertGreaterEqual(getattr(im, "n_frames", 1), 2, "应为多帧 GIF")
        self.assertLessEqual(im.size[0], 480, "应按 max_width 降采样")

    def test_animate_three_effects(self):
        """三种效果（bounce/shake/zoom）均产出多个独立画面"""
        from PIL import ImageSequence
        for effect in ("bounce", "shake", "zoom"):
            out = Path(self.tmp.name) / f"{effect}.gif"
            animate_gif(self.base, "已读不回", out, effect=effect,
                        frames=6, fps=10)
            im = Image.open(out)
            frames = [f.convert("RGB").tobytes()
                      for f in ImageSequence.Iterator(im)]
            self.assertGreaterEqual(im.n_frames, 2, f"{effect} 应为多帧")
            self.assertGreaterEqual(len(set(frames)), 2,
                                    f"{effect} 应有画面变化")

    def test_animate_unknown_effect_raises(self):
        with self.assertRaises(ValueError):
            animate_gif(self.base, "x", Path(self.tmp.name) / "bad.gif",
                        effect="spin")


class TestLibrary(unittest.TestCase):
    def test_library_loads_and_generic_exists(self):
        lib = load_library()
        ids = [m["id"] for m in lib["moods"]]
        self.assertIn("generic", ids)
        self.assertGreaterEqual(len(lib["styles"]), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
