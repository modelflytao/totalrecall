# TotalRecall Phase 2 — 设计文档

_日期: 2026-06-17 · 状态: 已通过 brainstorming + 自查验证, 待 writing-plans_

---

## 1. 概述

Phase 1 把会话摩擦沉淀成持久的**模式库**(`~/.totalrecall/patterns/*.json`),并在 `insights.md`
里给出"🧰 给 Phase 2 的候选改进"。**Phase 2 闭环**:把高 strength 的**反复**摩擦模式转化为对你
`CLAUDE.md` 的具体规则,经你批准后写入,并验证规则是否真的消除了该摩擦。

**输入**:Phase 1 的 Pattern(含 `description`/`evidence`/`occurrences`/`strength`/`phase2_hint`/`status`)。
**输出**:经批准、写入你 CLAUDE.md 的规则 + 每条规则的"是否生效"判定。

---

## 2. 核心决策(brainstorming 确认)

| 维度 | 决策 |
|------|------|
| 改进目标 | **仅 CLAUDE.md/memory 规则**(MVP 不碰 skills/子 agent) |
| 应用方式 | **起草 → 你批准 → 自动写入(带备份)**,记录 `applied_at` |
| 反馈环 | 应用后 N 天(默认 14)无复发 → `resolved`;应用后仍复发 → `ineffective`(标记"修复无效") |
| 触发 | **手动** `totalrecall propose` / `apply`(不自动改你的配置) |
| 状态模型 | 提案工作流在 `proposals.json`;结果(`applied_at` / `resolved` / `ineffective`)落在 **Pattern** 上 |

---

## 3. 架构

Phase 2 = 3 个新组件 + CLI 命令,叠加在 Phase 1 之上(模式库是输入):

```
                 ┌──────────── Pattern 库 (Phase 1) ────────────┐
                 │  patterns/*.json  (含 applied_at, status)     │
                 └───────────────────────────────────────────────┘
   totalrecall propose │ 读 top 反复且未处理的 pattern        ▲ verifier 回写
        ▼              │                                     │ (resolved/ineffective)
┌─ proposer ─────────┐ │                          ┌─ verifier(并入分析流) ─┐
│ claude -p 起草规则  │ │                          │ 新 finding 命中已 applied │
│ → proposals.{md,json}│                          │ 的 pattern 且更晚 → 无效  │
└────────┬────────────┘                          │ applied+N天无复发 → resolved│
         │ 你 review proposals.md                 └───────────────────────────┘
         ▼  totalrecall apply <id...>
┌─ applier ──────────────────────────────────────────────────────┐
│ 规则写入 ~/.claude/totalrecall-rules.md(带 <!-- pattern:id --> 标记) │
│ 一次性把 @totalrecall-rules.md 导入 ~/.claude/CLAUDE.md(先备份)      │
│ 在 Pattern 记 applied_at + rule;proposals.json 状态→applied         │
└─────────────────────────────────────────────────────────────────┘
```

**职责边界**:确定性、可单测的活(读 pattern、写文件、状态机、CLI、import 注入)→ Python;
需要语义判断的活(把摩擦写成贴合风格的规则)→ Claude(`claude -p`,Sonnet)。

---

## 4. 组件详解

### 4.1 proposer
- 选取候选:`occurrences ≥ propose_min_occ`(默认 3)、`status == active`、无 `applied_at`、
  且 pattern_id 不在 proposals.json 的 `rejected` 中;按 strength 降序取 `propose_top_n`(默认 10)。
- 对每个候选,用 `claude -p`(synth_model)起草:输入 = pattern 的 `title`/`description`/
  `phase2_hint` + 若干 evidence 轮次文本 + **当前 `totalrecall-rules.md` 全文**(避免重复规则) +
  CLAUDE.md 的风格样例(前若干行)。输出 JSON:`{ rule_text, rationale, target_file }`。
- 写 `proposals.json`(状态 `drafted`)+ 渲染 `proposals.md`(人读:id、pattern 标题、规则、依据、
  "如何应用")。同一 pattern 已有 `drafted`/`applied` 提案则跳过(幂等)。

### 4.2 applier
- `totalrecall apply <id...>` 或 `--all`:对每个 `drafted` 提案:
  1. 校验其 pattern 仍存在(synth 可能已合并/删除);不存在则跳过并记 `stale`。
  2. **幂等写规则**:若 `totalrecall-rules.md` 已含 `<!-- pattern: <id> -->` 标记则跳过;否则追加
     一个区块:标记 + 规则文本 + 来源注释(occurrences、最近日期)。
  3. **一次性导入**:若 `~/.claude/CLAUDE.md` 不含 `@totalrecall-rules.md`,先备份
     (`CLAUDE.md.bak-totalrecall`)再在末尾追加该 import 行。
  4. 在 Pattern 记 `applied_at = now`、`applied_rule = rule_text`;proposals.json 状态→`applied`。
- `totalrecall reject <id...>`:proposals.json 状态→`rejected`(proposer 不再重提)。

### 4.3 verifier(闭环,并入 Phase 1 分析流)
- **复发即无效**:在 `merger` 把一个 finding 并入某 Pattern 时,若该 Pattern 有 `applied_at` 且
  该 finding 的证据时间 `> applied_at` → 设 `status = "ineffective"`(规则没起作用)。
  **此判定可覆盖先前的 `resolved`**(晚到的回归:已判"已解决"后又复发,应翻回 ineffective)。
- **无复发即解决**:在 `render`/`status`(渲染时现算)中,对有 `applied_at` 的 Pattern:
  若 `now - applied_at ≥ resolved_after_days`(默认 14)且**没有任何证据时间晚于 `applied_at`**
  → `status = "resolved"`。
- **关键依赖(可靠性)**:复发必须被归并回**同一** Pattern 才能检测。故把**所有 applied 的 pattern
  钉进**喂给分析 skill 的精简目录(catalog,Phase 1 的 `catalog.build` 增加 "pin applied patterns"),
  让分析 skill 在摩擦复发时复用其 id,而非新建。(applied patterns 数量随手动应用增长缓慢,
  pin 进 catalog 的 token 成本 MVP 可接受;未来量大可只 pin 未 resolved 的 applied patterns。)

---

## 5. 数据模型与文件

### 5.1 Proposal(`~/.totalrecall/proposals.json`)
```
Proposal {
  id:          稳定短 id(如 "p-<pattern_slug>")
  pattern_id, target_file
  rule_text, rationale
  status:      drafted | applied | rejected | stale
  created_at, applied_at?
}
```

### 5.2 Pattern 扩展(Phase 1 的 `models.Pattern` 增字段)
- 新增 `applied_at: str | None`(应用规则的时间)
- 新增 `applied_rule: str | None`(写入的规则文本,便于 insights 展示与回溯)
- `status` 枚举扩为 `active | fading | resolved | ineffective`
  - `resolved` / `ineffective` 为**粘性**:一旦设定,`derive_status` 不再用时近度覆盖它;
    `derive_status` 只对非粘性状态计算 `active`/`fading`。

### 5.3 `~/.claude/totalrecall-rules.md`(受管规则文件)
```
<!-- Managed by TotalRecall. Edit/remove freely; blocks are keyed by pattern id. -->

<!-- pattern: powershell-vs-bash-correction -->
- 在 Windows 上默认使用 PowerShell;仅在确需 POSIX 脚本时用 Bash。
  _(TotalRecall: 反复 14 次 · 最近 2026-06-15)_
```
- 通过在 `~/.claude/CLAUDE.md` 末尾加一行 `@totalrecall-rules.md` 引入(CLAUDE.md 支持 @import,
  与你现有的 `@RTK.md` 同理)。**你的 CLAUDE.md 只多这一行**,且删文件+删行即可完全回退。

### 5.4 `~/.totalrecall/proposals.md`(人读视图)
每条:`### [<id>] <pattern 标题>` + 规则草稿(代码块)+ 依据 + `应用: totalrecall apply <id>`。

---

## 6. 数据流

**起草:** `totalrecall propose` → 选候选 → 逐个 `claude -p` 起草 → 写 proposals.{json,md} → 提示你 review。

**应用:** 你读 `proposals.md` → `totalrecall apply <id...>` → 写 rules 文件 + 注入 import(备份)+
回写 Pattern(`applied_at`/`applied_rule`)+ proposals 状态→applied。

**验证(随后续增量分析自动发生):**
- 某 applied pattern 复发(新 finding 证据时间 > applied_at) → merger 标 `ineffective`。
- applied 后 N 天无更晚证据 → 渲染时算出 `resolved`。
- insights.md 增区块:**✅ 已解决 · ⏳ 已应用待验证 · ⚠️ 修复无效**(各列 pattern + 规则)。

---

## 7. Pattern 状态机

```
active ──propose+apply──> (applied_at 记录, 仍 active/待验证)
  │                              │
  │                              ├── N 天无复发 ──> resolved (粘性)
  │                              └── 复发(证据晚于 applied_at) ──> ineffective (粘性)
  └── 久未出现 ──> fading        ineffective ──重新 propose+apply──> 再次待验证
```
- 渲染时 `derive_status`:`status in {resolved, ineffective}` → 原样返回(粘性);
  否则按 `applied_at` + 证据时间算 `resolved`,再否则按时近度算 `active`/`fading`。

---

## 8. CLI 命令(新增)

| 命令 | 作用 |
|------|------|
| `propose [--top N] [--min-occ K]` | 为 top 反复且未处理的 pattern 起草规则 → proposals.{json,md} |
| `apply <id...> \| --all` | 应用指定/全部 drafted 提案(写 rules + import + 回写 pattern) |
| `reject <id...>` | 标记提案 rejected(不再重提) |
| `proposals` | 列出提案及状态(drafted/applied/rejected/stale) |

`status` 增显:已应用 / 已解决 / 待验证 / 无效 的计数。

---

## 9. 配置(`config.toml` 增段)

```toml
[phase2]
propose_top_n = 10
propose_min_occ = 3
resolved_after_days = 14
rules_file = "~/.claude/totalrecall-rules.md"
claude_md  = "~/.claude/CLAUDE.md"
```

---

## 10. 容错 / 幂等 / 安全

- **CLAUDE.md 安全**:仅追加一行 `@import`,先备份 `CLAUDE.md.bak-totalrecall`;规则正文进**独立受管文件**,
  不动你 CLAUDE.md 正文。删文件+删 import 行即完全回退。
- **幂等**:rules 文件按 `<!-- pattern: id -->` 标记去重;import 注入前先查存在;重复 apply 是 no-op。
- **proposer/applier 不自动触发**:只在你手动运行时执行,绝不在后台改你的配置。
- **stale 提案**:apply 时若 pattern 已被 synth 合并/删除 → 跳过 + 标 `stale`,不报错。
- **状态权威**:Pattern 的 `applied_at`/`status` 是闭环真相源;proposals.json 是工作流视图,二者不一致时以 Pattern 为准。
- **并发加锁**:`apply` 回写 Pattern(`applied_at`/`status`)会与后台增量 worker 的 pattern 写入竞争 →
  `apply` 必须先取 `worker_lock`(与 Phase 1 给 `ingest`/`retry` 加锁同理);取不到则提示稍后重试。
  `propose` 只读 pattern、只写 proposals.{json,md},无需锁。verifier 的 `ineffective` 标记发生在 worker
  自身的 merger 流程内(已持锁),无竞争。
- **`claude -p` 失败**:proposer 跳过该候选并记日志;不阻断其余。

---

## 11. 测试策略

确定性层全部可单测(注入 fake runner,不调真 claude):
- **proposer**:fake runner 返回规则 JSON → 断言 proposals.{json,md} 内容、候选筛选(occ/status/applied/rejected)、幂等(已有提案不重提)。
- **applier**:临时 HOME + 临时 CLAUDE.md → 断言 rules 文件区块写入、import 注入幂等、CLAUDE.md 备份、pattern 回写 `applied_at`;stale pattern 跳过。
- **verifier**:
  - 复发:applied pattern + 更晚证据的 finding → merger 标 `ineffective`。
  - 解决:applied + 无更晚证据 + 超 N 天(注入 now)→ `derive_status` 算出 `resolved`。
  - 粘性:resolved/ineffective 不被时近度覆盖。
- **catalog pin**:applied patterns 必在 catalog 中(即使不在 top-K strength)。
- **render**:已解决/待验证/无效 三区块正确分组。
- **CLI**:propose/apply/reject/proposals 派发。

---

## 12. MVP 范围

**做:**
- ✅ proposer(CLAUDE.md 规则草稿,via claude -p)
- ✅ applier(受管 rules 文件 + 一次性 @import + 备份 + 回写 pattern)
- ✅ verifier 闭环(ineffective on 复发 / resolved on 无复发)+ catalog pin applied
- ✅ Pattern 扩展(applied_at/applied_rule/status 粘性)
- ✅ CLI:propose/apply/reject/proposals + status 增显 + insights 三区块

**不做(Phase 2 之外):**
- ❌ 生成/编辑 skills 或子 agent(仅 CLAUDE.md 规则)
- ❌ 自动 propose/apply(全手动)
- ❌ 多目标文件路由(MVP 单一受管 rules 文件 + 全局 CLAUDE.md)
- ❌ project 级 CLAUDE.md / memory 系统(后续可扩 `target_file` 路由)

---

## 13. 风险与未决(实现期确认)

1. **闭环依赖归并可靠性**:复发必须归并回同一 pattern 才能判 ineffective/resolved。靠"pin applied patterns 进 catalog"
   + Phase 1 的 pattern_id 复用缓解;需评估归并命中率。若复发被新建成别的 pattern,会漏判(假 resolved)。
2. **假 resolved**:"N 天无复发"也可能只是你没做那类任务(并非规则生效),无法区分。文案应表述为"未再复发",不夸大为"已修复"。
3. **`claude -p` 起草质量**:规则需贴合 CLAUDE.md 风格、可执行、不与现有规则冲突。喂当前 rules + CLAUDE.md 样例缓解;仍需人审(故"批准"是硬门)。
4. **CLAUDE.md @import 语义**:确认 `@totalrecall-rules.md` 相对路径解析(相对 CLAUDE.md 所在目录)与 Claude Code 实际加载行为一致。
5. **证据时间口径**:`applied_at` 与 evidence `ts` 的时区/格式一致(均 ISO UTC),比较才正确。

---

## 14. 成功标准

- `propose` 能为 top 反复摩擦产出**贴合风格、可直接用**的 CLAUDE.md 规则草稿。
- `apply` 后,规则进入受管文件并经一行 @import 生效;**我的 CLAUDE.md 只多一行**,可一键回退。
- 后续会话中,被规则消除的摩擦在 N 天后标 `resolved`;**仍复发的标 `ineffective` 并提示我换法子**——闭环验证有效。
- 全流程手动、可审、可逆;Pattern/proposals 状态一致。
- 所有确定性层有单测;真 `claude -p` 仅在 proposer 一处,且可注入 fake。
