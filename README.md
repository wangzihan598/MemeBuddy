# MemeBuddy 表情包生成助手（WorkBuddy 版）

MemeBuddy 是一个中文表情包生成助手：输入一句话、一个情绪或一个网络梗，它负责理解语境、提出创意、生成画面并精确叠加中文配文，产出可直接使用的表情包图片。

当前版本已迁移到 **WorkBuddy 平台**运行（原 DeepSeek Harness 插件方案已废弃）。

## 工作原理（两段式，解决中文乱码问题）

```
用户输入 ──> ① 意图识别 + 创意生成（memebuddy.py idea）
                │  输出：画面构想（无文字）、配文、适用场景
                ▼
         ② AI 生成底图（WorkBuddy ImageGen，提示词明确要求"画面不含任何文字"）
                │
                ▼
         ③ 本地精确叠字（memebuddy.py render，微软雅黑描边字）
                │
                ▼
         output/ 成品表情包
```

为什么不让 AI 直接画字？生成式模型渲染中文字符极易出现乱码、错别字和布局溢出。MemeBuddy 让 AI 只画画面，配文由本地字体引擎渲染，**保证中文 100% 清晰准确**。

## 安装

```bash
git clone https://github.com/wangzihan598/MemeBuddy.git
cd MemeBuddy
python -m pip install -r requirements.txt
```

运行环境：Python 3.10+；Windows（配文渲染依赖系统自带微软雅黑/黑体字体，本仓库不内置字体文件）。macOS/Linux 需自行修改 `memebuddy.py` 中的 `FONT_CANDIDATES` 为系统内可用中文字体路径。

## 在 WorkBuddy 中使用

已注册为用户级 Skill（`~/.workbuddy/skills/memebuddy/`）。在对话中说出触发词即可：

- "帮我做个表情包：今天不想上班"
- "用 MemeBuddy 生成一张'对方已读不回'的梗图"
- "把刚才那张的配文改短一点"（迭代修改）

也可以直接命令行使用：

```bash
# 1. 生成创意方案（含画图提示词）
python memebuddy.py idea "今天不想上班" -n 3 --save

# 2. 用 WorkBuddy ImageGen 按 image_prompt 生成底图（不含文字）

# 3. 叠加配文
python memebuddy.py render base.png --text "这班是一秒都上不下去了" --out output/meme1.png
#    多行配文用 | 分隔；--position top/center/bottom；--band 加黑底条
```

## 功能

- **意图识别**：内置 12 类情绪库（不想上班/已读不回/震惊/无语/鼓励/反讽/职场/愤怒/催促/社恐/狂喜/通用），212+ 关键词（含口语、网络用语、隐喻），最长匹配消重计数，子串关键词不重复计分；无法可靠判断时回落 generic 兜底，不强行猜测
- **创意生成**：每个输入产出 n 个方案，含场景描述、画面构想、配文、适用场景、可直接使用的画图提示词
- **成品渲染**：白字黑描边经典表情包样式，自动换行、自动缩放字号、三种文字位置、可选黑底条
- **动图（GIF）**：bounce/shake/zoom 三种本地动画，按情绪自动推荐效果，零积分零新依赖，聊天可用体积
- **三效果预览**：`compare` 命令同底图同文案一次产出三种效果 + 对比图
- **迭代修改**：改配文（重跑 render）、换画风（`--style`，5 种画风库）、保留构图（仅改 `--text` 重渲染）

## 动图（GIF）

同一套中文描边字渲染管线逐帧动画化，配文清晰度与静态图一致。**可直接复制运行**（任意外部委图片均可）：

```bash
python memebuddy.py animate 底图.png --text "已读不回|是成年人最后的体面" --out output/动图.gif --effect bounce
```

### 三种效果与适用场景

| 效果 | 动画内容 | 适用场景 | 适用性说明 |
| --- | --- | --- | --- |
| `bounce` | 配文垂直弹跳 | 无语、调侃、轻度吐槽等多数场景 | 通用；纯色底图下仅文字动，仍可感知 |
| `shake` | 整图小幅抖动 | 愤怒、催促、崩溃、抓狂 | 感知最强；任意底图均适用 |
| `zoom` | 整图缩放脉冲 | 震惊、强调、心跳感 | **纯色/极简底图无效**（放大后无像素变化），需有内容的画面 |

### 情绪自动推荐（默认开启）

`animate` 默认 `--effect auto`：按 `templates/moods.json` 中的关键词识别情绪，读取该情绪的 `suggested_effect` / `effect_reason` / `suggested_amplitude` 字段推荐效果，并在输出中显示识别结果、推荐理由；未命中任何情绪时回落默认 bounce 并明确提示。**手动指定 `--effect` 时永远优先于自动推荐**。

当前 12 类情绪映射（同分时库中靠前者优先）：

| 情绪 | 推荐效果 | 情绪 | 推荐效果 |
| --- | --- | --- | --- |
| 不想上班/摸鱼 | bounce | 职场交流 | shake |
| 已读不回/被冷落 | bounce | 愤怒/炸毛 | shake |
| 震惊/吃瓜 | zoom（幅度 1.3） | 催促/着急 | shake |
| 无奈/无语 | bounce | 社恐/尴尬 | zoom |
| 鼓励/打气 | bounce（幅度 1.2） | 狂喜/乐疯 | bounce（幅度 1.4） |
| 反讽/阴阳怪气 | bounce | 通用兜底 | bounce（默认） |

### 三效果并排预览

```bash
python memebuddy.py compare 底图.png --text "已读不回|是成年人最后的体面" --out-prefix output/preview
```

一次生成 `preview_bounce.gif`、`preview_shake.gif`、`preview_zoom.gif`（同底图/同文案/同规格，文件名带效果标签互不覆盖）和 `preview_对比图.png`（各效果 3 帧抽样拼图，标注效果名与体积）。单个效果生成失败不影响其余结果。命令行环境无动态 GUI，**动态对比请分别打开三个 GIF**，对比图用于快速初选。

### 参数说明

| 参数 | 默认值 | 含义与限制 |
| --- | --- | --- |
| `--effect` | `auto` | `auto`=按情绪自动推荐（默认）/ bounce / shake / zoom；手动指定优先 |
| `--frames` | 16 | 帧数，**2–60** |
| `--fps` | 12 | 帧率，**1–60**；GIF 帧延最小 20ms，fps>50 会被播放器钳制，建议 8–25 |
| `--max-width` | 480 | 降采样宽度（控制体积），**≥160** |
| `--amplitude` | 1.0（auto 模式采用情绪推荐值） | 动效幅度倍率，**0.2–2.0** |
| `--position` | `bottom` | 文字位置 top/center/bottom（同 render） |
| `--band` | 关 | 文字区加半透明黑底条（同 render） |
| `--font-scale` | 0.62 | 字号缩放系数（同 render；动图默认较小以控制体积） |

### 体积参考（实测）

| 档位 | 体积 | 适用 |
| --- | --- | --- |
| `--max-width 320` | ≈0.5–1 MB | 微信/QQ 表情推荐 |
| `--max-width 480` | ≈1–2 MB | 本地高清留存 |

### 常见错误与排查

| 现象 | 原因与处理 |
| --- | --- |
| `错误：frames 必须在 2–60 之间` | 参数超出有效范围，按提示调整 |
| `错误：底图文件不存在` | 检查路径（含中文路径请用引号包裹） |
| 动图"看不出在动" | 纯色底图换 zoom 无效→改 shake；或加大 `--amplitude`（如 1.5） |
| 文件太大 | 减小 `--max-width`（320 档约减半）或减少 `--frames` |
| 播放速度不对 | fps>50 会被播放器钳制，改用 8–25 |

## 目录结构

```
memebuddy/
├── README.md          本文件
├── SKILL.md           技能入口说明（仓库版路径已泛化，本机安装时替换为实际路径）
├── memebuddy.py       核心引擎（创意生成 + 中文渲染）
├── requirements.txt   依赖声明（仅 Pillow）
├── templates/
│   └── moods.json     情绪库 + 画风库（可自由扩展，改 JSON 即可，无需动代码）
├── examples/          示例成品（由本工具 + WorkBuddy ImageGen 生成）
├── output/            生成的成品与创意记录（已 gitignore）
└── tests/
    └── test_core.py   自动化测试（python -m unittest discover tests -v）
```

示例成品见 [`examples/`](examples/)——"不想上班"与"已读不回"两张均为本流水线实际生成：AI 底图 + 本地中文叠字。

## 能力边界（如实说明）

| 能力 | 状态 |
| --- | --- |
| 创意/配文生成（本地引擎） | ✅ 已实现，自动化测试通过 |
| 中文配文渲染 | ✅ 已实现，Pillow + 微软雅黑，测试通过 |
| AI 生成底图 | ✅ 已实测可用（WorkBuddy 内置 ImageGen，消耗平台积分约 5-10/张）；积分不足或未接通时可退化为本地占位底图继续渲染 |
| 迭代修改（改字/换画风/保留构图） | ✅ 已实现（重跑对应命令） |
| 动图 GIF（bounce/shake/zoom） | ✅ 已实现，纯本地零积分；zoom 对纯色底图无效（如实说明） |
| 情绪自动推荐 | ✅ 40 条独立文案实测明确命中 32/36 ≈ 89%（含口语/隐喻扩充与子串消重）；模糊文案回落 generic，不强行猜测 |
| AI 语义模型 | ⏸ 评估后**暂不引入**（2026-10）：优化后规则已满足日常使用；本地轻量语义模型需 25 个依赖包（torch 等）+ 数百 MB 权重，云 LLM 需联网与付费额度——代价与收益不成比例。未来若语义缺口集中且关键词无法覆盖，可评估 opt-in 本地小模型 |
| 开源发布 | ✅ 已发布：[github.com/wangzihan598/MemeBuddy](https://github.com/wangzihan598/MemeBuddy)（MIT） |

扩展方式：往 `templates/moods.json` 里加情绪条目或画风条目即可，无需改代码。

## License

MIT
