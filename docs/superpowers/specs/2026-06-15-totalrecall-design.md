# TotalRecall — 设计文档 (Phase 1)

_日期: 2026-06-15 · 状态: 已通过 brainstorming, 待用户复核 → writing-plans_

---

## 1. 概述

**TotalRecall** 读取本机多个 AI 工具(Claude Code、Codex、OpenCode……)的本地会话,
分析对话以理解"我如何与 AI 协作",并**持续把学到的东西沉淀下来**。

参考产品 **Paxel**(Y Combinator,2026-06-06 发布):本地分析 Claude/Codex/Cursor 会话,
产出一次性的"builder report",在 steering/execution/engineering/product instinct/planning
五维上打分并给出 archetype。

**与 Paxel 的关键差异 / 本项目的novel之处:不止于一次性画像,而是闭环。**
Paxel 告诉你"你是谁";TotalRecall 持续观察 → 沉淀 → 最终(Phase 2)把洞察反哺成对你自己
skills/agents 的改进。

### 分阶段

- **Phase 1(本文档范围)**:把"理解你的交互摩擦"做扎实,产出可信、可累积的洞察。
- **Phase 2(本文档只留接缝,不实现)**:在洞察之上叠加 skill/agent 的(半)自动迭代。

---

## 2. 核心决策摘要

经 brainstorming 确认的决策:

| 维度 | 决策 |
|------|------|
| 核心目标 | **先洞察,后迭代**(分阶段) |
| Phase 1 洞察焦点 | **摩擦 / 失败模式**(反复纠正、返工、误解意图、多轮拉扯) |
| 隐私 / 算力 | **可用云端 LLM(Claude)** 做分析 |
| 运行方式 | **会话结束即时增量**,hook 驱动 → 维护持久"模式库" |
| 洞察出口 | **唯一出口:一份持续更新的 `insights.md`**(不主动提醒、不做问答) |
| 首个数据源 | **Claude Code 优先**(原生 hook + 主力工具);Codex/OpenCode 后续接 |
| 架构 | **C:混合** — 薄 CLI 管摄取/状态,skill 管分析;适配器为多工具就绪 |
| CLI 语言 | **Python** |

---

## 3. 架构

三层:

```
┌─ 触发层 ──────────────────────────────────────────────┐
│ Claude Code SessionEnd/Stop hook (settings.json)      │
│   → 把 transcript 路径写入队列目录, 立刻返回(非阻塞)   │
│ [后续] 其他工具: CLI 的 scan 模式检测新会话文件         │
└───────────────────────────────────────────────────────┘
                      │ enqueue
                      ▼
┌─ CLI 核心 (薄 CLI, 确定性管线; Python) ────────────────┐
│ worker  : 排空队列, 串行处理                            │
│ adapter : 原始 session 文件 → NormalizedSession         │
│ ledger  : 已处理记录 → 幂等 + 增量                      │
│ orchestr: 对(增量)调起分析 skill (headless `claude -p`) │
│ merger  : 发现 JSON → 模式库; 重生成 insights.md        │
└───────────────────────────────────────────────────────┘
                      │ 调用                ▲ 写
                      ▼                     │
┌─ 分析 skill (LLM 判断层) ─────┐   ┌─ 状态 (~/.totalrecall/) ─┐
│ totalrecall-analyze           │   │ queue/        队列          │
│ 输入: NormalizedSession(增量) │   │ ledger.json   台账          │
│ 输出: 结构化发现 JSON          │   │ patterns/*.json 模式库      │
│ (摩擦信号 + 证据 + 模式标签)   │   │ patterns/index.json         │
└───────────────────────────────┘   │ insights.md   ← 唯一出口    │
                                     │ config.toml   配置          │
                                     │ log           日志          │
                                     └─────────────────────────────┘
```

**职责边界**:
- 确定性、便宜、可单测的活(解析、事件派生、台账、合并、渲染)→ **CLI 核心(Python)**。
- 需要语义判断的活(理解对话里的误解/纠正/挫败)→ **分析 skill(Claude)**。

---

## 4. 组件详解

### 4.1 触发层

- **Claude Code**:在 `~/.claude/settings.json` 配 `SessionEnd`(必要时加 `Stop`)hook。
  hook 命令只做一件事:把本次 transcript 路径(hook 在 stdin 提供 `transcript_path`/`session_id`/`cwd`)
  追加进 `~/.totalrecall/queue/`,然后**立刻返回**。失败静默。
- **其他工具(Phase 1 不实现,留接口)**:`totalrecall scan` 轮询各工具 session 目录,
  把新增/变长的文件入队。可由用户手动或后续调度触发。

### 4.2 worker

- 排空 `queue/`,**单 worker 串行**处理,持有 ledger/index 文件锁,避免并发写坏模式文件。
- 由 hook detached 拉起一个短命进程,或常驻;Phase 1 用"hook 入队 + 拉起一次性 worker"。

### 4.3 adapter(适配器)

- 接口:`(raw_session_file) -> NormalizedSession`。每个工具一个实现。
- **Phase 1 只实现 Claude Code adapter**;接口签名定好,Codex/OpenCode 后续插入。
- Claude Code 事实:transcript = `~/.claude/projects/<编码路径>/<session-id>.jsonl`,
  逐行 JSON,`type` 字段区分记录(`last-prompt`/`mode`/`permission-mode`/`attachment`/
  `file-history-snapshot`/ user / assistant / tool 等),含 `timestamp`/`cwd`/`gitBranch`/
  `permissionMode`/工具调用/文件快照。
- 适配器**确定性地**算出 `events` + `stats`(见 §5 A 类),无法解析的行跳过并记数。

### 4.4 归一化会话 schema

```
NormalizedSession {
  tool, session_id, cwd, git_branch, started_at, ended_at
  turns:  [ Turn { idx, role:user|assistant|tool, ts, text?, tool_name?, tool_status? } ]
  events: [ Event { kind:edit|revert|permission_denied|tool_error|interrupt, ts, ref } ]
  stats:  { n_turns, duration_s, n_tool_errors, n_edits, n_reverts, ... }
}
```

### 4.5 orchestrator(编排)

- 对 NormalizedSession 的**增量**(自 ledger 偏移起的新轮次)+ events/stats,
  用 headless `claude -p` 调起 `totalrecall-analyze` skill。
- 复用用户现有 Claude Code 授权/订阅,无需单独 API key。
- 强制 LLM 输出符合发现 JSON schema(schema 不符则重试)。

### 4.6 merger(合并)

- 发现 JSON → 模式库:按 slug + 语义相似度匹配已有模式(LLM 给建议 slug,merger 协调);
  命中则强化(occurrences++、更新 last_seen、追加去重证据),否则新建。
- 重算 strength;轻量刷新 `insights.md`。

### 4.7 分析 skill `totalrecall-analyze`

- 输入:一个 NormalizedSession(或其增量)。
- 任务:检出 §5 B 类语义摩擦信号。
- 输出:结构化发现 JSON,每条含 `category` / `description` / `evidence(turn_refs)` /
  建议 `slug` / 可选 `phase2_hint` / 严重度。

---

## 5. 摩擦信号分类

尽量把信号交给确定性代码,只把语义交给 LLM。

### A. 元数据派生(CLI 适配器直接算,几乎不花 token)
- **返工/抖动 churn**:`file-history-snapshot` 显示同一文件反复改 / "改完很快回滚"(edit→revert→re-edit)。
- **权限摩擦**:`permission-mode` 变更 / 被拒工具调用。
- **工具报错**:tool_result 带 error → 失败、重试。
- **重述循环**:连续多个短 user 轮次 / `last-prompt` 抖动。
- **轮次时延 / 会话长度**:任务磨了很多轮或很久。
- **中断/打断**:abort、Stop 事件。

### B. LLM 语义派生(分析 skill 判断)
- **误解意图**:assistant 做了 X,用户纠正"我要的是 Y"。
- **反复纠正**:跨轮次/跨会话重复同一约束(例:又一次"用 PowerShell 不要 bash")。← Phase 2 金矿
- **澄清缺口**:动手前要来回好多轮才说清。
- **既定规则被违反**:AI 反复破坏说过的偏好 → "该补一条 skill/CLAUDE.md 规则"候选。
- **挫败标记**:语气 / 明确的"又错了"。

两类信号最终一起进模式库。

---

## 6. 数据模型

### 6.1 Pattern(模式库条目,`patterns/<slug>.json` + `patterns/index.json`)

```
Pattern {
  id:          稳定 slug,如 "powershell-vs-bash-correction"
  title:       人类可读短标签
  category:    rework | misunderstood-intent | repeated-correction | permission |
               tool-error | clarification-gap | rule-violation | ...
  source:      metadata | llm | both
  description: 这个摩擦是什么
  first_seen, last_seen, occurrences
  strength:    频次 × 时近衰减 × 严重度   ← 排序 & Phase 2 优先级
  evidence:    [ { session_id, tool, turn_refs, ts, snippet_hash } ]   ← 只存引用, 不存全文
  status:      active | fading | resolved
  phase2_hint: 可选 — 建议补救(如 "加 CLAUDE.md 规则:默认用 PowerShell")
}
```

设计决定:
- **存储**:JSON 文件(可读、可 git diff、可手改),不用 SQLite(MVP 量级用不上)。
- **去重/合并**:slug + 语义相似度;周期综合再合并近似模式,防爆炸。
- **证据只存引用**(session_id + turn_refs + snippet_hash),不存全文 → 状态小、更隐私。
- **strength** 驱动排序与 Phase 2 优先级;久未出现 `fading`,修复后停止复发 `resolved`。

### 6.2 `insights.md`(唯一面向用户的出口)

Merger 轻量刷新,周期综合时由强模型重写叙事。结构:

```
# TotalRecall — 你与 AI 的协作摩擦档案
_最后更新 <ts> · 已分析 N 个会话 · 跨 M 个项目_

## 🔥 当前最该处理的摩擦 (按 strength)
1. **<标题>** — <类别> · 出现 <n> 次 · 最近 <日期>
   <一行描述>   证据: <refs>   建议(Phase 2): <phase2_hint>

## 📈 趋势   (本周新增/加剧 · 正在消退/已解决)

## 🗂 全部模式 (按类别分组)

## 🧰 给 Phase 2 的候选改进 (skill / agent / CLAUDE.md)
```

**"给 Phase 2 的候选改进"** 是桥:Phase 1 即产出可落地补救,Phase 1 自身就有用,Phase 2 一来闭环已预热。

---

## 7. 数据流

**单次(会话结束):**
```
会话结束 → hook 写队列(立即返回) → worker 取出 → adapter 归一化
→ ledger 判定"自偏移 X 起的新轮次" → orchestrator 对增量跑分析 skill
→ 发现 JSON → merger 更新模式库 → 重生成 insights.md
```

**周期综合(由 worker 计数,每 N 个会话自动触发;或手动 `totalrecall synth`。不引入调度器):**
```
强模型读全模式库 → 合并近似模式 → 重算 strength → 重写 insights.md 叙事 + Phase 2 建议
```

---

## 8. 成本 / 性能分层

- **单会话抽取(每次结束)**:**Haiku**。输入 = 增量轮次 + events/stats,提示词精简;
  不喂原始全文;超长会话按"事件附近优先"采样截断;设最大输入 token 上限。
- **周期综合**:**Sonnet/Opus**。合并、重算、重写叙事。质量开销摊薄到这里。
- 模型/阈值/上限/开关均在 `config.toml` 可配。

---

## 9. 幂等 / 容错 / 并发

- **幂等 & 增量**:ledger 按 `session_id → {content_hash, last_offset, last_ts}`。
  hash 未变跳过;变长只分析增量;证据按 snippet_hash 去重。
- **hook 非阻塞(硬约束)**:hook 只入队即返回,失败静默(记 `~/.totalrecall/log`);
  分析由独立 worker 进行。SessionEnd hook 绝不能拖慢/卡住 Claude Code。
- **LLM 失败/超时**:ledger 标 `pending`,`totalrecall retry` 重试;transcript 在盘上是真相源,不丢数据。
- **坏行/半截 transcript**:逐行跳过 + 记数。
- **并发**:队列 + 单 worker 串行 + ledger/index 文件锁。

---

## 10. CLI 命令(`totalrecall`)

| 命令 | 作用 |
|------|------|
| `init` | 安装 Claude Code hook、生成默认 `config.toml`、建 `~/.totalrecall/` |
| `ingest <path>` | 处理单个 transcript(供 hook/手动调用) |
| `worker` | 排空队列, 串行处理 |
| `synth` | 触发一次周期综合 |
| `status` | 显示已分析会话数、模式数、待重试、最近更新 |
| `retry` | 重试 ledger 中 `pending` 的会话 |
| `scan` | (接口预留)轮询其他工具 session 目录入队 |

---

## 11. 配置 `config.toml`

```toml
[models]
extract = "claude-haiku-4-5-20251001"   # 单会话抽取
synth   = "claude-sonnet-4-6"            # 周期综合

[limits]
max_input_tokens = 20000
synth_every_n_sessions = 20

[sources]
claude_code = true
codex = false       # Phase 1 关
opencode = false

[privacy]
store_snippets = false   # 证据默认只存引用
```

---

## 12. 存储布局 `~/.totalrecall/`

```
~/.totalrecall/
  queue/            # hook 入队的 transcript 路径
  ledger.json       # 已处理台账
  patterns/         # 模式库, 一个模式一个 JSON
    index.json
    <slug>.json
  insights.md       # 唯一出口
  config.toml
  log               # worker / hook 日志
```

---

## 13. 测试策略

确定性层是大头,且不需 LLM 即可测:
- **adapter**:golden fixtures(脱敏真实 CC JSONL → 期望 NormalizedSession);逐 line-type + 事件派生单测。
- **ledger/幂等**:重复 ingest = no-op;变长只分析增量。
- **merger**:给定发现 JSON,断言 创建/合并/strength + snippet_hash 去重。
- **分析 skill**:已知摩擦的 golden transcript → 断言发现;LLM 输出按 JSON schema 校验 + 少量语义抽查。
- **insights.md**:固定模式库 → 渲染 markdown 快照测试。

---

## 14. MVP 范围(Phase 1)

**做:**
- ✅ Claude Code 适配器(接口为他者留好)
- ✅ 确定性 event/stat 抽取
- ✅ 单会话 Haiku 抽取 + 周期 Sonnet 综合
- ✅ 模式库(JSON)+ 台账 + insights.md
- ✅ SessionEnd hook + 队列 + worker
- ✅ `totalrecall` CLI:`init`/`ingest`/`worker`/`synth`/`status`/`retry`

**不做(Phase 1 之外):**
- ❌ Codex/OpenCode 适配器(留接口)
- ❌ 主动提醒、按需问答
- ❌ Phase 2 的 skill/agent 自动迭代

---

## 15. Phase 2 接缝(设计好,不实现)

- `Pattern.phase2_hint` + insights.md 的"候选改进"区块已在产可落地补救。
- Phase 2 新增:`totalrecall propose` 把高 strength 模式变成具体 skill/CLAUDE.md/子 agent
  草改(草稿 → 用户批 → 应用);加反馈环:模式在改动后转 `resolved` 即验证修复。
- 架构(CLI 核心 + 分析 skill + 模式库)天然支持;Phase 2 主要是新增一个命令 + 一个"补救"skill。

---

## 16. 风险与未决问题(实现期需确认)

1. **transcript schema 细节**:user/assistant/tool 消息行与 `file-history-snapshot` 的确切字段,
   需在实现期对真实文件核实(adapter golden fixtures 即用来锁定)。
2. **headless `claude -p` 调用形态**:如何在子进程里加载 `totalrecall-analyze` skill 并强制 JSON 输出
   (`--output-format json` / 系统提示 / schema 约束),需在实现期验证。
3. **SessionEnd hook 时机**:Claude Code 的 SessionEnd 与 Stop 语义差异、是否每次都触发、
   resume 续接的处理。
4. **跨平台**:Windows 主力;worker detached 拉起与文件锁需在 Windows 上验证。
5. **成本实测**:每会话 Haiku 抽取的真实 token / 时延,可能需要进一步精简提示或采样。

---

## 17. 成功标准(Phase 1)

- 会话结束后,worker 在后台无感地更新模式库,**不拖慢 Claude Code**。
- `insights.md` 随使用逐步充实,Top 摩擦项**与我的真实体感吻合**(可信)。
- 每条摩擦可溯源到具体会话证据。
- 重跑/并发不产生重复或损坏。
- 单会话分析成本可接受(Haiku 抽取 + 摊薄综合)。
- "候选改进"区块给出的建议,我看了觉得**确实该这么改**——为 Phase 2 闭环验明价值。
