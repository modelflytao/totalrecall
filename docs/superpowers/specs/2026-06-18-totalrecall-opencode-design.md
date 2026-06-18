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
- 时间戳:epoch ms → **带时区的 ISO UTC**(`datetime.fromtimestamp(ms/1000, tz=timezone.utc).isoformat()`,
  产出含 `+00:00`)。**必须 tz-aware**:否则 merger `_ts`/闭环/strength 把 naive 与 aware 混比会抛异常(修正 M5)。
  实现期加断言:导出行的 ts 含时区偏移。
- 一条 message 的多个 `text` part 拼接成该轮文本;`tool`/`patch` part 各成一行。
- 顺序:按 message.time_created,再按 part.time_created。

## 6. OpenCodeAdapter

`parse(path) -> NormalizedSession`,逐行 JSON,跳过坏行:
- `tool="opencode"`;`session_id`/`cwd`/`started_at`/`ended_at` 取自 `meta` 行;`git_branch=None`;`is_analysis_session=False`(恒)。
- 轮次:`text` role user/assistant → user/assistant 轮次;`tool` → tool 轮次(tool_name=name,tool_status= "error" if status=="error" else "ok")。
- A 类事件/stats:`tool` status=="error" → tool_error(n_tool_errors);`patch` 的每个 file → n_edits,同文件累计 ≥3 → churn 事件;duration = 尾-首 ts。
- `tool` status=="running"(进行中)→ 当 "ok" 记 tool 轮次,**不计 error**(修正 M1)。
- (OpenCode 无显式 interrupt 事件;MVP 不做。)

**重分析去重(修正 I1 —— 跨来源通用改进)**:活跃 OpenCode 会话长大后每次 sync 都会重导→重分析,
若按内容 snippet_hash 去重,新一轮 finding 的 hash 不同 → 同一会话的 occurrences 被**重复累加**、虚高。
修正:`merger._apply` 对一个 Pattern 追加证据时,去重键从"仅 snippet_hash"改为 **也按 `session_id` 去重**——
即同一会话对同一 Pattern 只贡献一次 occurrence(occurrences = 该模式出现过的**不同会话数**)。
这正是之前手动清理计数时采用的语义。对 CC/Codex 同样正确(重分析罕见,正常情况行为不变),merger 层统一修。
实现期加回归测试:同一 session_id 的两个 finding(不同 snippet_hash)并入同一 Pattern → occurrences 只 +1。

## 7. opencode_export 模块

- `opencode_db_path()` → `~/.local/share/opencode/opencode.db`。
- **WAL 安全 + 一致快照读取(修正 I3)**:**不手工复制 db+wal+shm**(复制顺序不一致会导致 .db 与 -wal 撕裂、
  salt 不匹配而静默读到旧数据)。改用 **SQLite 一致性快照**:以 `mode=ro` 打开原库,用 `Connection.backup()`
  把事务一致的快照(含 WAL)备份到临时文件,再查询临时文件;用完删临时文件。**全程只读原库**。
- 对每个 `session`(MVP 全导,含子会话 `parent_id` 非空者),重建 message+part → 写 `opencode-cache/<sid>.jsonl`。
- **增量导出(修正 C1 —— 关键)**:**不以 `session.time_updated` 作为单会话是否变更的判据**。
  实测 38 个会话的 part 在 `time_updated` 之后仍流入(最多晚 ~15.5 分钟),用它会把流式中的会话**永久截断**。
  做法:① **全局水位探测**(廉价):`SELECT max(time_updated) FROM session` 与持久化的上次水位比对,
  无变化 → **整个 sync 立即返回**(全局 max 会被最近触碰的会话顶上来,可靠);② 若有变化,
  **逐会话全部重导**(368 个小文件,导出成本远低于一次 LLM 分析)——**用 ledger 的 path+hash 作为唯一去重权威**:
  内容没变 → hash 不变 → ledger 跳过;内容变了(会话长大)→ hash 变 → 重新分析。export 自己不猜 staleness。
- **孤儿缓存 GC(修正 C2)**:导出后,`SELECT id FROM session` 得到现存会话集,**删除 `opencode-cache/` 里
  sid 不在该集合的 `<sid>.jsonl`**(OpenCode 可删除/归档会话,否则缓存文件残留 → 被反复当 stale 分析)。
- **持久化水位**:把"上次 sync 的全局 max time_updated"存进 `~/.totalrecall/opencode-sync.json`(不靠缓存文件 mtime 反推)。
- `sync-opencode` 返回导出/更新/删除的会话数。
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
- **worker 内联 sync 的鲁棒性约束(修正 I2)**:`worker.run()` 整体在 `try_worker_lock()` 内运行。
  内联 sync 放在 reconcile 前,但必须:
  ① **强制廉价全局探测先行**:`SELECT max(time_updated) FROM session` 与**持久化水位**(`opencode-sync.json`)比对,
     无变化 → 立即返回,**绝不触发 backup 快照**(避免在持锁时做 200MB+ 的 DB I/O);
  ② 整个 sync 包 try/except,**失败静默**(记日志),OpenCode 的 DB 问题绝不拖垮/阻断 CC/Codex 处理;
  ③ 热路径本身已天然安全:SessionEnd hook 是 detached spawn worker、立即返回,DB 工作永不阻塞用户会话结束。
  首次**全量导出(368 会话)**较重 → 只由**手动 `sync-opencode`** 承担,不进会话结束触发的 worker 热路径。
  (注:持锁期间的快照仅在确有变更时发生且单实例串行;偶发数秒可接受,已用廉价探测严格门控。)
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
- ✅ opencode_export(SQLite `backup()` 一致快照读,重建会话,导出 `<sid>.jsonl`,全局水位探测短路,孤儿缓存 GC)+ CLI `sync-opencode`
- ✅ OpenCodeAdapter(导出格式 → NormalizedSession,含 tool_error/edit/churn,tz-aware ts)
- ✅ for_path 加 OpenCode 路由;reconcile 加 opencode 来源;worker.run 开头按需(廉价探测门控)sync
- ✅ merger 证据按 session_id 去重(修 I1,跨来源通用)
- ✅ 回填现有 368 个 OpenCode 会话(启用后运维步骤)

**不做(本期之外):**
- ❌ 直接读 DB 当数据源(放弃方案 A;用导出隔离)
- ❌ interrupt 事件(OpenCode 无显式标记)
- ❌ 监听 DB 变更做实时触发(靠 sync+reconcile 机会式)
- ❌ subtask/子会话特殊处理(MVP 顶层与子会话都按各自 session 导出)

## 12. 风险与未决(鲁棒性审查已解决的项 + 实现期确认)

**鲁棒性审查(opus,基于本机 207MB 真实库)已解决并入设计:**
- **C1**(已修 §7):`session.time_updated` 非可靠变更键(38 会话 part 晚于它达 ~15.5 分钟)→ 改为全局水位探测 + ledger-hash 唯一去重。
- **C2**(已修 §7):删除/归档会话留孤儿缓存 → 导出后按现存 session 集 GC 缓存文件。
- **I1**(已修 §6):重导长大会话致 occurrences 虚高 → merger 证据按 session_id 去重。
- **I2**(已修 §9):内联 sync 持锁做重 I/O → 强制廉价全局探测门控,仅变更时快照,失败静默。
- **I3**(已修 §7):手工复制 db+wal 撕裂风险 → 改用 SQLite `Connection.backup()` 一致快照。
- **M1/M5**(已修 §6/§5):`tool` 第三态 `running` 当 ok 不计 error;导出 ts 必须 tz-aware。

**实现期仍需确认:**
1. `Connection.backup()` 在本机 207MB 库的耗时(全量首次);确认临时快照文件用完清理。
2. 性能:368 会话、55k parts 的全量导出时长(首次手动跑可接受;增量靠全局探测短路)。
3. 子会话(282/368 有 parent_id):cwd 各自独立,确认 parent 与 child 不重复归因(加 fixture 测)。
4. 回填触发:启用后 `sync-opencode`(全量 368)+ `reconcile` + `worker`;成本 ~368 次分析(可临时 Haiku)。

## 13. 成功标准

- `sources.opencode=true` + `sync-opencode` + `worker` 后,OpenCode 会话进入同一模式库,
  insights.md 出现 `tool=opencode` 证据的摩擦。
- OpenCodeAdapter 正确映射角色/工具(含结构化 tool_error)/编辑/churn;坏行不崩。
- 导出**绝不写用户的 opencode.db**;增量导出不每次全量。
- CC / Codex / OpenCode 经 for_path 各走各的;现有 112 测试不回归。
- 回填 368 个 OpenCode 会话可控完成。
