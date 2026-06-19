# TotalRecall — 部署指南(AI 可读可执行)

> **给执行者(AI agent 或人):** 这是一份自包含的部署 runbook。按"步骤"顺序执行命令,每步给了**预期输出**用于校验。遇到分支决策点会用 **DECISION** 标出——按用户偏好或默认建议选择。完整说明见同目录 `README.md`。

---

## 0. 这是什么

TotalRecall 是一个本地工具:分析你与 AI 工具(Claude Code / Codex / OpenCode)的会话,抽取"协作摩擦"模式,维护一份 `~/.totalrecall/insights.md`,并能把反复摩擦闭环成 CLAUDE.md 规则。纯本地运行,分析靠你已登录的 `claude` CLI(`claude -p`)。

---

## 1. 前置条件(先校验,缺了再装)

| 依赖 | 检查命令 | 预期 | 缺失时 |
|------|---------|------|--------|
| Python ≥ 3.11 | `python --version` | `Python 3.11+` | 安装 Python 3.11/3.12/3.13 |
| pip | `python -m pip --version` | 显示版本 | 随 Python 自带 |
| Claude CLI(已登录) | `claude --version` | 显示版本 | 安装并 `claude login`(分析依赖它) |
| git(仅源码安装可选) | `git --version` | 显示版本 | 可选 |

> **平台**:开发于 Windows 11 / PowerShell,代码跨平台(Linux/macOS 同样可用)。下文命令给通用形式;Windows PowerShell 下 `~` 写作 `$env:USERPROFILE`。

---

## 2. 解压并安装

**步骤 2.1 — 解压本压缩包**到任意目录(例 `~/totalrecall` 或 `D:\tools\totalrecall`),`cd` 进去。
解压后应看到:`README.md` `DEPLOY.md` `pyproject.toml` `src/` `skills/` `tests/` `docs/`。

**步骤 2.2 — 安装(可编辑模式)**
```bash
python -m pip install -e .
```
预期:`Successfully installed totalrecall-0.1.0`(及依赖 `filelock`)。
> 若报权限错误,加 `--user`:`python -m pip install -e . --user`

**步骤 2.3 — 校验 CLI 就位**
```bash
totalrecall --help    # 或: python -m totalrecall.cli --help
```
预期:列出子命令 `init / status / worker / reconcile / ingest / retry / synth / sync-opencode / hook / propose / apply / reject / proposals`。
> 若 `totalrecall` 不在 PATH:用 `python -m totalrecall.cli <cmd>` 等价替代(全文通用)。

**步骤 2.4 —(推荐)跑测试自检**
```bash
python -m pip install pytest
python -m pytest -q
```
预期:`135 passed`(或更多)。全绿表示安装正确。

---

## 3. 初始化

```bash
totalrecall init
```
做了什么:创建 `~/.totalrecall/`(配置 + 状态目录),并把 **SessionEnd hook 合并写入** `~/.claude/settings.json`(幂等、先备份成 `settings.json.bak-totalrecall`,不覆盖你已有 hook)。
预期输出:`TotalRecall initialized.`

校验:
```bash
totalrecall status
```
预期:`sessions: 0` / `patterns: 0` / `pending: 0`(全新状态)。

> **此后,每次 Claude Code 会话结束都会自动分析**——无需常驻进程。

---

## 4. DECISION:历史会话怎么处理

`~/.claude/projects/` 里可能已有大量历史会话。**默认行为**:启用 hook 后只分析**新**会话。是否回填历史由你定:

- **选项 A —— 从现在开始(推荐,默认)**:不回填,只学新会话。无需额外操作,直接用即可。
- **选项 B —— 回填历史**:见下方"§7 回填"。注意:大量历史 = 大量 `claude -p` 调用(成本/时间),建议回填期临时切 Haiku 模型(见 §6)。

> **建议**:首次部署选 A。用几天积累出真实摩擦后再按需回填或起草规则。

---

## 5. 日常使用(零操作)

- 正常用 Claude Code。会话结束 → 后台自动分析 → 摩擦沉淀进模式库。
- 随时看洞察:打开 `~/.totalrecall/insights.md`。
- 随时看进度:`totalrecall status`。
- 想立刻分析而不等会话结束:`totalrecall reconcile && totalrecall worker`。

---

## 6. 配置(可选)

文件:`~/.totalrecall/config.toml`(由 `init` 生成默认值)。常改项:

```toml
[models]
extract = "claude-sonnet-4-6"            # 单会话分析模型(质量优先)
                                         # 批量回填省钱可临时改: "claude-haiku-4-5-20251001"
synth   = "claude-sonnet-4-6"

[limits]
max_input_tokens       = 12000           # 单次喂模型的最大 token(超长会话截断)
synth_every_n_sessions = 25              # 每 N 次分析自动 synth 合并(回填时可设 99999 关掉)

[sources]
claude_code = true                       # 扫 ~/.claude/projects
codex       = false                      # 设 true 启用 Codex(~/.codex/sessions)
opencode    = false                      # 设 true 启用 OpenCode(~/.local/share/opencode/opencode.db)
```

**启用 Codex**:把 `codex = true`,然后 `totalrecall reconcile && totalrecall worker`。
**启用 OpenCode**:把 `opencode = true`,然后 `totalrecall sync-opencode`(只读导出 SQLite→缓存)`&& totalrecall reconcile && totalrecall worker`。

---

## 7. 回填历史(选项 B,可选)

> 大批量回填建议:先把 `[models] extract` 临时改成 `claude-haiku-4-5-20251001`、`synth_every_n_sessions = 99999`(省钱/避免限流);跑完再改回。

**Claude Code / Codex 回填:**
```bash
totalrecall reconcile        # 把历史会话补入队列
totalrecall worker           # 逐个分析(crash-safe;被中断可重跑续上)
totalrecall status           # 看进度
```

**OpenCode 回填(先导出再分析):**
```bash
totalrecall sync-opencode    # 只读快照导出全部会话 -> ~/.totalrecall/opencode-cache/
totalrecall reconcile
totalrecall worker
```

> worker 是单次阻塞调用、会一次 drain 完整个队列;若中途被杀(限流/休眠),重跑 `totalrecall worker` 会从断点续(crash-safe,无重复)。回填后想清理计数:`totalrecall synth`。

---

## 8. Phase 2 —— 把摩擦闭环成 CLAUDE.md 规则(可选)

```bash
totalrecall propose          # 为 top 反复摩擦起草规则 -> ~/.totalrecall/proposals.md
#   人工审阅 proposals.md
totalrecall apply <id...>    # 应用认可的(写入 ~/.claude/totalrecall-rules.md + 一行 @import,带备份)
totalrecall reject <id...>   # 拒绝不要的
totalrecall proposals        # 查看状态
```
应用后,后续会话会自动验证规则是否生效,显示在 `insights.md` 的「🔧 Phase 2」区块(✅已解决 / ⏳待验证 / ⚠️修复无效)。

---

## 9. 校验部署成功(端到端冒烟,可选)

```bash
totalrecall reconcile && totalrecall worker   # 若已有会话,分析一两个
totalrecall status                            # sessions/patterns 应 > 0
```
然后打开 `~/.totalrecall/insights.md`,应看到带 `tool=...` 证据的摩擦条目。`pending: 0` 表示无分析错误。

---

## 10. 卸载 / 回退

- **暂停学习**:从 `~/.claude/settings.json` 删掉 SessionEnd 那条 hook(或用 `settings.json.bak-totalrecall` 恢复)。
- **撤销已应用规则**:删 `~/.claude/totalrecall-rules.md` + 删 CLAUDE.md 里 `@totalrecall-rules.md` 那行。
- **清空数据**:删除 `~/.totalrecall/` 整个目录。
- **卸载包**:`python -m pip uninstall totalrecall`。

---

## 11. 故障排查

| 现象 | 原因 / 处理 |
|------|------------|
| `totalrecall: command not found` | 用 `python -m totalrecall.cli <cmd>`;或确认 pip 的 scripts 目录在 PATH |
| `status` 后 `pending` > 0 | 有会话分析失败(多为 `claude` 限流/未登录)。`claude login` 后 `totalrecall retry` |
| 分析很慢 | `claude` 限流。临时切 Haiku(§6),或减少并发(回填本就串行) |
| `insights.md` 没更新 | 它在 worker drain 完整批后才渲染;`totalrecall worker` 手动跑一次 |
| hook 没触发 | 确认 `~/.claude/settings.json` 含 SessionEnd → `totalrecall hook`;重跑 `totalrecall init`(幂等) |
| OpenCode 报错 | 确认 `~/.local/share/opencode/opencode.db` 存在;导出是只读的,绝不写你的库 |

---

## 速查:最小部署(复制即用)

```bash
# 1) 解压后 cd 进目录
python -m pip install -e .
# 2) 初始化(装 hook)
totalrecall init
# 3) 验证
totalrecall status
# 完成。此后会话结束自动分析,看 ~/.totalrecall/insights.md
```

_部署完成后,日常无需任何操作。需要深入说明见 `README.md`。_
