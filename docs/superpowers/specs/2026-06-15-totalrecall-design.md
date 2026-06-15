# TotalRecall — 设计文档 (Phase 1)

_日期: 2026-06-15 · 状态: 已通过 brainstorming + 自查修订, 待用户复核 → writing-plans_
_修订 r2: 修复自吞递归、finding↔pattern 分离、对账扫描入 Phase 1、worker drain-loop、模型/衰减/目录膨胀等_

---

## 1. 概述

**TotalRecall** 读取本机多个 AI 工具(Claude Code、Codex、OpenCode……)的本地会话,
分析对话以理解"我如何与 AI 协作",并**持续把学到的东西沉淀下来**。

参考产品 **Paxel**(Y Combinator,2026-06-06 发布):本地分析 Claude/Codex/Cursor 会话,
产出一次性"builder report",在 steering/execution/engineering/product instinct/planning
五维打分并给 archetype。

**与 Paxel 的关键差异 / novel 之处:不止一次性画像,而是闭环。**
Paxel 告诉你"你是谁";TotalRecall 持续观察 → 沉淀 → 最终(Phase 2)把洞察反哺成对你自己
skills/agents 的改进。

### 分阶段
- **Phase 1(本文档范围)**:把"理解你的交互摩擦"做扎实,产出可信、可累积的洞察。
- **Phase 2(本文档只留接缝,不实现)**:在洞察之上叠加 skill/agent 的(半)自动迭代。

---

## 2. 核心决策摘要

| 维度 | 决策 |
|------|------|
| 核心目标 | **先洞察,后迭代**(分阶段) |
| Phase 1 洞察焦点 | **摩擦 / 失败模式**(反复纠正、返工、误解意图、多轮拉扯) |
| 隐私 / 算力 | **可用云端 LLM(Claude)** 做分析(transcript 内容会上云,已接受) |
| 运行方式 | **会话结束即时增量**(hook 为主)**+ 对账扫描兜底**(非调度器) |
| 洞察出口 | **唯一出口:一份持续更新的 `insights.md`**(不主动提醒、不做问答) |
| 首个数据源 | **Claude Code 优先**(原生 hook + 主力工具);Codex/OpenCode 后续接 |
| 架构 | **C:混合** — 薄 CLI 管摄取/状态,skill 管分析;适配器为多工具就绪 |
| CLI 语言 | **Python** |

---

## 3. 架构

```
┌─ 触发层 ──────────────────────────────────────────────┐
│ (主) Claude Code SessionEnd hook → 把 transcript 路径   │
│      写入队列目录, 立刻返回(非阻塞, 失败静默)          │
│ (兜底) reconcile: 扫已知来源目录, 把"比 ledger 新"的     │
│      会话补入队 (堵住 hook 漏触发的洞; 非调度器)         │
│ ※ 自吞排除: 带 TOTALRECALL_ANALYSIS 标记的分析会话不入队 │
└───────────────────────────────────────────────────────┘
                      │ enqueue
                      ▼
┌─ CLI 核心 (薄 CLI, 确定性管线; Python) ────────────────┐
│ worker  : 排空队列, 串行处理; 退出前 drain-loop 复查     │
│ adapter : 原始 session 文件 → NormalizedSession         │
│           (并在 ingest 层再次排除自产分析会话)          │
│ ledger  : 已处理记录 → 幂等 + 增量(主要服务 resume)     │
│ orchestr: 调起分析 skill (headless `claude -p`),        │
│           喂 [会话 + 精简模式目录]; spawn 时打自吞标记    │
│ merger  : Finding[] → 归并到 Pattern; 重渲染 insights.md │
└───────────────────────────────────────────────────────┘
                      │ 调用                ▲ 写
                      ▼                     │
┌─ 分析 skill (LLM 判断层) ─────┐   ┌─ 状态 (~/.totalrecall/) ─┐
│ totalrecall-analyze           │   │ queue/        队列          │
│ 输入: NormalizedSession +     │   │ ledger.json   台账          │
│       精简模式目录            │   │ patterns/*.json 模式库      │
│ 输出: Finding[] (摩擦实例,    │   │ patterns/index.json         │
│       尽量复用已有 pattern id)│   │ insights.md   ← 唯一出口    │
└───────────────────────────────┘   │ config.toml / log           │
                                     └─────────────────────────────┘
```

**职责边界**:确定性、便宜、可单测的活(解析、事件派生、台账、归并、渲染、对账)→ CLI 核心(Python);
需要语义判断的活(理解误解/纠正/挫败)→ 分析 skill(Claude)。

---

## 4. 组件详解

### 4.1 触发层
- **主:Claude Code SessionEnd hook**(`~/.claude/settings.json`)。hook 只把 transcript 路径
  (hook 在 stdin 提供 `transcript_path`/`session_id`/`cwd`)追加进 `~/.totalrecall/queue/` 即返回。失败静默。
- **兜底:reconcile 扫描**。会话崩溃/被 kill 时 SessionEnd 可能不触发 → 会话会被静默漏掉。
  故 `totalrecall reconcile`(也在 `worker`/`status` 时顺手跑)扫各来源目录,把"比 ledger 新/更大"
  的 transcript 补入队。适配器本就读这些文件,近乎零成本。**这是堵漏,不是调度器。**
- **自吞排除(关键)**:orchestrator 跑分析用的 `claude -p` 本身是一次 Claude Code 会话,其结束会
  **再次触发 SessionEnd** → 若不排除将无限递归。排除做**两道**:
  1. hook 层:spawn 分析进程时设环境标记 `TOTALRECALL_ANALYSIS=1`,hook 见标记则不入队;
  2. **ingest 层**:adapter 识别自产分析会话(标记/专用 cwd/会话元数据)并跳过——因为 reconcile 扫描
     也会扫到这些自产 transcript,只靠 hook 层排除不够。

### 4.2 worker
- 排空 `queue/`,**单 worker 串行**,持有 ledger/index 文件锁,避免并发写坏模式文件。
- **drain-loop 防竞态**:worker 在释放锁/退出**之前重新检查队列**;若有新项则继续处理。
  这堵住"worker 将退、新 hook 见锁占用而未拉 worker"导致队列项滞留的窗口。
- 由 hook detached 拉起短命进程;第二个 worker 拿不到锁即退出(已有 worker 会经 drain-loop 带走新项)。

### 4.3 adapter(适配器)
- 接口:`(raw_session_file) -> NormalizedSession`,每工具一实现。**Phase 1 只实现 Claude Code adapter**。
- Claude Code 事实:transcript = `~/.claude/projects/<编码路径>/<session-id>.jsonl`,逐行 JSON,
  `type` 区分记录(`last-prompt`/`mode`/`permission-mode`/`attachment`/`file-history-snapshot`/
  user/assistant/tool 等),含 `timestamp`/`cwd`/`gitBranch`/`permissionMode`/工具调用/文件快照。
- 确定性算出 `events`+`stats`(§5 A 类);无法解析的行跳过并记数;识别并跳过自产分析会话(见 §4.1)。

### 4.4 归一化会话 schema
```
NormalizedSession {
  tool, session_id, cwd, git_branch, started_at, ended_at, is_analysis_session(bool)
  turns:  [ Turn { idx, role:user|assistant|tool, ts, text?, tool_name?, tool_status? } ]
  events: [ Event { kind:edit|revert|permission_denied|tool_error|interrupt, ts, ref } ]
  stats:  { n_turns, duration_s, n_tool_errors, n_edits, n_reverts, ... }
}
```

### 4.5 orchestrator(编排)
- spawn `claude -p` 跑 `totalrecall-analyze`,**带 `TOTALRECALL_ANALYSIS=1`**(自吞排除)。
- 喂给 skill 的输入 = **整个 NormalizedSession**(标注"已分析到 turn X"以便聚焦新增、同时保留上下文)
  **+ 精简模式目录**(top-K by strength/recency 的 `id`+`title`+一行,见 §8/§11),
  让 skill **能复用已有 pattern id**,使 recurrence 实时可见。
- 复用用户现有 Claude Code 授权/订阅,无需单独 API key;强制输出符合 Finding JSON schema(不符重试)。

### 4.6 merger(归并)
- 输入 Finding[](摩擦实例)。对每条:
  - 若带可信 `pattern_id`(skill 从目录里复用的)→ 直接归并到该 Pattern;
  - 否则按 slug + 语义相似度匹配已有 Pattern,命中则归并,否则新建。
- 归并 = occurrences++、更新 last_seen、**按 `evidence.snippet_hash` 去重后追加证据**
  (这样 resume 重分析同一会话不会重复计数)。
- 周期综合(synth)再把碎片化的近似 Pattern 合并,作为二道防线。

### 4.7 分析 skill `totalrecall-analyze`
- 输入:一个 NormalizedSession + 精简模式目录。
- 任务:检出 §5 B 类**单会话内的摩擦实例**(不负责判断"是否反复"——那是跨会话、由 merger 涌现)。
- 输出:`Finding[]`,每条含 `category` / `description` / `evidence(turn_refs, snippet_hash)` /
  `pattern_id?`(尽量复用目录里的)/ 建议 `slug`(新模式时)/ 可选 `phase2_hint` / `severity`。

---

## 5. 摩擦信号分类

尽量把信号交给确定性代码,只把语义交给 LLM。**"反复性"不在此层——它是 merger 把多个实例归并到
同一 Pattern 后涌现的跨会话属性。** 本节列的是**单次**可观测的信号。

### A. 元数据派生(CLI 适配器直接算,几乎不花 token)
- **返工/抖动 churn**:`file-history-snapshot` 同一文件反复改 / "改完很快回滚"(edit→revert→re-edit)。
- **权限摩擦**:`permission-mode` 变更 / 被拒工具调用。
- **工具报错**:tool_result 带 error → 失败、重试。
- **重述循环**:连续多个短 user 轮次 / `last-prompt` 抖动。
- **轮次时延 / 会话长度**:任务磨了很多轮或很久。
- **中断/打断**:abort、Stop 事件。

### B. LLM 语义派生(分析 skill 判断,产出"实例 Finding")
- **误解意图**:assistant 做了 X,用户纠正"我要的是 Y"。
- **纠正实例**:用户在本会话纠正了某约束(例:"用 PowerShell 不要 bash")。
  ← 当它跨会话被 merger 归并到同一 Pattern、occurrences 累加,就成了"反复纠正"这一 Phase 2 金矿。
- **澄清缺口**:动手前要来回好多轮才说清。
- **既定规则被违反**:AI 破坏说过的偏好 → "该补一条 skill/CLAUDE.md 规则"候选。
- **挫败标记**:语气 / 明确的"又错了"。

---

## 6. 数据模型

**两层概念,务必分清:** `Finding`(单会话的摩擦**实例**)→ 经 merger → `Pattern`(跨会话的**反复模式**)。

### 6.1 Finding(分析 skill 输出,瞬时,不落地为长期状态)
```
Finding {
  category, description, severity
  evidence: { session_id, tool, turn_refs, snippet_hash }
  pattern_id?   # skill 从精简目录里复用的已有模式 id(关键: 让 recurrence 实时可见)
  slug?         # 新模式时建议的稳定 slug
  phase2_hint?
}
```

### 6.2 Pattern(模式库条目,`patterns/<slug>.json` + `patterns/index.json`)
```
Pattern {
  id:          稳定 slug,如 "powershell-vs-bash-correction"
  title, category, source(metadata|llm|both), description
  first_seen, last_seen, occurrences
  evidence:    [ { session_id, tool, turn_refs, ts, snippet_hash } ]   # 只存引用, 不存全文
  status:      active | fading | resolved
  phase2_hint?
  # strength 不持久化为字段, 而在渲染时按 频次×时近衰减×严重度 现算(见下)
}
```
设计决定:
- **存储**:JSON 文件(可读、可 git diff、可手改),不用 SQLite(MVP 量级用不上)。
- **strength 在渲染/读取时现算**(含时间衰减)——避免"无新发生但已过期"的 `fading` 判定要等下次 synth 才更新。
- **证据只存引用**(session_id + turn_refs + snippet_hash);`snippet_hash` 用于跨次去重。
- 久未出现 `fading`,修复后停止复发 `resolved`。

### 6.3 `insights.md`(唯一面向用户的出口)
Merger 每次**轻量刷新**(重排 Top、更新计数/日期/"最近活动");synth 时由强模型**重写叙事**。结构:
```
# TotalRecall — 你与 AI 的协作摩擦档案
_最后更新 <ts> · 已分析 N 个会话 · 跨 M 个项目_

## 🔥 当前最该处理的摩擦 (按现算 strength)
1. **<标题>** — <类别> · 出现 <n> 次 · 最近 <日期>
   <一行描述>   证据: <refs>   建议(Phase 2): <phase2_hint>

## 📈 趋势   (本周新增/加剧 · 正在消退/已解决)
## 🗂 全部模式 (按类别分组)
## 🧰 给 Phase 2 的候选改进 (skill / agent / CLAUDE.md)
```
**"给 Phase 2 的候选改进"是桥**:Phase 1 即产出可落地补救,Phase 1 自身就有用,Phase 2 一来闭环已预热。

---

## 7. 数据流

**单次(会话结束):**
```
会话结束 → hook 写队列(立即返回; 自产分析会话被标记排除)
→ worker 取出 → adapter 归一化(ingest 层再次排除自产会话)
→ ledger 判定 resume 增量(标注"已分析到 turn X")
→ orchestrator 喂 [会话 + 精简模式目录] 调起分析 skill (带自吞标记)
→ Finding[] → merger 归并到 Pattern(复用 pattern_id / slug+相似度; 证据 hash 去重)
→ 轻量重渲染 insights.md
→ worker 退出前 drain-loop 复查队列
```

**周期综合(由 worker 计数,每 N 个会话自动触发;或手动 `synth`。不引入调度器):**
```
强模型读全模式库 → 合并碎片化近似 Pattern → 重写 insights.md 叙事 + Phase 2 建议
```

**兜底对账(`reconcile`,worker/status 时顺手):**
```
扫各来源目录 → 找"比 ledger 新/更大"的 transcript → 补入队 → 走上面单次流程
```

---

## 8. 成本 / 性能分层

- **省钱主要来自两点**:① A 类信号确定性算出、**零 token**;② 喂 LLM 的是**会话 + 精简目录**,不是全量历史。
- **单会话抽取(每次结束)**:默认 **Sonnet**——B 类"误解意图/挫败"是细腻语义判断,
  能力不足会漏判/虚报、动摇核心价值。**Haiku 作为成本档位需先小样本评测再启用**(配置可切)。
- **周期综合**:**Sonnet**(可升 Opus)。合并、重写叙事。质量开销摊薄到这里。
- **精简模式目录**:只喂 top-K(by strength/recency)的 `id`+`title`+一行,避免输入随模式数线性膨胀。
- 模型/阈值/上限/top-K 均在 `config.toml` 可配;超长会话按"事件附近优先"采样截断,设最大输入 token。

---

## 9. 幂等 / 容错 / 并发

- **幂等 & 增量**:ledger 按 `session_id → {content_hash, last_offset, last_ts}`;hash 未变跳过;
  resume 变长则标注增量、聚焦新增但保留上下文;证据按 `snippet_hash` 去重 → 重分析不重复计数。
- **hook 非阻塞(硬约束)**:hook 只入队即返回,失败静默(记 `~/.totalrecall/log`)。绝不能拖慢/卡住 Claude Code。
- **自吞排除**:两道(hook 标记 + ingest 层识别),防分析会话递归自吞。
- **漏触发兜底**:`reconcile` 扫描堵住 SessionEnd 未触发(崩溃/kill)的会话。
- **LLM 失败/超时**:ledger 标 `pending`,`totalrecall retry` 重试;transcript 在盘上是真相源,不丢数据。
- **坏行/半截 transcript**:逐行跳过 + 记数。
- **并发**:队列 + 单 worker 串行 + 文件锁 + **退出前 drain-loop**,杜绝队列项滞留。

---

## 10. CLI 命令(`totalrecall`)

| 命令 | 作用 |
|------|------|
| `init` | **合并**写入 Claude Code hook(不覆盖已有 hook)、生成默认 `config.toml`、建 `~/.totalrecall/` |
| `ingest <path>` | 处理单个 transcript(供 hook/手动调用) |
| `worker` | 排空队列, 串行处理, 退出前 drain-loop; 顺手 reconcile |
| `reconcile` | 扫各来源目录, 把"比 ledger 新"的会话补入队(堵漏) |
| `synth` | 触发一次周期综合 |
| `status` | 显示已分析会话数、模式数、待重试、最近更新; 顺手 reconcile |
| `retry` | 重试 ledger 中 `pending` 的会话 |

---

## 11. 配置 `config.toml`
```toml
[models]
extract = "claude-sonnet-4-6"   # 单会话语义抽取(B类); Haiku 为成本档位, 需先评测
synth   = "claude-sonnet-4-6"   # 周期综合(可升 claude-opus-4-8)

[limits]
max_input_tokens = 20000
synth_every_n_sessions = 20
catalog_topk = 40               # 喂给单会话 skill 的精简模式目录条数

[sources]
claude_code = true
codex = false                   # Phase 1 关
opencode = false

[privacy]
store_snippets = false          # 证据默认只存引用

[internal]
analysis_marker_env = "TOTALRECALL_ANALYSIS"   # 自吞排除标记
```

---

## 12. 存储布局 `~/.totalrecall/`
```
~/.totalrecall/
  queue/            # hook/reconcile 入队的 transcript 路径
  ledger.json       # 已处理台账
  patterns/         # 模式库, 一个模式一个 JSON
    index.json
    <slug>.json
  insights.md       # 唯一出口
  config.toml
  log               # worker / hook 日志
```
全局目录(跨所有项目),因为摩擦档案是跨项目的"你"。

---

## 13. 测试策略

确定性层是大头,且不需 LLM 即可测:
- **adapter**:golden fixtures(脱敏真实 CC JSONL → 期望 NormalizedSession);逐 line-type + 事件派生单测;
  **自产分析会话被正确识别为 `is_analysis_session` 并跳过**。
- **ledger/幂等**:重复 ingest = no-op;resume 变长聚焦增量;证据 hash 去重。
- **merger**:给定 Finding[],断言 复用 pattern_id / slug+相似度归并 / 新建 / 证据去重。
- **worker 并发**:模拟"将退出时新入队"→ drain-loop 必须带走新项(竞态回归测试)。
- **reconcile**:projects 目录有"比 ledger 新"的文件 → 被补入队。
- **分析 skill**:已知摩擦的 golden transcript → 断言 Finding;输出按 JSON schema 校验 + 少量语义抽查。
- **insights.md**:固定模式库 → 渲染快照测试;strength 现算(含衰减)正确排序。

---

## 14. MVP 范围(Phase 1)

**做:**
- ✅ Claude Code 适配器(接口为他者留好)+ **自产分析会话排除**
- ✅ 确定性 event/stat 抽取
- ✅ 单会话抽取(默认 Sonnet)+ 周期综合;**喂精简模式目录以实时识别 recurrence**
- ✅ Finding↔Pattern 两层模型;模式库(JSON)+ 台账 + insights.md(strength 渲染时现算)
- ✅ SessionEnd hook(合并安装)+ 队列 + worker(drain-loop)+ **reconcile 兜底扫描**
- ✅ `totalrecall` CLI:`init`/`ingest`/`worker`/`reconcile`/`synth`/`status`/`retry`

**不做(Phase 1 之外):**
- ❌ Codex/OpenCode 适配器(留接口)
- ❌ 主动提醒、按需问答
- ❌ Phase 2 的 skill/agent 自动迭代

---

## 15. Phase 2 接缝(设计好,不实现)
- `Pattern.phase2_hint` + insights.md 的"候选改进"区块已在产可落地补救。
- Phase 2 新增 `totalrecall propose`:把高 strength Pattern 变成具体 skill/CLAUDE.md/子 agent
  草改(草稿 → 用户批 → 应用);加反馈环:Pattern 在改动后转 `resolved` 即验证修复。
- 架构(CLI 核心 + 分析 skill + 模式库)天然支持;Phase 2 主要是新增一个命令 + 一个"补救"skill。

---

## 16. 风险与未决问题(实现期需确认)
1. **transcript schema 细节**:user/assistant/tool 消息行与 `file-history-snapshot` 的确切字段,
   需对真实文件核实(adapter golden fixtures 用来锁定)。
2. **headless `claude -p` 调用形态**:如何加载 `totalrecall-analyze` skill 并强制 JSON 输出
   (`--output-format json` / 系统提示 / schema 约束),需验证。
3. **`claude -p` 是否触发 hook**:若触发,§4.1 两道自吞排除生效;若不触发,排除是冗余保险(无害)。仍需实测确认。
4. **SessionEnd 语义与时机**:与 Stop 的差异、是否每次触发、resume 处理、**结束时 transcript 是否已完全 flush**。
5. **抽取模型质量 vs 成本**:Sonnet 默认能否稳定识别 B 类语义;Haiku 档位需小样本评测命中率/误报率后再启用。
6. **`init` 合并写 settings.json**:必须 merge 不能覆盖用户已有 hook;需幂等(重复 init 不重复加 hook)。
7. **跨平台(Windows 主力)**:worker detached 拉起、文件锁、环境标记传递需在 Windows 验证。
8. **精简目录的相似度匹配**:top-K 截断可能让 skill 看不到某个老模式而新建重复条目;synth 合并 + reconcile 为二道防线,需评估碎片化率。

---

## 17. 成功标准(Phase 1)
- 会话结束后,worker 在后台无感更新模式库,**不拖慢 Claude Code**,且**不自吞递归**。
- `insights.md` 随使用逐步充实,Top 摩擦项**与真实体感吻合**,且"反复"项的 occurrences **实时累加**(非等 synth)。
- 每条摩擦可溯源到具体会话证据;漏触发的会话被 reconcile 补回,**无静默丢失**。
- 重跑/并发/resume 不产生重复或损坏。
- 单会话分析成本可接受。
- "候选改进"区块的建议,我看了觉得**确实该这么改**——为 Phase 2 闭环验明价值。
