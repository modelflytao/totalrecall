# TotalRecall

从你和 AI 工具的会话里学习。每当一个会话结束,TotalRecall 在本地分析 transcript,抽取**协作摩擦**
(反复纠正、误解意图、返工、工具报错……),持续维护一份活的 `~/.totalrecall/insights.md`;
并能把反复出现的摩擦闭环成对你 `CLAUDE.md` 的规则改进。

支持 **Claude Code** 与 **Codex(OpenAI Codex CLI)** 两种会话来源。

---

## 目录

- [安装](#安装)
- [快速开始](#快速开始)
- [工作原理](#工作原理)
- [命令参考](#命令参考)
- [配置](#配置-totalrecallconfigtoml)
- [Phase 1 — 洞察](#phase-1--洞察)
- [Phase 2 — 规则闭环](#phase-2--规则闭环)
- [多工具:Codex](#多工具codex)
- [存储布局](#存储布局)
- [停用 / 卸载](#停用--卸载)
- [实现说明](#实现说明)

---

## 安装

需要 Python ≥ 3.11,以及已登录的 `claude` CLI(分析靠 headless `claude -p`,复用你现有的订阅/授权)。

```bash
cd /path/to/totalrecall
pip install -e .
totalrecall init      # 创建 ~/.totalrecall/ 并把 SessionEnd hook 合并进 ~/.claude/settings.json
```

`init` 是**幂等**的:不会覆盖你已有的 hook,会先备份 `~/.claude/settings.json`。

---

## 快速开始

1. `totalrecall init` —— 启用后,**每次 Claude Code 会话结束自动分析**,无需手动操作。
2. 用一阵子后,打开 `~/.totalrecall/insights.md` 看你的协作摩擦档案。
3. `totalrecall status` —— 看已分析会话数 / 模式数。
4. (Phase 2)`totalrecall propose` → 看 `~/.totalrecall/proposals.md` → `totalrecall apply <id>` 把规则写进 CLAUDE.md。

想立刻分析(而不等下次会话结束):`totalrecall reconcile && totalrecall worker`。

---

## 工作原理

```
会话结束
  │  Claude Code: SessionEnd hook(原生);Codex: 无 hook → 靠 reconcile 兜底
  ▼
totalrecall hook  ── 把 transcript 路径写入队列, 立即返回(非阻塞, 失败静默)
  │  并 detached 拉起 worker
  ▼
totalrecall worker (单实例锁, crash-safe 队列)
  ├─ reconcile: 扫各来源目录, 把"比 ledger 新且已静置"的会话补入队
  ├─ adapters.for_path(p).parse(p) → NormalizedSession(工具无关)
  │     · Claude Code: ~/.claude/projects/.../<sid>.jsonl
  │     · Codex:       ~/.codex/sessions/.../rollout-*.jsonl
  ├─ 确定性抽取 A 类信号(工具报错 / 文件返工 churn / 中断 …)
  ├─ claude -p 语义分析 B 类摩擦 → 结构化 Finding(JSON)
  ├─ merge: 并入持久"模式库"(去重 / 累加 occurrences / 强化)
  └─ 渲染 insights.md(聚焦反复出现的摩擦, 折叠一次性长尾)
```

- **确定性、可单测的活**(解析、事件、队列、合并、渲染)用 Python;**语义判断**用 Claude。
- **幂等 & crash-safe**:重跑不重复;worker 被杀(休眠/崩溃)后从断点续, 无大批返工。
- **自吞排除**:分析用的 `claude -p` 会话本身被两道排除, 不会被递归分析。

---

## 命令参考

| 命令 | 作用 |
|------|------|
| `totalrecall init` | 创建 `~/.totalrecall/`、写默认 `config.toml`、合并安装 SessionEnd hook(幂等、带备份) |
| `totalrecall status` | 显示已分析会话数、模式数、待重试数 |
| `totalrecall worker` | 排空队列:reconcile + 逐个分析(单实例锁、crash-safe、退出前 drain-loop) |
| `totalrecall reconcile` | 扫各启用来源目录,把"比 ledger 新且已静置"的会话补入队(堵 hook 漏触发) |
| `totalrecall ingest <path>` | 分析单个 transcript(持锁,供手动/调试) |
| `totalrecall retry` | 重试 ledger 中标记 `pending`(分析失败)的会话 |
| `totalrecall synth` | 用强模型合并近似重复的模式,重写 insights 叙事 |
| `totalrecall hook` | SessionEnd hook 入口(读 stdin 的 hook 负载;由 Claude Code 调用,一般不手动跑) |
| `totalrecall propose` | (Phase 2)为 top 反复摩擦起草 CLAUDE.md 规则 → `proposals.md` |
| `totalrecall apply <id...>` | (Phase 2)把指定提案写进受管 rules 文件 + CLAUDE.md `@import`,并记 `applied_at` |
| `totalrecall reject <id...>` | (Phase 2)拒绝提案(proposer 不再重提) |
| `totalrecall proposals` | (Phase 2)列出所有提案及状态 |

---

## 配置 `~/.totalrecall/config.toml`

```toml
[models]
extract = "claude-sonnet-4-6"            # 单会话语义分析(质量优先);批量回填可临时改 Haiku 省钱
synth   = "claude-sonnet-4-6"            # 周期/手动综合(可升 claude-opus-4-8)

[limits]
max_input_tokens       = 12000           # 单次分析喂给模型的最大 token(超长会话按"事件附近优先"截断)
synth_every_n_sessions = 25              # 每 N 次分析自动跑一次 synth(0 关闭)
catalog_topk           = 80              # 喂给分析 skill 的精简模式目录条数(applied 模式必被钉入)

[sources]
claude_code = true                       # 扫 ~/.claude/projects
codex       = true                       # 扫 ~/.codex/sessions(Codex 支持)

[privacy]
store_snippets = false                   # 证据默认只存引用(session_id + 轮次 + hash),不存全文

[phase2]
propose_top_n       = 10                 # 一次 propose 最多起草几条
propose_min_occ     = 3                  # 候选模式的最少出现次数
resolved_after_days = 14                 # 应用规则后多少天无复发 → 判定 resolved
rules_file = "~/.claude/totalrecall-rules.md"   # 受管规则文件
claude_md  = "~/.claude/CLAUDE.md"              # 注入 @import 的目标
```

---

## Phase 1 — 洞察

启用后自动累积。`~/.totalrecall/insights.md` 结构:

- **🔥 当前最该处理的摩擦**(按 strength = 频次 × 时近衰减 × 严重度 排序)
- **📈 趋势**(活跃 / 消退中)
- **🔁 反复出现的摩擦**(≥2 个不同会话,按类别;一次性长尾折叠成计数)
- **🧰 给 Phase 2 的候选改进**(每条反复摩擦的可落地建议)

每条摩擦可溯源到具体会话证据(`tool=claude-code` 或 `tool=codex`)。

> 提示:批量回填历史会话后,如果 worker 期间反复扫到同一个**正在进行**的会话,计数可能被抬高。
> 跑一次 `totalrecall synth` 合并近似模式即可清理。

---

## Phase 2 — 规则闭环

把反复摩擦变成 CLAUDE.md 规则,并验证规则是否真的消除了摩擦。**全程手动、可审、可逆。**

```bash
totalrecall propose            # 为 top 反复摩擦起草规则 → 写 ~/.totalrecall/proposals.md
#   打开 proposals.md 审阅草稿
totalrecall apply p-<slug>     # 批准并应用(可一次多个 id)
totalrecall reject p-<slug>    # 拒绝
totalrecall proposals          # 查看所有提案状态
```

**apply 做了什么(安全):**
- 规则写进**独立受管文件** `~/.claude/totalrecall-rules.md`(按 `<!-- pattern: id -->` 标记,幂等)。
- 在 `~/.claude/CLAUDE.md` 末尾加**一行** `@totalrecall-rules.md`(首次注入前先备份)。
- 你的 CLAUDE.md 正文不被改动;删文件 + 删那行 import 即完全回退。
- 在该 Pattern 记 `applied_at`。

**闭环验证**(随后续会话自动发生,显示在 insights.md 的"🔧 Phase 2 — 已应用规则的效果"):
- 应用后 `resolved_after_days` 天内**无复发** → ✅ **已解决**
- 应用后**仍复发** → ⚠️ **修复无效**(提示这条规则没起作用,换个写法)
- 期间 → ⏳ **已应用待验证**

---

## 多工具:Codex

把 `~/.totalrecall/config.toml` 的 `[sources]` 下 `codex = true` 打开,即可一并学习
Codex CLI 会话(`~/.codex/sessions/.../rollout-*.jsonl`)。

Codex 没有 SessionEnd hook,所以它的会话靠 **reconcile** 拾取——下次任意 `totalrecall worker`
运行时(某个 Claude Code 会话结束后,或手动)被扫到。要立刻分析 Codex 历史:

```bash
totalrecall reconcile
totalrecall worker
```

Codex 会话的摩擦进入**同一个模式库**,在 insights.md 里以 `tool=codex` 证据呈现,与 Claude Code 并轨。

---

## 存储布局

```
~/.totalrecall/
  config.toml          # 配置
  queue/               # hook/reconcile 入队的 transcript 路径(*.job)
  ledger.json          # 已处理台账(幂等/增量:session_id → hash+path;含 pending)
  patterns/            # 模式库,一个模式一个 JSON
    index.json
    <slug>.json
  insights.md          # 唯一面向你的洞察出口
  proposals.json       # (Phase 2)提案工作流状态
  proposals.md         # (Phase 2)提案人读视图
  analysis/            # 分析用 claude -p 会话的 cwd(用于自吞排除)
  log                  # worker / hook 日志

~/.claude/
  settings.json        # 含 SessionEnd hook(init 合并;.bak-totalrecall 为备份)
  totalrecall-rules.md # (Phase 2)受管规则文件
  CLAUDE.md            # (Phase 2)被加一行 @totalrecall-rules.md
```

---

## 停用 / 卸载

- **暂停学习**:从 `~/.claude/settings.json` 删掉 SessionEnd 那条 hook(或用 `settings.json.bak-totalrecall` 恢复)。
- **撤销已应用的规则**:删 `~/.claude/totalrecall-rules.md` + 删 CLAUDE.md 里的 `@totalrecall-rules.md` 那行。
- **清空数据**:删除 `~/.totalrecall/`(模式库 / 洞察 / 台账)。
- **从今往后增量**(不回填历史):把已有历史会话标为 seen 后再启用 hook(避免一次性批量分析整段历史)。

---

## 实现说明

- 纯 Python 薄 CLI + 一个 `totalrecall-analyze` 分析 skill(经 `claude -p` 调用)+ 一个 `totalrecall-propose` 提案 skill。
- 确定性层全部有 pytest 单测(适配器、台账、队列锁、合并、strength、渲染、闭环 verifier、CLI);真实 `claude -p` 仅在分析/提案两处,测试中以注入的 fake runner 替代。
- 适配器可插拔:`adapters/base.py` 定义协议,`claude_code.py` / `codex.py` 各实现,`adapters.for_path()` 按来源目录路由。新增工具 = 加一个适配器。
- 健壮性:非阻塞 hook、单实例 worker 锁、crash-safe 队列(逐个 claim/complete)、reconcile 跳过进行中会话、prompt 截断、CLAUDE.md 写入幂等+备份。

运行测试:`python -m pytest -q`
