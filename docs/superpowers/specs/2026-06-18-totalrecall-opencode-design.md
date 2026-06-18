# TotalRecall — OpenCode 支持 设计文档

_日期: 2026-06-18 · 状态: 已通过 brainstorming + 字段核实, 待 writing-plans_

---

## 1. 概述

为 TotalRecall 增加 **OpenCode** 会话来源。OpenCode 与 Claude Code / Codex **根本不同**:它把对话
存在**单个 SQLite 库**(`~/.local/share/opencode/opencode.db`)的关系表里,而非每会话一个 JSONL 文件。

为保住已被反复验证的稳健**文件管线**(crash-safe 队列、ledger 按文件 hash、reconcile 扫目录、
in-progress 按 mtime 跳过),采用**导出到缓存(方案 C)**:一个 export 步骤把 DB 里每个 OpenCode 会话
导出成 `~/.totalrecall/opencode-cache/<sid>.jsonl`,之后**完全复用现有文件管线** —— 普通的
`OpenCodeAdapter` 解析导出的文件,reconcile 把缓存目录当作又一个来源目录扫描。DB 特有的复杂度
(含 WAL 安全读取)被隔离在 export 一处。

---

## 2. 核心决策(brainstorming 确认)

| 维度 | 决策 |
|------|------|
| 集成方式 | **C:导出到缓存**——export DB→`opencode-cache/<sid>.jsonl`,复用文件管线;不动稳健核心 |
| 现有历史 | **回填全部**(本机 368 个会话;借已有 crash-safe/in-progress/截断 健壮性) |
| 适配器路由 | 扩展 `adapters.for_path`:路径含 `/opencode-cache/` → OpenCodeAdapter |
| OpenCode 触发 | 无 hook → 靠 export + reconcile(任意 worker 运行时 / 手动) |
| 自吞排除 | OpenCode 会话**永不是分析会话** → 无需排除 |

---

## 3. OpenCode 存储格式(已在本机核实)

- DB:`~/.local/share/opencode/opencode.db`(+ `-wal`/`-shm`;数据可能在 WAL 未 checkpoint)。
- 关系结构:`session`(368) → `message`(14672) → `part`(55077)。
- **session** 列:`id`、`directory`(=cwd,如 `D:/work/lego`)、`title`、`time_created`、`time_updated`(epoch ms)、`parent_id`(子会话)。
- **message** 列:`id`、`session_id`、`time_created`、`data`(JSON:`{role: user|assistant, time:{created}, ...}`)。文本不在 message,在 part。
- **part** 列:`id`、`message_id`、`session_id`、`time_created`、`data`(JSON,`type` 区分):
  - `text`:`{type, text}` —— 消息文本
  - `tool`:`{type, tool(名称), callID, state:{status, input, output, time, ...}}` —— 工具调用;**`state.status` ∈ {completed, error, ...}**
  - `patch`:`{type, files:[路径列表], hash}` —— 文件编辑
  - `reasoning` / `step-start` / `step-finish` / `compaction` / `file` / `subtask` —— 跳过

---

## 4. 架构(改动点 = 1 新模块 + 3 处小改)

```
totalrecall sync-opencode (新)                    现有文件管线(不改)
  ├─ WAL 安全只读: 复制 db+wal+shm 到临时, 打开合并        reconcile (新增一来源)
  ├─ 查 session/message/part, 重建每会话                ├─ sources.opencode: 扫 opencode-cache/  (无分析排除)
  └─ 写 opencode-cache/<sid>.jsonl(规范化行格式)         worker.process_path
                                                          └─ adapters.for_path(p)
              opencode-cache/<sid>.jsonl ───────────────────► /opencode-cache/ → OpenCodeAdapter
                                                                  .parse(p) → NormalizedSession
                                                                  之后与 CC/Codex 完全一致
```

四处:
1. **export 模块**(`src/totalrecall/opencode_export.py`)+ CLI `sync-opencode`
2. **OpenCodeAdapter**(`src/totalrecall/adapters/opencode.py`)解析导出的 `<sid>.jsonl`
3. **for_path 路由**(`/opencode-cache/` → OpenCode)
4. **reconcile 扩展**(`sources.opencode` 开则扫 `opencode_cache_dir()`)

> export 与 adapter 解耦:export 定义一个**简单稳定的行格式**(我们自己的,非 OpenCode 内部),
> adapter 只认这个格式。DB schema 变化只影响 export 一处。

---

## 5. 导出行格式(opencode_export 产出,OpenCodeAdapter 消费)

每个会话一个文件 `opencode-cache/<sid>.jsonl`,逐行 JSON:
```
{"type":"meta","session_id":<sid>,"cwd":<directory>,"title":<title>,
 "started_at":<iso>,"ended_at":<iso>}                          # 首行
{"type":"text","role":"user","ts":<iso>,"text":<拼接文本>}      # 一条 user/assistant 消息
{"type":"tool","ts":<iso>,"name":<tool>,"status":<state.status>}
{"type":"patch","ts":<iso>,"files":[<路径>...]}
```
- 时间戳:epoch ms → ISO UTC(与 CC/Codex 一致,闭环时间比较才正确)。
- 一条 message 的多个 `text` part 拼接成该轮文本;`tool`/`patch` part 各成一行。
- 顺序:按 message.time_created,再按 part.time_created。

## 6. OpenCodeAdapter

`parse(path) -> NormalizedSession`,逐行 JSON,跳过坏行:
- `tool="opencode"`;`session_id`/`cwd`/`started_at`/`ended_at` 取自 `meta` 行;`git_branch=None`;`is_analysis_session=False`(恒)。
- 轮次:`text` role user/assistant → user/assistant 轮次;`tool` → tool 轮次(tool_name=name,tool_status= "error" if status=="error" else "ok")。
- A 类事件/stats:`tool` status=="error" → tool_error(n_tool_errors);`patch` 的每个 file → n_edits,同文件累计 ≥3 → churn 事件;duration = 尾-首 ts。
- (OpenCode 无显式 interrupt 事件;MVP 不做。)

## 7. opencode_export 模块

- `opencode_db_path()` → `~/.local/share/opencode/opencode.db`。
- **WAL 安全读取**:把 `opencode.db`(+`-wal`+`-shm`)复制到临时目录,以读写方式打开(触发 WAL 合并),
  查询后丢弃临时副本——绝不写用户的库。
- 对每个 `session`(可选过滤 `parent_id IS NULL` 只导出顶层会话,或全导;MVP 全导),重建 message+part →
  写 `opencode-cache/<sid>.jsonl`。
- **增量导出**:若缓存文件已存在且 session.time_updated 未变(存进文件 meta 或比对 mtime),跳过重写
  → 避免每次全量重导。`sync-opencode` 返回导出/更新的会话数。
- in-progress 安全:reconcile 的 mtime 跳过对缓存文件天然生效(刚导出的会话静置 >120s 才分析)。

## 8. 适配器路由 / reconcile / config / paths

- `adapters.for_path`:增 `if "/opencode-cache/" in s: return OpenCodeAdapter()`(在 codex 判断之后、默认之前)。
- `reconcile`:`sources.opencode` 开 → 加 `(opencode_cache_dir(), None)` 到扫描来源(无分析排除)。
- `reconcile.opencode_cache_dir()` → `paths.state_dir()/"opencode-cache"`(在 ~/.totalrecall 下,稳定)。
- `paths.opencode_cache_dir()` 同上(供 export/reconcile 共用)。
- `config.Config.sources["opencode"]`(已存在,默认 false)= 启用开关。

## 9. 数据流 / 触发

- **启用**:config `sources.opencode=true`。
- **导出 + 分析**:`totalrecall sync-opencode`(DB→缓存)→ `totalrecall reconcile`(缓存→队列)→ `totalrecall worker`(分析)。
- **worker 内联 sync 的鲁棒性约束**:`worker.run()` 在 reconcile 前,若 `sources.opencode` 开,**先跑增量 sync**——
  但 sync 必须**轻量且容错**:① 先用一条 `SELECT max(time_updated) FROM session` 之类的廉价探测,
  与上次 sync 记录的水位比对,**无变更则立即返回**(不复制 DB);② 整个 sync 包在 try/except 里,
  **失败静默**(记日志),绝不让 OpenCode 的 DB 问题拖垮/阻断对 CC/Codex 会话的处理。
  首次全量导出(368 会话)较重 → 由**手动 `sync-opencode`** 承担,不放进会话结束热路径。
- 想立刻分析:手动 `sync-opencode && reconcile && worker`。

## 10. 测试

- **opencode_export**:用临时 SQLite 建一个最小 OpenCode schema(session+message+part 各几行),
  断言导出的 `<sid>.jsonl` 行格式正确(meta/text/tool/patch、时间 ISO、文本拼接、增量跳过未变会话)。
- **OpenCodeAdapter**:golden fixture(手写导出格式 jsonl)→ 期望 NormalizedSession:角色映射、
  tool error→tool_status/tool_error、patch→edit/churn、meta→cwd/session_id/ts、坏行跳过、is_analysis_session=False。
- **for_path**:`/opencode-cache/...jsonl` → OpenCodeAdapter;不影响 codex/CC 路由。
- **reconcile**:`sources.opencode` 开 → 扫缓存目录入队;关 → 不扫;不破坏现有 CC/Codex reconcile 测试。
- **worker**:`run()` 在 `sources.opencode` 开时调用 export(注入 fake,验证被调用且不依赖真实 DB)。

## 11. MVP 范围

**做:**
- ✅ opencode_export(WAL 安全读 DB,重建会话,导出 `<sid>.jsonl`,增量跳过未变)+ CLI `sync-opencode`
- ✅ OpenCodeAdapter(导出格式 → NormalizedSession,含 tool_error/edit/churn)
- ✅ for_path 加 OpenCode 路由;reconcile 加 opencode 来源;worker.run 开头按需 sync
- ✅ 回填现有 368 个 OpenCode 会话(启用后运维步骤)

**不做(本期之外):**
- ❌ 直接读 DB 当数据源(放弃方案 A;用导出隔离)
- ❌ interrupt 事件(OpenCode 无显式标记)
- ❌ 监听 DB 变更做实时触发(靠 sync+reconcile 机会式)
- ❌ subtask/子会话特殊处理(MVP 顶层与子会话都按各自 session 导出)

## 12. 风险与未决(实现期确认)

1. **part 的 tool/patch 字段细节**:`state.status` 的全部取值(error 之外)、`patch.files` 的确切结构(已核实为路径字符串列表)——以临时 DB fixture + 真实抽样核实。
2. **WAL 合并副本**:复制 db+wal+shm 后以读写打开会就地 checkpoint 临时副本(不碰原库);需确认临时副本可写、用完清理。
3. **会话量/性能**:368 会话、55k parts;export 全量首次稍重,但增量后只导变更;查询按 session_id 索引。
4. **session.directory 缺失**:个别会话可能无 directory → cwd 置 ""。
5. **回填触发**:启用后首次需 `sync-opencode`(全量导出 368)+ `reconcile` + `worker`;成本 ~368 次分析(可临时用 Haiku)。
6. **epoch 时区**:OpenCode 时间是 epoch ms(UTC) → ISO UTC 转换需正确,闭环/strength 比较才对。

## 13. 成功标准

- `sources.opencode=true` + `sync-opencode` + `worker` 后,OpenCode 会话进入同一模式库,
  insights.md 出现 `tool=opencode` 证据的摩擦。
- OpenCodeAdapter 正确映射角色/工具(含结构化 tool_error)/编辑/churn;坏行不崩。
- 导出**绝不写用户的 opencode.db**;增量导出不每次全量。
- CC / Codex / OpenCode 经 for_path 各走各的;现有 112 测试不回归。
- 回填 368 个 OpenCode 会话可控完成。
