# TotalRecall 协作摩擦分析报告

> 基于 **1460 个真实会话**(跨 83 个项目、3 个 AI 工具)的本地分析
> 数据来源:Claude Code · Codex · OpenCode · 生成于 2026-06-18

---

## 📌 一句话结论

> **你与 AI 协作中最大、最可立刻消除的摩擦,是「Windows 环境下 AI 反复用 Bash/类 Unix 命令,失败后再切回 PowerShell」**——它以多种形态反复出现上百次,且有现成的一行 CLAUDE.md 规则可根治。

---

## 📊 关键数字

| 指标 | 数值 |
|------|------|
| 已分析会话 | **1460** |
| 覆盖项目 | 83 |
| 沉淀的摩擦模式 | 310(其中**反复出现 ≥2 个会话的:54**) |
| 来源占比(带证据的模式) | OpenCode 239 · Codex 62 · Claude Code 46 |
| 分析错误率 | **0**(0 pending) |

**反复摩擦的类别分布:**

| 类别 | 数量 | 含义 |
|------|------|------|
| 🔧 tool-error | 27 | 工具调用失败/需重试(占一半) |
| ❓ clarification-gap | 10 | 动手前来回拉扯、范围不清 |
| 🎯 misunderstood-intent | 9 | AI 理解偏了你的意图 |
| 🚫 rule-violation | 7 | AI 违反了你已声明的规则 |
| 😤 frustration | 1 | 明显挫败/中断 |

---

## 🔎 三大主题(按"可立刻行动"排序)

### 主题一:Windows × Shell 错配 —— 最高频、最易根治 ⭐

这是贯穿三个工具的头号问题,以多种形态反复出现:

| 表现 | 出现次数 | 工具 |
|------|---------|------|
| 用 `Get-Content`/cat 直接读 skill 文件(而非 Skill 工具) | **×65** | 三者 |
| Windows 环境却用 `bash`/`grep` | ×20 | CC, OpenCode |
| Bash 工具用 Windows 批处理语法(`cd /d D:\...`) | ×8 | CC, OpenCode |
| Bash 工具做 git 操作 | ×5 | CC, OpenCode |
| Bash 跑 pytest 失败 | ×3 | CC |

**合计 100+ 次**,且每次都以"失败 → 再用 PowerShell 重来"收场,纯属可避免的返工。

**👉 结论:这一类靠 1-2 条 CLAUDE.md 规则即可大面积消除,是 ROI 最高的改进。**

---

### 主题二:输出/写入被截断 —— 影响交付质量

| 表现 | 出现次数 | 工具 |
|------|---------|------|
| 响应正文中途被截断(如分析到一半戛然而止) | **×45** | 三者 |
| Write 工具把 fixture 文件写截断(JSON 写到一半) | ×8 | CC, OpenCode |

**👉 结论:这是 tool/上下文层面的问题,不完全是规则能解决的;但可以加一条"写完关键文件后回读校验"的工作习惯规则来兜底。**

---

### 主题三:命令重试与范围沟通 —— 效率损耗

| 表现 | 出现次数 | 工具 |
|------|---------|------|
| RTK PowerShell 代理在非可执行 cmdlet 上反复失败 | ×26 | Codex |
| 同一信息用多种语法反复重查(没缓存上次结果) | ×12 | Codex |
| "只读 §X / 只实现 Task N"被理解成读全文 | ×2 | CC, OpenCode |
| 委派子 agent 后未核实产出文件 | ×3 | CC, OpenCode |

**👉 结论:偏流程/习惯类,适合用更明确的指令模板 + 子 agent 完成校验来改善。**

---

## ✅ 总体结论

1. **摩擦高度集中**:54 个反复模式里,**近半是 tool-error**,且很大一块是**同一个"Windows 用错 shell"根因**的不同马甲。解决根因 = 消除一大片。
2. **跨工具一致**:同样的摩擦在 Claude Code / Codex / OpenCode 都出现 → 说明是**你的工作环境 × AI 习惯**的系统性问题,不是某个工具的偶发。
3. **可治性强**:头部问题大多是 **rule-violation / 可预防的 tool-error**,正是 CLAUDE.md 规则的甜区。

---

## 🚀 下一步建议(从高到低 ROI)

### 第 1 步:消除 Windows shell 错配(强烈推荐,今天就做)

让 TotalRecall 自动起草规则并应用到 CLAUDE.md:

```bash
totalrecall propose            # 为 top 反复摩擦起草 CLAUDE.md 规则
#   打开 ~/.totalrecall/proposals.md 审阅(重点看 PowerShell/Skill 工具相关几条)
totalrecall apply <id...>      # 批准你认可的(写入 ~/.claude/totalrecall-rules.md,带备份、可回退)
```

预期生成的核心规则(基于数据):
- **「Windows 上默认用 PowerShell 工具;Bash 仅用于明确的 POSIX 脚本」** ← 一条管掉主题一的大半
- **「加载 skill 用 Skill 工具,绝不用 Read/Get-Content 直接读 skill 文件」** ← 管掉 ×65 那条

### 第 2 步:加一条"关键写入回读校验"习惯(中)

针对主题二的 fixture 截断:在 CLAUDE.md 里加"写完 JSONL/fixture 等关键文件后回读校验字节一致"。可手动加,或等 `propose` 起草。

### 第 3 步:验证规则是否真生效(闭环,自动)

应用规则后**什么都不用做**——继续正常用 AI。TotalRecall 会在后续会话里自动判定:
- 该摩擦 N 天内不再出现 → 在 `insights.md` 标 **✅ 已解决**
- 仍然复发 → 标 **⚠️ 修复无效**(提示你换个规则写法)

随时 `totalrecall status` 看进展,打开 `~/.totalrecall/insights.md` 看完整档案。

### 第 4 步(可选):降噪

当前 310 个模式里有 256 个一次性长尾(多为各会话独有、不构成可操作模式)。已聚焦在"反复出现"区;若想进一步合并近似项,随时 `totalrecall synth`。

---

## 📁 数据出处

- 完整档案:`~/.totalrecall/insights.md`(随新会话持续刷新)
- 模式库:`~/.totalrecall/patterns/*.json`(每条摩擦可溯源到具体会话证据,标 `tool=claude-code|codex|opencode`)
- 本报告为某一时点快照;TotalRecall 持续增量学习,数字会变化。

---

_由 TotalRecall 生成 · Phase 1 洞察 + Phase 2 规则闭环 · 支持 Claude Code / Codex / OpenCode 三来源_
