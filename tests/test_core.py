#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MemeBuddy 核心功能自动化测试。运行: python -m unittest discover tests -v"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from memebuddy import (gen_ideas, match_mood, load_library, extract_theme,
                       render_caption, animate_gif, recommend_effect,
                       compare_effects, main)
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
        out = Path(self.tmp.name) / "out3.png"
        render_caption(self.base, "无语子", out, position="center")
        a = Image.open(self.base).convert("L").tobytes()
        b = Image.open(out).convert("L").tobytes()
        diff = sum(1 for pa, pb in zip(a, b) if pa != pb)
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


class TestAnimatePhase1(unittest.TestCase):
    """阶段一修复验收：黑边/时长守恒/幅度/参数健壮性（评测报告驱动）"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # 带图案底图（zoom/bounce 需要画面差异）
        img = Image.new("RGB", (800, 600), (120, 180, 220))
        d = ImageDraw.Draw(img)
        d.ellipse([100, 100, 700, 500], fill=(250, 190, 90))
        d.rectangle([300, 200, 500, 400], fill=(90, 140, 90))
        self.base = str(Path(self.tmp.name) / "base.png")
        img.save(self.base)

    def tearDown(self):
        self.tmp.cleanup()

    def _frames(self, gif_path):
        from PIL import ImageSequence
        im = Image.open(gif_path)
        return im, [f.convert("RGB") for f in ImageSequence.Iterator(im)]

    def test_shake_no_black_edges_on_white(self):
        """P0-1 验收：纯白底图 shake 后边缘 3px 环带内不得出现黑色填充像素"""
        white = Image.new("RGB", (800, 600), (255, 255, 255))
        wp = str(Path(self.tmp.name) / "white.png")
        white.save(wp)
        out = Path(self.tmp.name) / "shake_white.gif"
        animate_gif(wp, "测试黑边", out, effect="shake", frames=8, fps=10,
                    max_width=320)
        _, frames = self._frames(out)
        for idx, f in enumerate(frames):
            w, h = f.size
            px = f.load()
            for x in range(w):
                for y in list(range(3)) + list(range(h - 3, h)):
                    r, g, b = px[x, y]
                    self.assertFalse(r < 30 and g < 30 and b < 30,
                                     f"第{idx}帧边缘({x},{y})出现黑色像素")
            for y in range(h):
                for x in list(range(3)) + list(range(w - 3, w)):
                    r, g, b = px[x, y]
                    self.assertFalse(r < 30 and g < 30 and b < 30,
                                     f"第{idx}帧边缘({x},{y})出现黑色像素")

    def test_frame_duration_conservation(self):
        """帧合并后总时长必须守恒（12帧@10fps → 1200ms±10）"""
        out = Path(self.tmp.name) / "dur.gif"
        animate_gif(self.base, "节奏", out, effect="bounce", frames=12, fps=10,
                    max_width=320)
        im, _ = self._frames(out)
        from PIL import ImageSequence
        durs = [f.info.get("duration", 0) for f in ImageSequence.Iterator(im)]
        self.assertAlmostEqual(sum(durs), 1200, delta=10,
                               msg=f"总时长失真: {durs}")

    def test_fps_clamped_no_sub20ms(self):
        """P0-3 验收：高 fps 不得产生 <20ms 帧延（浏览器钳制导致变慢）"""
        out = Path(self.tmp.name) / "fast.gif"
        animate_gif(self.base, "快", out, effect="bounce", frames=6, fps=60,
                    max_width=320)
        im, _ = self._frames(out)
        from PIL import ImageSequence
        durs = [f.info.get("duration", 0) for f in ImageSequence.Iterator(im)]
        self.assertGreaterEqual(min(durs), 20, f"存在 <20ms 帧延: {durs}")

    def test_bounce_amplitude_perceptible(self):
        """P0-2 验收：bounce 首帧与过顶帧像素差异率 >0.5%（幅度可感知）"""
        out = Path(self.tmp.name) / "amp.gif"
        animate_gif(self.base, "幅度检查|第二行", out, effect="bounce",
                    frames=12, fps=10, max_width=320)
        im, frames = self._frames(out)
        a = frames[0].tobytes()
        b = frames[min(3, len(frames) - 1)].tobytes()
        diff = sum(1 for x, y in zip(a, b) if x != y) / len(a)
        self.assertGreater(diff, 0.005, f"动效幅度不可感知（差异率 {diff:.4f}）")

    def test_param_validation_friendly(self):
        """P0-3 验收：非法参数一律 ValueError 中文提示，不裸崩"""
        out = Path(self.tmp.name) / "x.gif"
        bad_cases = [
            dict(frames=1), dict(frames=0), dict(frames=61),
            dict(fps=0), dict(fps=-3), dict(fps=61),
            dict(max_width=100), dict(amplitude=0.1), dict(amplitude=3.0),
        ]
        for kw in bad_cases:
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError):
                    animate_gif(self.base, "x", out, **kw)
        with self.assertRaises(FileNotFoundError):
            animate_gif(str(Path(self.tmp.name) / "nope.png"), "x", out)


class TestPhase2(unittest.TestCase):
    """阶段二验收：情绪自动选动画 + 三效果并排预览"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        img = Image.new("RGB", (800, 600), (120, 180, 220))
        d = ImageDraw.Draw(img)
        d.ellipse([100, 100, 700, 500], fill=(250, 190, 90))
        d.rectangle([300, 200, 500, 400], fill=(90, 140, 90))
        self.base = str(Path(self.tmp.name) / "base.png")
        img.save(self.base)

    def tearDown(self):
        self.tmp.cleanup()

    def test_recommend_new_moods(self):
        """新增情绪（愤怒/催促/社恐/狂喜）可匹配且映射到推荐效果"""
        cases = [
            ("气死了气死了", "anger", "shake"),
            ("在吗在吗快点回我消息", "urgent", "shake"),
            ("人多的地方想逃，假装没看见", "social_anxiety", "zoom"),
            ("哈哈哈哈笑死我了", "ecstasy", "bounce"),
            ("什么情况也太震惊了", "shock", "zoom"),
        ]
        for text, mood, effect in cases:
            rec = recommend_effect(text)
            self.assertEqual(rec["mood"], mood, f"{text!r} 情绪匹配错误")
            self.assertEqual(rec["effect"], effect, f"{text!r} 效果推荐错误")
            self.assertFalse(rec["is_default"])
            self.assertTrue(rec["reason"], "推荐理由不应为空")

    def test_recommend_tie_priority(self):
        """同分歧义按'库中靠前者优先'确定性解析（文档化规则）"""
        # '同事朝我走来假装没看见' 同时命中 office(同事) 与 social_anxiety(假装没看见) 各1分
        rec = recommend_effect("同事朝我走来假装没看见")
        self.assertEqual(rec["mood"], "office")  # office 在库中更靠前
        self.assertIn(rec["mood"], ("office", "social_anxiety"))

    def test_recommend_ambiguous_and_unknown(self):
        """模糊/未知文案回落 generic 默认并标记 is_default"""
        rec = recommend_effect("无语")
        self.assertEqual(rec["mood"], "speechless")
        rec = recommend_effect("猫把我的作业吃了")
        self.assertEqual(rec["mood"], "generic")
        self.assertTrue(rec["is_default"])
        self.assertEqual(rec["effect"], "bounce")

    def test_substring_dedup_scoring(self):
        """子串关键词消重：'哈哈哈'与'哈哈哈哈'对同一处文本只计 1 次（D2 修复回归）"""
        # "哈哈哈哈气死我了" 修复前 ecstasy 计 2 分（哈哈哈+哈哈哈哈）压过 anger 1 分
        rec = recommend_effect("哈哈哈哈气死我了")
        self.assertEqual(rec["mood"], "anger",
                         "子串重复计分应被消重，气死(anger) 应与 ecstasy 同分并由库序胜出")

    def test_expanded_keywords_coverage(self):
        """D2 扩充关键词：同义表达/口语/隐喻可命中（非逐字复刻测试样本）"""
        cases = [
            ("气得我把鼠标都摔了", "anger"),
            ("能不能麻利点，火车要开了", "urgent"),
            ("一想到要当众发言，脚趾抠地", "social_anxiety"),
            ("太阳打西边出来了？", "shock"),
            ("老板又画大饼，我先溜了", "office"),
            ("快递三天了还在派送，服气", "speechless"),
            ("涨工资了！！", "ecstasy"),
            ("顶不住了，但你是最棒的，冲", "cheer"),
        ]
        for text, mood in cases:
            rec = recommend_effect(text)
            self.assertEqual(rec["mood"], mood, f"{text!r} 应命中 {mood}")
            self.assertFalse(rec["is_default"])

    def test_no_single_char_keywords(self):
        """词表不应含单字过宽词（误命中防线）"""
        lib = load_library()
        for m in lib["moods"]:
            singles = [k for k in m["keywords"] if len(k) == 1]
            self.assertEqual(singles, [], f"{m['id']} 存在单字关键词: {singles}")

    def test_manual_effect_not_overridden(self):
        """用户手动 --effect 优先：不触发推荐提示、按指定效果执行"""
        import io
        from contextlib import redirect_stdout
        out = Path(self.tmp.name) / "manual.gif"
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["animate", self.base, "--text", "气死了气死了",
                       "--out", str(out), "--effect", "zoom",
                       "--frames", "4", "--fps", "10", "--max-width", "320"])
        self.assertEqual(rc, 0)
        self.assertTrue(out.exists())
        self.assertNotIn("自动推荐", buf.getvalue(),
                         "手动指定效果时不应出现推荐流程")
        # auto 模式对照：同文案应命中 anger 并输出推荐信息
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            rc = main(["animate", self.base, "--text", "气死了气死了",
                       "--out", str(Path(self.tmp.name) / "auto.gif"),
                       "--frames", "4", "--fps", "10", "--max-width", "320"])
        self.assertEqual(rc, 0)
        self.assertIn("自动推荐", buf2.getvalue())
        self.assertIn("愤怒", buf2.getvalue())

    def test_compare_generates_three_independent(self):
        """三效果独立生成：文件名带效果标签、互不覆盖、规格一致"""
        prefix = Path(self.tmp.name) / "pv"
        results = compare_effects(self.base, "无语子|我不想说话", prefix,
                                  frames=8, fps=10, max_width=320)
        self.assertEqual(len(results), 3)
        paths = [Path(r["path"]) for r in results]
        self.assertEqual(len({p.name for p in paths}), 3, "文件名应互不相同")
        for r, p in zip(results, paths):
            self.assertTrue(r["ok"], f"{r['effect']} 应生成成功: {r['error']}")
            self.assertTrue(p.exists())
            self.assertGreater(r["size_kb"], 0)
        self.assertTrue(Path(str(prefix) + "_对比图.png").exists(),
                        "应产出对比图")
        # 同底图同文案 → 三者尺寸一致、总时长一致
        from PIL import ImageSequence
        sizes, durs = set(), set()
        for p in paths:
            im = Image.open(p)
            sizes.add(im.size)
            durs.add(sum(f.info.get("duration", 0)
                         for f in ImageSequence.Iterator(im)))
        self.assertEqual(len(sizes), 1, "三效果输出尺寸应一致")
        self.assertEqual(len(durs), 1, "三效果总时长应一致")

    def test_compare_partial_failure(self):
        """单个效果失败不中断其余，失败项如实标记"""
        from unittest import mock
        import memebuddy
        real = memebuddy.animate_gif

        def fake(*a, **kw):
            if kw.get("effect") == "zoom":
                raise RuntimeError("模拟 zoom 失败")
            return real(*a, **kw)

        prefix = Path(self.tmp.name) / "pf"
        with mock.patch("memebuddy.animate_gif", side_effect=fake):
            results = compare_effects(self.base, "测试", prefix,
                                      frames=6, fps=10, max_width=320)
        by_eff = {r["effect"]: r for r in results}
        self.assertFalse(by_eff["zoom"]["ok"])
        self.assertIn("模拟 zoom 失败", by_eff["zoom"]["error"])
        self.assertTrue(by_eff["bounce"]["ok"])
        self.assertTrue(by_eff["shake"]["ok"])
        self.assertTrue(Path(str(prefix) + "_bounce.gif").exists())
        self.assertTrue(Path(str(prefix) + "_shake.gif").exists())
        self.assertFalse(Path(str(prefix) + "_zoom.gif").exists())

    def test_animate_never_silently_overwrites(self):
        """已存在的输出文件不被静默覆盖（阶段二验收缺陷修复回归）"""
        out = Path(self.tmp.name) / "exists.gif"
        out.write_text("PRE_EXISTING_MARKER", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            animate_gif(self.base, "覆盖测试", out, frames=4, fps=10)
        self.assertEqual(out.read_text(encoding="utf-8"), "PRE_EXISTING_MARKER",
                         "已存在文件内容必须原样保留")

    def test_compare_existing_target_reports_failure_not_overwrite(self):
        """compare 中某效果目标已存在 → 该效果失败并明确报告，其余效果正常"""
        pre = Path(self.tmp.name) / "pf_shake.gif"
        pre.write_bytes(b"GIF89a-pre-existing")
        results = compare_effects(self.base, "测试", Path(self.tmp.name) / "pf",
                                  frames=6, fps=10, max_width=320)
        by_eff = {r["effect"]: r for r in results}
        self.assertFalse(by_eff["shake"]["ok"])
        self.assertIn("已存在", by_eff["shake"]["error"])
        self.assertEqual(pre.read_bytes(), b"GIF89a-pre-existing", "已有文件被改动")
        self.assertTrue(by_eff["bounce"]["ok"])
        self.assertTrue(by_eff["zoom"]["ok"])


class TestLibrary(unittest.TestCase):
    def test_library_loads_and_generic_exists(self):
        lib = load_library()
        ids = [m["id"] for m in lib["moods"]]
        self.assertIn("generic", ids)
        self.assertGreaterEqual(len(lib["styles"]), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
