# TotalRecall — Codex 支持 设计文档

_日期: 2026-06-17 · 状态: 已通过 brainstorming + 字段核实, 待 writing-plans_

---

## 1. 概述

TotalRecall 的适配器接口(`adapters/base.py` 的 `Adapter` Protocol)从一开始就为多工具设计。
本设计实现 **Codex(OpenAI Codex CLI)适配器**,把 Codex 会话接入 Phase 1 的分析管线
(归一化 → 事件抽取 → `claude -p` 语义分析 → 模式库 → insights),与 Claude Code 会话并轨。

不引入新架构:加一个适配器 + 一个按路径的适配器路由 + 扩展 reconcile 扫描 Codex 目录。

---

## 2. 核心决策(brainstorming 确认)

| 维度 | 决策 |
|------|------|
| 现有 98 个 Codex 会话 | **全部回填**(98 ≪ CC 的 997,且健壮性修复已就位,成本可控) |
| 适配器路由 | **按路径**:`adapters.for_path(path)` 依来源目录返回对应适配器(队列仍只存路径) |
| Codex 触发 | Codex 无 CC 那种 SessionEnd hook → **靠 reconcile**(任意 worker 运行时 + 手动)拾取 |
| 自吞排除 | Codex 会话**永不是分析会话**(TotalRecall 用 `claude -p` 分析,不用 Codex)→ 无需排除 |

---

## 3. Codex 存储格式(已在本机核实)

- 位置:`~/.codex/sessions/YYYY/MM/DD/rollout-<ISO时间戳>-<uuid>.jsonl`(本机 98 个)。
- 每行 = `{timestamp, type, payload}`。`type` ∈ {`session_meta`(首行), `turn_context`, `event_msg`, `response_item`}。
- **session_meta.payload**: `{id, timestamp, cwd, originator, cli_version, source, thread_source, model_provider, base_instructions}`(无 git)。
- **response_item.payload.type**:
  - `message`: `{role: user|assistant|developer, content:[{type: input_text|output_text, text}]}`
  - `function_call`: `{name, arguments, call_id}`(工具调用)
  - `function_call_output`: `{call_id, output(字符串)}`(工具结果;无结构化 exit code)
  - `patch_apply_end`: `{call_id, turn_id, stdout, stderr, success(bool), changes, status}`(文件编辑结果)
  - `reasoning`(跳过,类似 CC thinking)、`custom_tool_call`/`_output`
- **event_msg.payload.type**: `turn_aborted`(`{turn_id, reason, completed_at, duration_ms}`=中断)、`agent_message`、`task_started`、`token_count`(跳过)等。

---

## 4. 架构(改动点)

```
reconcile (扫描)                          worker.process_path
  ├─ sources.claude_code: ~/.claude/projects (带分析目录排除)   adapters.for_path(p)
  └─ sources.codex:       ~/.codex/sessions  (无需排除)    ──►  ├─ ~/.claude/projects → ClaudeCodeAdapter
       enqueue 路径(in-progress 跳过 + ledger 去重)              └─ ~/.codex/sessions  → CodexAdapter
                                                                      │ .parse(p) → NormalizedSession (tool-agnostic)
                                                                      ▼ 后续与 CC 完全一致:events→catalog→claude -p 分析→merge→render
```

四处改动:
1. **CodexAdapter**(`src/totalrecall/adapters/codex.py`)
2. **适配器路由**(`adapters/__init__.py` 的 `for_path(path)`)
3. **reconcile 扩展**(扫 Codex 目录,gated by `sources.codex`)
4. **worker.process_path**(用 `for_path` 取代写死的 `ClaudeCodeAdapter`)

---

## 5. CodexAdapter 详解

`parse(path) -> NormalizedSession`,逐行 JSON,跳过坏行:
- `tool = "codex"`;`session_id` = **`session_meta.payload.id`**(权威 uuid;缺失才回退文件名 stem——
  注意文件名 `rollout-<时间戳>-<uuid>` 的时间戳本身含 `-`,按 `-` 切分歧义,故不以文件名为主);
  `cwd` = `session_meta.payload.cwd`(缺失则 `""`);`git_branch = None`(Codex 无);
  `started_at` = 首行 `timestamp`,`ended_at` = 尾行 `timestamp`;`is_analysis_session = False`(恒)。
- **轮次**(从 `response_item.payload`):
  - `message` role `user`:取 `content` 里 `input_text` 的 text → user 轮次
  - `message` role `assistant`:取 `output_text` 的 text → assistant 轮次
  - `message` role `developer`:跳过(meta,系统/开发指令)
  - `function_call`:tool 轮次(`tool_name = payload.name`,`tool_status="ok"`,text = arguments[:500])
  - `function_call_output`:不单独成轮次;通用 shell 无结构化错误,**不据此标 error**(见风险)
  - `reasoning`/其它:跳过
- **A 类事件 / stats**(确定性):
  - `patch_apply_end`:每个 `changes` 里的文件 → 计 `n_edits`;同一文件累计 ≥ 3 → `churn` 事件;
    `success == false` → `tool_error` 事件(编辑失败)
  - `turn_aborted` → `interrupt` 事件
  - `stats`:n_turns、duration_s(尾-首 timestamp)、n_edits、n_tool_errors(=编辑失败数)
- `changes` 的确切结构(文件列表 vs 路径→改动 的字典)在实现期以 golden fixture 锁定。

---

## 6. 适配器路由 `adapters.for_path(path)`

```python
def for_path(path) -> Adapter:
    s = str(path).replace("\\", "/")
    if "/.codex/sessions/" in s:
        return CodexAdapter()
    return ClaudeCodeAdapter()   # 默认(~/.claude/projects)
```
队列只存路径不变;`worker.process_path` 把 `_ADAPTER.parse(p)` 改为 `adapters.for_path(p).parse(p)`。
(备选:队列 job 打 tool 标签 / 格式嗅探——均更重,不采用。)

---

## 7. reconcile 扩展

现 `reconcile.run` 只扫 `claude_projects_dir()`。改为按 config 的 sources 分别扫:
- `sources.claude_code`:扫 `~/.claude/projects`,沿用分析目录排除(`_encoded_analysis_dir`)。
- `sources.codex`:扫 `codex_sessions_dir()`(=`~/.codex/sessions`,rglob `*.jsonl`),无分析排除。
两路都走同一套:in-progress(最近修改)跳过 + ledger `is_new`(path+hash)去重 + `queue.enqueue`。
返回总入队数。

---

## 8. config / paths

- `config.Config.sources["codex"]`(已存在,默认 false)= 启用开关。
- `reconcile.codex_sessions_dir()` → `Path.home()/".codex"/"sessions"`(镜像 `claude_projects_dir`,硬编码标准位置)。
- 不新增必填配置;`sources.codex=true` 即启用。

---

## 9. 数据流 / 触发

- **触发**:Codex 无 SessionEnd hook。Codex 会话由 **reconcile** 拾取——reconcile 在每次 `worker.run()`
  开头跑(由 CC 的 hook 触发),以及手动 `totalrecall reconcile`/`worker` 时跑。
- 因此 Codex 会话是**机会式增量**:下一次任意 worker 运行时被扫到;in-progress 跳过保证只在会话静置
  (>120s 未写)后才分析。想用完 Codex 立刻分析 → 手动 `totalrecall worker`。
- **专用 Codex 触发(文件监视 / Codex 侧 hook)不在本期**。

---

## 10. 测试

- **CodexAdapter**:golden fixture(手写小 rollout.jsonl)→ 期望 NormalizedSession:
  user/assistant/developer 角色映射、function_call→tool 轮次、session_meta→cwd/session_id、
  首尾 timestamp、坏行跳过、`is_analysis_session=False`。
- **事件**:patch_apply_end(success=false→tool_error;同文件 ≥3→churn)、turn_aborted→interrupt、n_edits。
- **for_path**:`~/.codex/sessions/...jsonl`→CodexAdapter;`~/.claude/projects/...jsonl`→ClaudeCodeAdapter。
- **reconcile**:`sources.codex` 开 → 扫到 Codex 目录文件并入队;关 → 不扫。
- **worker**:process_path 对 Codex 路径用 Codex 适配器(注入 fake analyze,验证走通)。

---

## 11. MVP 范围

**做:**
- ✅ CodexAdapter(rollout 解析 → NormalizedSession,含 A 类:edit/churn/tool_error(编辑失败)/interrupt)
- ✅ 按路径适配器路由 `for_path`;worker 用之
- ✅ reconcile 按 sources 分别扫 CC + Codex 目录
- ✅ 回填现有 98 个 Codex 会话(启用后,运维步骤)

**不做(本期之外):**
- ❌ 通用 shell function_call 的确定性错误事件(output 无结构化 exit code;靠 B 类语义分析兜)
- ❌ 专用 Codex 触发(文件监视 / Codex hook);靠 reconcile 机会式拾取
- ❌ OpenCode 等其它工具(下一个适配器)
- ❌ Codex `archived_sessions`/`history.jsonl`(只接 `sessions/` 的 rollout)

---

## 12. 风险与未决(实现期确认)

1. **`patch_apply_end.changes` 结构**:文件列表还是 路径→改动 字典,需 golden fixture 锁定(影响 churn 抽取)。
2. **function_call_output 无结构化错误**:通用工具失败只能靠 output 字符串启发式或 B 类语义;MVP 不做确定性 tool_error(仅编辑失败计入)。
3. **message content 多段**:user 消息可能多个 input_text 段;assistant 多个 output_text;需拼接。
4. **大会话**:Codex 会话可达 ~900KB;Phase 1 的 `max_input_tokens` 截断已覆盖,无新问题。
5. **回填触发**:启用后需手动 `totalrecall reconcile` + `worker`(或下次 CC hook 触发)拾取 98 个;成本 ~98 次分析调用。

---

## 13. 成功标准

- 启用 `sources.codex` 后,`totalrecall worker`(或下次 CC 会话结束)会把 Codex 会话分析进同一模式库,
  insights.md 里出现来自 Codex 会话的摩擦(evidence 标 `tool=codex`)。
- CodexAdapter 正确映射角色/工具/编辑/中断;坏行不崩。
- CC 与 Codex 经 `for_path` 各走各的适配器,互不干扰;CC 现有 100 测试不回归。
- 回填 98 个 Codex 会话可控完成(借已有 crash-safe/in-progress/截断 健壮性)。
