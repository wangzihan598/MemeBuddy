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

- **意图识别**：内置 8 类情绪库（不想上班/已读不回/震惊/无语/鼓励/反讽/职场/通用），关键词匹配 + generic 兜底
- **创意生成**：每个输入产出 n 个方案，含场景描述、画面构想、配文、适用场景、可直接使用的画图提示词
- **成品渲染**：白字黑描边经典表情包样式，自动换行、自动缩放字号、三种文字位置、可选黑底条
- **迭代修改**：改配文（重跑 render）、换画风（`--style`，5 种画风库）、保留构图（仅改 `--text` 重渲染）

## 目录结构

```
memebuddy/
├── README.md          本文件
├── SKILL.md           技能入口说明（与用户级 Skill 同步）
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
| 开源发布 | 📋 代码结构已就绪（MIT LICENSE、.gitignore），发布需作者确认 |

扩展方式：往 `templates/moods.json` 里加情绪条目或画风条目即可，无需改代码。

## License

MIT
