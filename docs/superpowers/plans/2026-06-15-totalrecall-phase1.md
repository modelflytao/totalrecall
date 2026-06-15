# TotalRecall Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Python tool that, after each Claude Code session ends, extracts AI-collaboration *friction* signals from the transcript and maintains a continuously-updated `insights.md`.

**Architecture:** Thin Python CLI (deterministic plumbing: parse → events → ledger → merge → render) + an LLM analysis step invoked via headless `claude -p` (semantic friction). A file-based queue + single worker process the work; a SessionEnd hook and a reconcile scan feed the queue. Self-produced analysis sessions are excluded at two layers to prevent recursion.

**Tech Stack:** Python 3.11+ (stdlib `tomllib`, `dataclasses`, `difflib`, `hashlib`), `filelock` (cross-platform lock), `pytest` (dev). State lives in `~/.totalrecall/` (overridable via `TOTALRECALL_HOME` for tests). Analysis driven by the user's installed `claude` CLI.

**Spec:** `docs/superpowers/specs/2026-06-15-totalrecall-design.md` (r2).

---

## File Structure

```
pyproject.toml
src/totalrecall/
  __init__.py          # __version__
  paths.py             # state dir resolution (TOTALRECALL_HOME override)
  config.py            # defaults + load config.toml + render default toml
  models.py            # dataclasses + dict (de)serialization
  adapters/
    __init__.py
    base.py            # Adapter protocol
    claude_code.py     # JSONL -> NormalizedSession (+ is_analysis_session)
  events.py            # A-class deterministic events/stats
  ledger.py            # idempotency: content hash + pending state
  locking.py           # file lock helper (filelock)
  queue.py             # file-based enqueue/dequeue
  patterns_store.py    # patterns/*.json + index.json CRUD
  strength.py          # render-time strength (freq x recency-decay x severity) + status
  merger.py            # Finding[] -> Pattern store
  catalog.py           # compact top-K pattern catalog for the skill
  render.py            # insights.md renderer
  orchestrator.py      # build prompt, call claude -p (injectable runner), parse Finding[]
  reconcile.py         # scan projects dir vs ledger, enqueue stragglers
  worker.py            # drain-loop, single-worker lock, per-item pipeline, synth-every-N
  synth.py             # periodic consolidation + narrative rewrite (claude -p)
  hookinstall.py       # init: scaffold state, merge SessionEnd hook into settings.json
  cli.py               # argparse: init/ingest/worker/reconcile/synth/status/retry/hook
skills/totalrecall-analyze/
  SKILL.md             # analysis instructions + Finding JSON schema (read by orchestrator)
tests/
  conftest.py          # tmp TOTALRECALL_HOME fixture
  fixtures/*.jsonl     # hand-crafted transcripts
  test_*.py
```

Each module has one responsibility. Types are defined once in `models.py` and reused everywhere.

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/totalrecall/__init__.py`
- Create: `tests/conftest.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

`tests/test_smoke.py`:
```python
import totalrecall

def test_version_present():
    assert isinstance(totalrecall.__version__, str)
    assert totalrecall.__version__
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'totalrecall'`

- [ ] **Step 3: Create package + packaging**

`src/totalrecall/__init__.py`:
```python
__version__ = "0.1.0"
```

`pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "totalrecall"
version = "0.1.0"
description = "Learn from your AI-tool sessions: detect collaboration friction, maintain a living insights doc."
requires-python = ">=3.11"
dependencies = ["filelock>=3.13"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
totalrecall = "totalrecall.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

`tests/conftest.py`:
```python
import os
import pytest

@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated ~/.totalrecall for each test."""
    h = tmp_path / "trhome"
    h.mkdir()
    monkeypatch.setenv("TOTALRECALL_HOME", str(h))
    return h
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pip install -e ".[dev]" && pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/totalrecall/__init__.py tests/conftest.py tests/test_smoke.py
git commit -m "chore: scaffold totalrecall package + pytest"
```

---

## Task 2: Paths

**Files:**
- Create: `src/totalrecall/paths.py`
- Test: `tests/test_paths.py`

- [ ] **Step 1: Write the failing test**

`tests/test_paths.py`:
```python
from pathlib import Path
from totalrecall import paths

def test_home_uses_env_override(home):
    assert paths.state_dir() == home
    assert paths.queue_dir() == home / "queue"
    assert paths.ledger_path() == home / "ledger.json"
    assert paths.patterns_dir() == home / "patterns"
    assert paths.insights_path() == home / "insights.md"
    assert paths.config_path() == home / "config.toml"

def test_ensure_dirs_creates_layout(home):
    paths.ensure_dirs()
    assert paths.queue_dir().is_dir()
    assert paths.patterns_dir().is_dir()

def test_default_home_without_env(monkeypatch):
    monkeypatch.delenv("TOTALRECALL_HOME", raising=False)
    assert paths.state_dir() == Path.home() / ".totalrecall"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'totalrecall.paths'`

- [ ] **Step 3: Implement**

`src/totalrecall/paths.py`:
```python
from __future__ import annotations
import os
from pathlib import Path


def state_dir() -> Path:
    override = os.environ.get("TOTALRECALL_HOME")
    return Path(override) if override else Path.home() / ".totalrecall"


def queue_dir() -> Path:
    return state_dir() / "queue"


def ledger_path() -> Path:
    return state_dir() / "ledger.json"


def patterns_dir() -> Path:
    return state_dir() / "patterns"


def patterns_index_path() -> Path:
    return patterns_dir() / "index.json"


def insights_path() -> Path:
    return state_dir() / "insights.md"


def config_path() -> Path:
    return state_dir() / "config.toml"


def log_path() -> Path:
    return state_dir() / "log"


def analysis_cwd() -> Path:
    """Dedicated cwd for headless analysis sessions (used for self-exclusion)."""
    return state_dir() / "analysis"


def ensure_dirs() -> None:
    for d in (state_dir(), queue_dir(), patterns_dir(), analysis_cwd()):
        d.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_paths.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/paths.py tests/test_paths.py
git commit -m "feat: state path resolution with TOTALRECALL_HOME override"
```

---

## Task 3: Config

**Files:**
- Create: `src/totalrecall/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
from totalrecall import config, paths

def test_defaults_when_no_file(home):
    cfg = config.load()
    assert cfg.extract_model == "claude-sonnet-4-6"
    assert cfg.synth_model == "claude-sonnet-4-6"
    assert cfg.synth_every_n_sessions == 20
    assert cfg.catalog_topk == 40
    assert cfg.sources["claude_code"] is True
    assert cfg.analysis_marker_env == "TOTALRECALL_ANALYSIS"

def test_file_overrides_defaults(home):
    paths.ensure_dirs()
    paths.config_path().write_text(
        '[models]\nextract = "claude-haiku-4-5-20251001"\n'
        '[limits]\nsynth_every_n_sessions = 5\n',
        encoding="utf-8",
    )
    cfg = config.load()
    assert cfg.extract_model == "claude-haiku-4-5-20251001"
    assert cfg.synth_every_n_sessions == 5
    assert cfg.synth_model == "claude-sonnet-4-6"  # untouched default

def test_default_toml_text_parses(home):
    text = config.default_toml()
    assert "[models]" in text and "claude-sonnet-4-6" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'totalrecall.config'`

- [ ] **Step 3: Implement**

`src/totalrecall/config.py`:
```python
from __future__ import annotations
import tomllib
from dataclasses import dataclass, field
from . import paths


@dataclass
class Config:
    extract_model: str = "claude-sonnet-4-6"
    synth_model: str = "claude-sonnet-4-6"
    max_input_tokens: int = 20000
    synth_every_n_sessions: int = 20
    catalog_topk: int = 40
    sources: dict = field(default_factory=lambda: {
        "claude_code": True, "codex": False, "opencode": False})
    store_snippets: bool = False
    analysis_marker_env: str = "TOTALRECALL_ANALYSIS"


def load() -> Config:
    cfg = Config()
    p = paths.config_path()
    if not p.exists():
        return cfg
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    models = data.get("models", {})
    cfg.extract_model = models.get("extract", cfg.extract_model)
    cfg.synth_model = models.get("synth", cfg.synth_model)
    limits = data.get("limits", {})
    cfg.max_input_tokens = limits.get("max_input_tokens", cfg.max_input_tokens)
    cfg.synth_every_n_sessions = limits.get("synth_every_n_sessions", cfg.synth_every_n_sessions)
    cfg.catalog_topk = limits.get("catalog_topk", cfg.catalog_topk)
    cfg.sources = {**cfg.sources, **data.get("sources", {})}
    cfg.store_snippets = data.get("privacy", {}).get("store_snippets", cfg.store_snippets)
    cfg.analysis_marker_env = data.get("internal", {}).get(
        "analysis_marker_env", cfg.analysis_marker_env)
    return cfg


def default_toml() -> str:
    return (
        "[models]\n"
        'extract = "claude-sonnet-4-6"   # per-session semantic extraction; Haiku is a cost lever, evaluate first\n'
        'synth   = "claude-sonnet-4-6"   # periodic synthesis (can raise to claude-opus-4-8)\n\n'
        "[limits]\n"
        "max_input_tokens = 20000\n"
        "synth_every_n_sessions = 20\n"
        "catalog_topk = 40\n\n"
        "[sources]\n"
        "claude_code = true\n"
        "codex = false\n"
        "opencode = false\n\n"
        "[privacy]\n"
        "store_snippets = false\n\n"
        "[internal]\n"
        'analysis_marker_env = "TOTALRECALL_ANALYSIS"\n'
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/config.py tests/test_config.py
git commit -m "feat: config defaults + toml loading"
```

---

## Task 4: Models

**Files:**
- Create: `src/totalrecall/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:
```python
from totalrecall.models import (
    Turn, Event, Stats, NormalizedSession, Evidence, Finding, Pattern,
    pattern_to_dict, pattern_from_dict, finding_from_dict,
)

def test_pattern_roundtrip():
    p = Pattern(
        id="pwsh-vs-bash", title="Use PowerShell not bash", category="repeated-correction",
        source="llm", description="...", first_seen="2026-06-01T00:00:00Z",
        last_seen="2026-06-10T00:00:00Z", occurrences=3, severity=4,
        evidence=[Evidence("s1", "claude-code", [4, 5], "2026-06-10T00:00:00Z", "abc")],
    )
    d = pattern_to_dict(p)
    p2 = pattern_from_dict(d)
    assert p2 == p

def test_finding_from_dict_defaults():
    f = finding_from_dict({
        "category": "tool-error", "description": "x", "severity": 2,
        "evidence": {"session_id": "s1", "tool": "claude-code",
                     "turn_refs": [1], "ts": None, "snippet_hash": "h"},
    })
    assert f.pattern_id is None and f.slug is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/totalrecall/models.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Turn:
    idx: int
    role: str                      # "user" | "assistant" | "tool"
    ts: Optional[str]
    text: str = ""
    tool_name: Optional[str] = None
    tool_status: Optional[str] = None   # "ok" | "error"
    is_meta: bool = False
    is_sidechain: bool = False


@dataclass
class Event:
    kind: str                      # edit|revert|permission_denied|tool_error|interrupt|churn
    ts: Optional[str]
    ref: str


@dataclass
class Stats:
    n_turns: int = 0
    duration_s: float = 0.0
    n_tool_errors: int = 0
    n_edits: int = 0
    n_reverts: int = 0


@dataclass
class NormalizedSession:
    tool: str
    session_id: str
    cwd: str
    git_branch: Optional[str]
    started_at: Optional[str]
    ended_at: Optional[str]
    is_analysis_session: bool
    turns: list[Turn] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    stats: Stats = field(default_factory=Stats)


@dataclass
class Evidence:
    session_id: str
    tool: str
    turn_refs: list[int]
    ts: Optional[str]
    snippet_hash: str


@dataclass
class Finding:
    category: str
    description: str
    severity: int                  # 1..5
    evidence: Evidence
    pattern_id: Optional[str] = None
    slug: Optional[str] = None
    phase2_hint: Optional[str] = None


@dataclass
class Pattern:
    id: str
    title: str
    category: str
    source: str                    # metadata|llm|both
    description: str
    first_seen: str
    last_seen: str
    occurrences: int
    severity: int = 1
    evidence: list[Evidence] = field(default_factory=list)
    status: str = "active"         # active|fading|resolved
    phase2_hint: Optional[str] = None


def evidence_from_dict(d: dict) -> Evidence:
    return Evidence(d["session_id"], d["tool"], list(d["turn_refs"]),
                    d.get("ts"), d["snippet_hash"])


def finding_from_dict(d: dict) -> Finding:
    return Finding(
        category=d["category"], description=d["description"], severity=int(d["severity"]),
        evidence=evidence_from_dict(d["evidence"]),
        pattern_id=d.get("pattern_id"), slug=d.get("slug"), phase2_hint=d.get("phase2_hint"),
    )


def pattern_to_dict(p: Pattern) -> dict:
    return asdict(p)


def pattern_from_dict(d: dict) -> Pattern:
    return Pattern(
        id=d["id"], title=d["title"], category=d["category"], source=d["source"],
        description=d["description"], first_seen=d["first_seen"], last_seen=d["last_seen"],
        occurrences=int(d["occurrences"]), severity=int(d.get("severity", 1)),
        evidence=[evidence_from_dict(e) for e in d.get("evidence", [])],
        status=d.get("status", "active"), phase2_hint=d.get("phase2_hint"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/models.py tests/test_models.py
git commit -m "feat: core dataclasses (Turn/Event/NormalizedSession/Finding/Pattern)"
```

---

## Task 5: Claude Code adapter

**Files:**
- Create: `src/totalrecall/adapters/__init__.py` (empty)
- Create: `src/totalrecall/adapters/base.py`
- Create: `src/totalrecall/adapters/claude_code.py`
- Create: `tests/fixtures/cc_basic.jsonl`
- Create: `tests/fixtures/cc_analysis.jsonl`
- Test: `tests/test_claude_code_adapter.py`

- [ ] **Step 1: Write the fixtures**

`tests/fixtures/cc_basic.jsonl` (one JSON object per line — keep exactly these lines):
```
{"type":"user","isMeta":false,"isSidechain":false,"timestamp":"2026-06-10T10:00:00Z","cwd":"/home/u/proj","sessionId":"s1","gitBranch":"main","message":{"role":"user","content":"please use PowerShell not bash"}}
{"type":"assistant","isSidechain":false,"timestamp":"2026-06-10T10:00:05Z","cwd":"/home/u/proj","sessionId":"s1","gitBranch":"main","message":{"role":"assistant","content":[{"type":"text","text":"ok"},{"type":"tool_use","id":"t1","name":"Edit","input":{"file_path":"a.py"}}]}}
{"type":"user","isMeta":false,"isSidechain":false,"timestamp":"2026-06-10T10:00:06Z","cwd":"/home/u/proj","sessionId":"s1","gitBranch":"main","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t1","content":"done"}]}}
{"type":"assistant","isSidechain":false,"timestamp":"2026-06-10T10:00:08Z","cwd":"/home/u/proj","sessionId":"s1","gitBranch":"main","message":{"role":"assistant","content":[{"type":"tool_use","id":"t2","name":"Bash","input":{"command":"ls"}}]}}
{"type":"user","isMeta":false,"isSidechain":false,"timestamp":"2026-06-10T10:00:09Z","cwd":"/home/u/proj","sessionId":"s1","gitBranch":"main","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t2","content":"err","is_error":true}]}}
{"type":"user","isMeta":true,"isSidechain":false,"timestamp":"2026-06-10T10:00:10Z","cwd":"/home/u/proj","sessionId":"s1","gitBranch":"main","message":{"role":"user","content":"<system-reminder>ignore me</system-reminder>"}}
{"type":"assistant","isSidechain":false,"timestamp":"2026-06-10T10:00:12Z","cwd":"/home/u/proj","sessionId":"s1","gitBranch":"main","message":{"role":"assistant","content":[{"type":"tool_use","id":"t3","name":"Edit","input":{"file_path":"a.py"}}]}}
not-json-garbage-line
```

`tests/fixtures/cc_analysis.jsonl` (cwd under a `.totalrecall/analysis` path → must be flagged analysis):
```
{"type":"user","isMeta":false,"isSidechain":false,"timestamp":"2026-06-10T11:00:00Z","cwd":"/home/u/.totalrecall/analysis","sessionId":"a1","gitBranch":null,"message":{"role":"user","content":"analyze this"}}
```

- [ ] **Step 2: Write the failing test**

`tests/test_claude_code_adapter.py`:
```python
from pathlib import Path
from totalrecall.adapters.claude_code import ClaudeCodeAdapter

FIX = Path(__file__).parent / "fixtures"

def test_parse_basic_turns_and_meta():
    s = ClaudeCodeAdapter().parse(FIX / "cc_basic.jsonl")
    assert s.tool == "claude-code"
    assert s.session_id == "s1"
    assert s.cwd == "/home/u/proj"
    assert s.git_branch == "main"
    assert s.is_analysis_session is False
    # user turns exclude isMeta and exclude tool_result-only user lines
    user_texts = [t.text for t in s.turns if t.role == "user"]
    assert "please use PowerShell not bash" in user_texts
    assert all("system-reminder" not in t for t in user_texts)  # meta excluded
    # tool turns captured with status
    tool_turns = [t for t in s.turns if t.role == "tool"]
    statuses = {t.tool_name: t.tool_status for t in tool_turns}
    assert statuses["Bash"] == "error"
    assert statuses["Edit"] == "ok"

def test_started_and_ended_timestamps():
    s = ClaudeCodeAdapter().parse(FIX / "cc_basic.jsonl")
    assert s.started_at == "2026-06-10T10:00:00Z"
    assert s.ended_at == "2026-06-10T10:00:12Z"

def test_is_analysis_session_by_cwd():
    s = ClaudeCodeAdapter().parse(FIX / "cc_analysis.jsonl")
    assert s.is_analysis_session is True

def test_garbage_lines_skipped_without_crash():
    s = ClaudeCodeAdapter().parse(FIX / "cc_basic.jsonl")
    assert len(s.turns) >= 4  # parsed despite trailing garbage line
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_claude_code_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'totalrecall.adapters.claude_code'`

- [ ] **Step 4: Implement**

`src/totalrecall/adapters/base.py`:
```python
from __future__ import annotations
from pathlib import Path
from typing import Protocol
from ..models import NormalizedSession


class Adapter(Protocol):
    tool: str

    def parse(self, path: Path) -> NormalizedSession: ...
```

`src/totalrecall/adapters/claude_code.py`:
```python
from __future__ import annotations
import json
from pathlib import Path
from ..models import NormalizedSession, Turn, Stats


def _text_from_content(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for item in content if isinstance(content, list) else []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
    return "\n".join(parts)


def _tool_uses(content):
    if not isinstance(content, list):
        return []
    return [i for i in content if isinstance(i, dict) and i.get("type") == "tool_use"]


def _tool_results(content):
    if not isinstance(content, list):
        return []
    return [i for i in content if isinstance(i, dict) and i.get("type") == "tool_result"]


class ClaudeCodeAdapter:
    tool = "claude-code"

    def parse(self, path: Path) -> NormalizedSession:
        session_id = cwd = git_branch = ""
        started_at = ended_at = None
        turns: list[Turn] = []
        is_analysis = False
        idx = 0

        for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                o = json.loads(raw)
            except json.JSONDecodeError:
                continue
            ts = o.get("timestamp")
            if ts:
                started_at = started_at or ts
                ended_at = ts
            session_id = o.get("sessionId") or session_id
            if o.get("cwd"):
                cwd = o["cwd"]
                if "/.totalrecall/analysis" in cwd.replace("\\", "/"):
                    is_analysis = True
            if "gitBranch" in o:
                git_branch = o.get("gitBranch")

            msg = o.get("message")
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = msg.get("content")
            is_meta = bool(o.get("isMeta"))
            is_side = bool(o.get("isSidechain"))

            if role == "assistant":
                txt = _text_from_content(content)
                if txt.strip():
                    turns.append(Turn(idx, "assistant", ts, text=txt,
                                      is_sidechain=is_side)); idx += 1
                for tu in _tool_uses(content):
                    turns.append(Turn(idx, "tool", ts, tool_name=tu.get("name"),
                                      tool_status="ok", is_sidechain=is_side,
                                      text=json.dumps(tu.get("input", {}))[:500]))
                    idx += 1
            elif role == "user":
                results = _tool_results(content)
                if results:
                    for tr in results:
                        status = "error" if tr.get("is_error") else "ok"
                        # attach error status to the most recent matching tool turn
                        for t in reversed(turns):
                            if t.role == "tool" and t.tool_status == "ok":
                                if status == "error":
                                    t.tool_status = "error"
                                break
                    continue  # tool_result user lines are not user-authored turns
                if is_meta:
                    continue
                txt = _text_from_content(content)
                if txt.strip():
                    turns.append(Turn(idx, "user", ts, text=txt, is_meta=False,
                                      is_sidechain=is_side)); idx += 1

        stats = Stats(n_turns=len(turns))
        return NormalizedSession(
            tool=self.tool, session_id=session_id, cwd=cwd, git_branch=git_branch or None,
            started_at=started_at, ended_at=ended_at, is_analysis_session=is_analysis,
            turns=turns, events=[], stats=stats,
        )
```

> Note: the tool_result→tool-turn error attachment above is a simplification (marks the latest still-ok tool turn). Task 6 recomputes `n_tool_errors` from turn statuses, so this is sufficient for Phase 1.

- [ ] **Step 5: Run tests, then commit**

Run: `pytest tests/test_claude_code_adapter.py -v`
Expected: PASS
```bash
git add src/totalrecall/adapters tests/test_claude_code_adapter.py tests/fixtures/cc_basic.jsonl tests/fixtures/cc_analysis.jsonl
git commit -m "feat: Claude Code transcript adapter -> NormalizedSession"
```

---

## Task 6: A-class event/stat extraction

**Files:**
- Create: `src/totalrecall/events.py`
- Test: `tests/test_events.py`

- [ ] **Step 1: Write the failing test**

`tests/test_events.py`:
```python
from totalrecall.models import NormalizedSession, Turn, Stats
from totalrecall.events import extract_events

def _sess(turns):
    return NormalizedSession("claude-code", "s1", "/p", "main",
                             "2026-06-10T10:00:00Z", "2026-06-10T10:05:00Z",
                             False, turns=turns, events=[], stats=Stats())

def test_tool_errors_counted():
    s = _sess([
        Turn(0, "tool", None, tool_name="Bash", tool_status="error"),
        Turn(1, "tool", None, tool_name="Bash", tool_status="ok"),
    ])
    extract_events(s)
    assert s.stats.n_tool_errors == 1
    assert any(e.kind == "tool_error" for e in s.events)

def test_edit_churn_same_file():
    s = _sess([
        Turn(0, "tool", None, tool_name="Edit", tool_status="ok", text='{"file_path": "a.py"}'),
        Turn(1, "tool", None, tool_name="Edit", tool_status="ok", text='{"file_path": "a.py"}'),
        Turn(2, "tool", None, tool_name="Write", tool_status="ok", text='{"file_path": "a.py"}'),
        Turn(3, "tool", None, tool_name="Edit", tool_status="ok", text='{"file_path": "b.py"}'),
    ])
    extract_events(s)
    assert s.stats.n_edits == 4
    churn = [e for e in s.events if e.kind == "churn"]
    assert len(churn) == 1 and churn[0].ref == "a.py"  # a.py edited 3x -> churn; b.py once -> no

def test_duration_seconds():
    s = _sess([Turn(0, "user", None)])
    extract_events(s)
    assert s.stats.duration_s == 300.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_events.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/totalrecall/events.py`:
```python
from __future__ import annotations
import json
from collections import Counter
from datetime import datetime
from .models import NormalizedSession, Event

CHURN_THRESHOLD = 3      # same file edited >= 3 times in a session = churn
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}


def _parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _file_path(turn) -> str | None:
    try:
        return json.loads(turn.text or "{}").get("file_path")
    except json.JSONDecodeError:
        return None


def extract_events(session: NormalizedSession) -> None:
    """Populate session.events (A-class) and session.stats in place."""
    events: list[Event] = []
    n_tool_errors = 0
    n_edits = 0
    file_counts: Counter[str] = Counter()

    for t in session.turns:
        if t.role != "tool":
            continue
        if t.tool_status == "error":
            n_tool_errors += 1
            events.append(Event("tool_error", t.ts, t.tool_name or "?"))
        if t.tool_name in EDIT_TOOLS:
            n_edits += 1
            fp = _file_path(t)
            if fp:
                file_counts[fp] += 1

    for fp, count in file_counts.items():
        if count >= CHURN_THRESHOLD:
            events.append(Event("churn", None, fp))

    start = _parse_ts(session.started_at)
    end = _parse_ts(session.ended_at)
    duration = (end - start).total_seconds() if start and end else 0.0

    session.events = events
    session.stats.n_turns = len(session.turns)
    session.stats.n_tool_errors = n_tool_errors
    session.stats.n_edits = n_edits
    session.stats.duration_s = duration
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_events.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/events.py tests/test_events.py
git commit -m "feat: deterministic A-class event/stat extraction"
```

---

## Task 7: Ledger (idempotency)

**Files:**
- Create: `src/totalrecall/ledger.py`
- Test: `tests/test_ledger.py`

- [ ] **Step 1: Write the failing test**

`tests/test_ledger.py`:
```python
from totalrecall import ledger, paths

def test_unseen_then_seen(home):
    paths.ensure_dirs()
    p = home / "t.jsonl"
    p.write_text("hello", encoding="utf-8")
    lg = ledger.Ledger.load()
    assert lg.is_new(p) is True
    lg.mark_done("s1", p)
    lg.save()
    lg2 = ledger.Ledger.load()
    assert lg2.is_new(p) is False           # same content -> not new

def test_changed_content_is_new_again(home):
    paths.ensure_dirs()
    p = home / "t.jsonl"
    p.write_text("hello", encoding="utf-8")
    lg = ledger.Ledger.load()
    lg.mark_done("s1", p); lg.save()
    p.write_text("hello world", encoding="utf-8")   # grew
    assert ledger.Ledger.load().is_new(p) is True

def test_pending_roundtrip(home):
    paths.ensure_dirs()
    lg = ledger.Ledger.load()
    lg.mark_pending("s9", "/path/x.jsonl"); lg.save()
    assert ("s9", "/path/x.jsonl") in ledger.Ledger.load().pending_items()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ledger.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/totalrecall/ledger.py`:
```python
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from . import paths


def _hash_file(p: Path) -> str:
    h = hashlib.sha1()
    h.update(Path(p).read_bytes())
    return h.hexdigest()


class Ledger:
    def __init__(self, done: dict, pending: dict):
        self._done = done        # session_id -> {"hash":..., "path":...}
        self._pending = pending  # session_id -> path

    @classmethod
    def load(cls) -> "Ledger":
        p = paths.ledger_path()
        if not p.exists():
            return cls({}, {})
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(data.get("done", {}), data.get("pending", {}))

    def save(self) -> None:
        paths.ensure_dirs()
        paths.ledger_path().write_text(
            json.dumps({"done": self._done, "pending": self._pending}, indent=2),
            encoding="utf-8")

    def is_new(self, path) -> bool:
        path = Path(path)
        cur = _hash_file(path)
        for rec in self._done.values():
            if rec.get("path") == str(path) and rec.get("hash") == cur:
                return False
        return True

    def mark_done(self, session_id: str, path) -> None:
        self._done[session_id] = {"hash": _hash_file(Path(path)), "path": str(path)}
        self._pending.pop(session_id, None)

    def mark_pending(self, session_id: str, path: str) -> None:
        self._pending[session_id] = str(path)

    def pending_items(self):
        return [(sid, p) for sid, p in self._pending.items()]

    def done_paths(self) -> set[str]:
        return {rec["path"] for rec in self._done.values()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ledger.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/ledger.py tests/test_ledger.py
git commit -m "feat: ledger for idempotent/incremental ingest"
```

---

## Task 8: Locking + file queue

**Files:**
- Create: `src/totalrecall/locking.py`
- Create: `src/totalrecall/queue.py`
- Test: `tests/test_queue.py`

- [ ] **Step 1: Write the failing test**

`tests/test_queue.py`:
```python
from totalrecall import queue, paths

def test_enqueue_dequeue_fifo(home):
    paths.ensure_dirs()
    queue.enqueue("/a.jsonl")
    queue.enqueue("/b.jsonl")
    assert queue.size() == 2
    items = queue.drain()
    assert items == ["/a.jsonl", "/b.jsonl"]
    assert queue.size() == 0

def test_enqueue_dedupes_same_path(home):
    paths.ensure_dirs()
    queue.enqueue("/a.jsonl")
    queue.enqueue("/a.jsonl")
    assert queue.size() == 1

def test_worker_lock_is_exclusive(home):
    paths.ensure_dirs()
    with queue.worker_lock() as got:
        assert got is True
        with queue.worker_lock() as second:
            assert second is False   # already held in-process (non-blocking)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_queue.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/totalrecall/locking.py`:
```python
from __future__ import annotations
from contextlib import contextmanager
from filelock import FileLock, Timeout
from . import paths


@contextmanager
def try_worker_lock():
    """Yield True if we acquired the singleton worker lock, else False."""
    paths.ensure_dirs()
    lock = FileLock(str(paths.state_dir() / "worker.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        yield False
        return
    try:
        yield True
    finally:
        lock.release()
```

`src/totalrecall/queue.py`:
```python
from __future__ import annotations
import hashlib
from . import paths
from .locking import try_worker_lock

worker_lock = try_worker_lock


def _name_for(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8")).hexdigest() + ".job"


def enqueue(transcript_path: str) -> None:
    paths.ensure_dirs()
    job = paths.queue_dir() / _name_for(transcript_path)
    if not job.exists():
        job.write_text(transcript_path, encoding="utf-8")


def size() -> int:
    return len(list(paths.queue_dir().glob("*.job"))) if paths.queue_dir().exists() else 0


def drain() -> list[str]:
    """Return queued paths (FIFO by mtime) and remove their job files."""
    if not paths.queue_dir().exists():
        return []
    jobs = sorted(paths.queue_dir().glob("*.job"), key=lambda p: p.stat().st_mtime)
    out = []
    for j in jobs:
        out.append(j.read_text(encoding="utf-8"))
        j.unlink()
    return out
```

> The FIFO test relies on enqueue order == mtime order; `enqueue` writes files sequentially so this holds. If two enqueues land in the same mtime tick on some filesystems, order between them is unspecified but both are still processed — acceptable.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_queue.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/locking.py src/totalrecall/queue.py tests/test_queue.py
git commit -m "feat: file-based queue + singleton worker lock"
```

---

## Task 9: Pattern store

**Files:**
- Create: `src/totalrecall/patterns_store.py`
- Test: `tests/test_patterns_store.py`

- [ ] **Step 1: Write the failing test**

`tests/test_patterns_store.py`:
```python
from totalrecall import patterns_store, paths
from totalrecall.models import Pattern, Evidence

def _p(pid="x"):
    return Pattern(pid, "T", "tool-error", "llm", "d",
                   "2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z", 1, 2,
                   evidence=[Evidence("s1", "claude-code", [1], None, "h1")])

def test_save_and_load(home):
    paths.ensure_dirs()
    patterns_store.save(_p("alpha"))
    got = patterns_store.get("alpha")
    assert got.id == "alpha" and got.occurrences == 1

def test_all_and_index(home):
    paths.ensure_dirs()
    patterns_store.save(_p("alpha"))
    patterns_store.save(_p("beta"))
    ids = {p.id for p in patterns_store.all()}
    assert ids == {"alpha", "beta"}
    assert set(patterns_store.index_ids()) == {"alpha", "beta"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_patterns_store.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/totalrecall/patterns_store.py`:
```python
from __future__ import annotations
import json
from . import paths
from .models import Pattern, pattern_to_dict, pattern_from_dict


def _path_for(pid: str):
    return paths.patterns_dir() / f"{pid}.json"


def save(p: Pattern) -> None:
    paths.ensure_dirs()
    _path_for(p.id).write_text(json.dumps(pattern_to_dict(p), indent=2,
                                          ensure_ascii=False), encoding="utf-8")
    _rebuild_index()


def get(pid: str) -> Pattern | None:
    fp = _path_for(pid)
    if not fp.exists():
        return None
    return pattern_from_dict(json.loads(fp.read_text(encoding="utf-8")))


def all() -> list[Pattern]:
    if not paths.patterns_dir().exists():
        return []
    out = []
    for fp in paths.patterns_dir().glob("*.json"):
        if fp.name == "index.json":
            continue
        out.append(pattern_from_dict(json.loads(fp.read_text(encoding="utf-8"))))
    return out


def index_ids() -> list[str]:
    fp = paths.patterns_index_path()
    if not fp.exists():
        return []
    return json.loads(fp.read_text(encoding="utf-8")).get("ids", [])


def _rebuild_index() -> None:
    ids = sorted(p.id for p in all())
    paths.patterns_index_path().write_text(
        json.dumps({"ids": ids}, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_patterns_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/patterns_store.py tests/test_patterns_store.py
git commit -m "feat: JSON pattern store + index"
```

---

## Task 10: Strength + status (render-time)

**Files:**
- Create: `src/totalrecall/strength.py`
- Test: `tests/test_strength.py`

- [ ] **Step 1: Write the failing test**

`tests/test_strength.py`:
```python
from datetime import datetime, timezone
from totalrecall.models import Pattern
from totalrecall.strength import strength, derive_status

NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)

def _p(occ, last, sev=3, status="active"):
    return Pattern("x", "T", "c", "llm", "d", "2026-06-01T00:00:00Z", last, occ, sev,
                   status=status)

def test_more_occurrences_more_strength():
    a = strength(_p(1, "2026-06-15T00:00:00Z"), NOW)
    b = strength(_p(5, "2026-06-15T00:00:00Z"), NOW)
    assert b > a

def test_recency_decay():
    fresh = strength(_p(3, "2026-06-15T00:00:00Z"), NOW)
    stale = strength(_p(3, "2026-05-01T00:00:00Z"), NOW)
    assert fresh > stale

def test_status_fading_when_old():
    assert derive_status(_p(3, "2026-06-14T00:00:00Z"), NOW) == "active"
    assert derive_status(_p(3, "2026-04-01T00:00:00Z"), NOW) == "fading"

def test_resolved_status_sticky():
    assert derive_status(_p(3, "2026-06-14T00:00:00Z", status="resolved"), NOW) == "resolved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_strength.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/totalrecall/strength.py`:
```python
from __future__ import annotations
import math
from datetime import datetime, timezone
from .models import Pattern

HALF_LIFE_DAYS = 14.0
FADING_DAYS = 30


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _days_since(ts: str, now: datetime) -> float:
    return max(0.0, (now - _parse(ts)).total_seconds() / 86400.0)


def strength(p: Pattern, now: datetime) -> float:
    recency = math.exp(-_days_since(p.last_seen, now) / HALF_LIFE_DAYS)
    return p.occurrences * recency * (p.severity / 5.0)


def derive_status(p: Pattern, now: datetime) -> str:
    if p.status == "resolved":
        return "resolved"
    return "fading" if _days_since(p.last_seen, now) > FADING_DAYS else "active"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_strength.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/strength.py tests/test_strength.py
git commit -m "feat: render-time strength + status with time decay"
```

---

## Task 11: Merger (Finding[] -> Pattern)

**Files:**
- Create: `src/totalrecall/merger.py`
- Test: `tests/test_merger.py`

- [ ] **Step 1: Write the failing test**

`tests/test_merger.py`:
```python
from totalrecall import merger, patterns_store, paths
from totalrecall.models import Finding, Evidence

def _f(pattern_id=None, slug=None, title_desc="Use PowerShell not bash", sid="s1", h="h1"):
    return Finding(category="repeated-correction", description=title_desc, severity=3,
                   evidence=Evidence(sid, "claude-code", [4], "2026-06-10T00:00:00Z", h),
                   pattern_id=pattern_id, slug=slug)

NOW = "2026-06-10T00:00:00Z"

def test_new_pattern_created_from_slug(home):
    paths.ensure_dirs()
    merger.merge([_f(slug="pwsh-vs-bash")], now=NOW)
    p = patterns_store.get("pwsh-vs-bash")
    assert p is not None and p.occurrences == 1

def test_reuse_pattern_id_increments(home):
    paths.ensure_dirs()
    merger.merge([_f(slug="pwsh-vs-bash")], now=NOW)
    merger.merge([_f(pattern_id="pwsh-vs-bash", sid="s2", h="h2")], now="2026-06-11T00:00:00Z")
    p = patterns_store.get("pwsh-vs-bash")
    assert p.occurrences == 2 and len(p.evidence) == 2
    assert p.last_seen == "2026-06-11T00:00:00Z"

def test_evidence_hash_dedup(home):
    paths.ensure_dirs()
    merger.merge([_f(slug="pwsh-vs-bash", h="same")], now=NOW)
    merger.merge([_f(pattern_id="pwsh-vs-bash", h="same")], now=NOW)  # same evidence hash
    p = patterns_store.get("pwsh-vs-bash")
    assert p.occurrences == 1 and len(p.evidence) == 1   # deduped, not counted twice

def test_fuzzy_title_match_when_no_id(home):
    paths.ensure_dirs()
    merger.merge([_f(slug="pwsh-vs-bash", title_desc="Use PowerShell not bash")], now=NOW)
    # near-identical description, different slug, no pattern_id -> should merge, not create new
    merger.merge([_f(slug="use-powershell", title_desc="Use PowerShell, not bash", h="h2")], now=NOW)
    assert len(patterns_store.all()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_merger.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/totalrecall/merger.py`:
```python
from __future__ import annotations
import re
from difflib import SequenceMatcher
from .models import Finding, Pattern
from . import patterns_store

SIM_THRESHOLD = 0.82


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s or "pattern")[:60]


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _find_target(f: Finding, existing: list[Pattern]) -> Pattern | None:
    if f.pattern_id:
        for p in existing:
            if p.id == f.pattern_id:
                return p
    slug = f.slug or _slugify(f.description)
    for p in existing:
        if p.id == slug:
            return p
    for p in existing:
        if _similar(p.description, f.description) >= SIM_THRESHOLD:
            return p
    return None


def _apply(p: Pattern, f: Finding, now: str) -> None:
    if any(e.snippet_hash == f.evidence.snippet_hash for e in p.evidence):
        return  # duplicate evidence -> do not double-count
    p.occurrences += 1
    p.last_seen = now
    p.severity = max(p.severity, f.severity)
    p.evidence.append(f.evidence)
    if f.phase2_hint and not p.phase2_hint:
        p.phase2_hint = f.phase2_hint
    if p.source != f_source(f):
        p.source = "both"


def f_source(f: Finding) -> str:
    return "llm"


def merge(findings: list[Finding], now: str) -> None:
    for f in findings:
        existing = patterns_store.all()
        target = _find_target(f, existing)
        if target is None:
            pid = f.slug or _slugify(f.description)
            target = Pattern(
                id=pid, title=f.description[:80], category=f.category, source="llm",
                description=f.description, first_seen=now, last_seen=now,
                occurrences=0, severity=f.severity, evidence=[], phase2_hint=f.phase2_hint,
            )
        _apply(target, f, now)
        patterns_store.save(target)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_merger.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/merger.py tests/test_merger.py
git commit -m "feat: merge findings into patterns (id reuse, fuzzy match, hash dedup)"
```

---

## Task 12: Compact catalog

**Files:**
- Create: `src/totalrecall/catalog.py`
- Test: `tests/test_catalog.py`

- [ ] **Step 1: Write the failing test**

`tests/test_catalog.py`:
```python
from datetime import datetime, timezone
from totalrecall import catalog, patterns_store, paths
from totalrecall.models import Pattern

NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)

def _p(pid, occ, last):
    return Pattern(pid, f"title-{pid}", "c", "llm", f"desc-{pid}",
                   "2026-06-01T00:00:00Z", last, occ, 3)

def test_topk_orders_by_strength_and_truncates(home):
    paths.ensure_dirs()
    patterns_store.save(_p("weak", 1, "2026-05-01T00:00:00Z"))
    patterns_store.save(_p("strong", 9, "2026-06-15T00:00:00Z"))
    patterns_store.save(_p("mid", 3, "2026-06-14T00:00:00Z"))
    cat = catalog.build(top_k=2, now=NOW)
    assert [c["id"] for c in cat] == ["strong", "mid"]
    assert set(cat[0].keys()) == {"id", "title", "category", "description"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/totalrecall/catalog.py`:
```python
from __future__ import annotations
from datetime import datetime
from . import patterns_store
from .strength import strength


def build(top_k: int, now: datetime) -> list[dict]:
    ranked = sorted(patterns_store.all(), key=lambda p: strength(p, now), reverse=True)
    return [
        {"id": p.id, "title": p.title, "category": p.category,
         "description": p.description[:160]}
        for p in ranked[:top_k]
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_catalog.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/catalog.py tests/test_catalog.py
git commit -m "feat: compact top-K pattern catalog for the analysis skill"
```

---

## Task 13: Render insights.md

**Files:**
- Create: `src/totalrecall/render.py`
- Test: `tests/test_render.py`

- [ ] **Step 1: Write the failing test**

`tests/test_render.py`:
```python
from datetime import datetime, timezone
from totalrecall import render, patterns_store, paths
from totalrecall.models import Pattern, Evidence

NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)

def _p(pid, occ, hint=None):
    return Pattern(pid, f"Title {pid}", "repeated-correction", "llm", f"Desc {pid}",
                   "2026-06-01T00:00:00Z", "2026-06-14T00:00:00Z", occ, 3,
                   evidence=[Evidence("s1", "claude-code", [4], None, "h")], phase2_hint=hint)

def test_render_writes_sections_and_top_order(home):
    paths.ensure_dirs()
    patterns_store.save(_p("weak", 1))
    patterns_store.save(_p("strong", 8, hint="add CLAUDE.md rule"))
    render.write(now=NOW, n_sessions=12, n_projects=3)
    text = paths.insights_path().read_text(encoding="utf-8")
    assert "# TotalRecall" in text
    assert "已分析 12 个会话" in text
    assert "🔥" in text and "🧰" in text
    assert text.index("Title strong") < text.index("Title weak")   # by strength
    assert "add CLAUDE.md rule" in text                            # phase2 hint surfaced

def test_render_empty_store(home):
    paths.ensure_dirs()
    render.write(now=NOW, n_sessions=0, n_projects=0)
    assert paths.insights_path().exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_render.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/totalrecall/render.py`:
```python
from __future__ import annotations
from datetime import datetime
from . import patterns_store, paths
from .strength import strength, derive_status


def write(now: datetime, n_sessions: int, n_projects: int) -> None:
    patterns = sorted(patterns_store.all(), key=lambda p: strength(p, now), reverse=True)
    lines: list[str] = []
    lines.append("# TotalRecall — 你与 AI 的协作摩擦档案")
    lines.append(f"_最后更新 {now.isoformat()} · 已分析 {n_sessions} 个会话 · 跨 {n_projects} 个项目_")
    lines.append("")
    lines.append("## 🔥 当前最该处理的摩擦 (按 strength)")
    if not patterns:
        lines.append("_(还没有累积到摩擦模式)_")
    for i, p in enumerate(patterns[:10], 1):
        date = p.last_seen[:10]
        lines.append(f"{i}. **{p.title}** — {p.category} · 出现 {p.occurrences} 次 · 最近 {date}")
        lines.append(f"   {p.description}")
        refs = ", ".join(e.session_id for e in p.evidence[:5])
        hint = f"   建议(Phase 2): {p.phase2_hint}" if p.phase2_hint else ""
        lines.append(f"   证据: {refs}{hint}")
    lines.append("")
    lines.append("## 📈 趋势")
    active = [p for p in patterns if derive_status(p, now) == "active"]
    fading = [p for p in patterns if derive_status(p, now) == "fading"]
    lines.append(f"- 活跃模式 {len(active)} · 消退中 {len(fading)}")
    lines.append("")
    lines.append("## 🗂 全部模式 (按类别分组)")
    by_cat: dict[str, list] = {}
    for p in patterns:
        by_cat.setdefault(p.category, []).append(p)
    for cat, ps in sorted(by_cat.items()):
        lines.append(f"### {cat}")
        for p in ps:
            lines.append(f"- {p.title} (×{p.occurrences})")
    lines.append("")
    lines.append("## 🧰 给 Phase 2 的候选改进 (skill / agent / CLAUDE.md)")
    hints = [p for p in patterns if p.phase2_hint]
    if not hints:
        lines.append("_(暂无)_")
    for p in hints:
        lines.append(f"- **{p.title}** → {p.phase2_hint}")

    paths.ensure_dirs()
    paths.insights_path().write_text("\n".join(lines) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_render.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/render.py tests/test_render.py
git commit -m "feat: render insights.md from pattern store"
```

---

## Task 14: Analysis skill template

**Files:**
- Create: `skills/totalrecall-analyze/SKILL.md`
- Test: `tests/test_skill_template.py`

- [ ] **Step 1: Write the failing test**

`tests/test_skill_template.py`:
```python
from pathlib import Path

SKILL = Path("skills/totalrecall-analyze/SKILL.md")

def test_skill_exists_and_specifies_json_array_and_categories():
    text = SKILL.read_text(encoding="utf-8")
    assert "JSON array" in text
    for cat in ["misunderstood-intent", "repeated-correction", "clarification-gap",
                "rule-violation", "tool-error"]:
        assert cat in text
    assert "turn_refs" in text and "severity" in text
    # must instruct reuse of existing pattern ids
    assert "pattern_id" in text and "catalog" in text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_skill_template.py -v`
Expected: FAIL — `FileNotFoundError`

- [ ] **Step 3: Implement**

`skills/totalrecall-analyze/SKILL.md`:
```markdown
---
name: totalrecall-analyze
description: Analyze one normalized AI-coding session for collaboration friction, returning a JSON array of findings. Invoked headless by TotalRecall.
---

# TotalRecall — Session Friction Analyzer

You are given ONE normalized session (JSON) and a compact catalog of already-known
friction patterns. Detect **per-session friction instances** only. Do NOT judge whether
something is "recurring" — recurrence is computed downstream by accumulation.

## Input (provided in the prompt)
- `session`: { turns:[{idx,role,text,tool_name,tool_status}], events:[...], stats:{...} }
- `catalog`: [{ id, title, category, description }]  ← known patterns

## What to detect (categories)
- `misunderstood-intent` — assistant did X, user corrected to Y
- `repeated-correction` — user (re)states a constraint/preference (e.g. "use PowerShell not bash")
- `clarification-gap` — many back-and-forth turns before any action
- `rule-violation` — assistant broke a previously stated preference
- `tool-error` — notable failed tool use that caused rework
- `frustration` — explicit "that's wrong again" / visible frustration

## Reusing pattern ids (important)
For each finding, if it matches an existing catalog entry, set `pattern_id` to that
entry's `id`. Otherwise leave `pattern_id` null and propose a stable kebab-case `slug`.

## Output
Output ONLY a JSON array (no prose, no code fences). Each element:
```
{
  "category": "<one of the categories>",
  "description": "<one concise sentence>",
  "severity": <1-5>,
  "turn_refs": [<turn idx>, ...],
  "pattern_id": "<existing catalog id or null>",
  "slug": "<kebab-slug or null>",
  "phase2_hint": "<optional: concrete skill/CLAUDE.md/agent change, or null>"
}
```
If there is no friction, output `[]`.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_skill_template.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/totalrecall-analyze/SKILL.md tests/test_skill_template.py
git commit -m "feat: totalrecall-analyze skill template (prompt + finding schema)"
```

---

## Task 15: Orchestrator (claude -p driver)

**Files:**
- Create: `src/totalrecall/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

`tests/test_orchestrator.py`:
```python
import json
from totalrecall import orchestrator
from totalrecall.models import NormalizedSession, Turn, Stats

def _sess():
    return NormalizedSession("claude-code", "s1", "/p", "main",
                             "2026-06-10T10:00:00Z", "2026-06-10T10:05:00Z", False,
                             turns=[Turn(0, "user", "2026-06-10T10:00:00Z",
                                         text="use PowerShell not bash")],
                             events=[], stats=Stats(n_turns=1))

def _fake_runner_returns(findings):
    # mimic `claude -p --output-format json` envelope
    envelope = {"type": "result", "result": json.dumps(findings)}
    return lambda prompt, model, cwd, env: json.dumps(envelope)

def test_returns_findings_with_computed_snippet_hash(home):
    raw = [{"category": "repeated-correction", "description": "use pwsh not bash",
            "severity": 3, "turn_refs": [0], "pattern_id": None,
            "slug": "pwsh-vs-bash", "phase2_hint": None}]
    findings = orchestrator.analyze(_sess(), catalog=[], model="m",
                                    runner=_fake_runner_returns(raw))
    assert len(findings) == 1
    f = findings[0]
    assert f.slug == "pwsh-vs-bash"
    assert f.evidence.session_id == "s1"
    assert f.evidence.turn_refs == [0]
    assert f.evidence.snippet_hash  # deterministically computed by orchestrator, not the model

def test_handles_fenced_and_noisy_result(home):
    noisy = "Here you go:\n```json\n[]\n```"
    runner = lambda p, m, c, e: json.dumps({"type": "result", "result": noisy})
    assert orchestrator.analyze(_sess(), [], "m", runner=runner) == []

def test_sets_analysis_marker_env_and_cwd(home, monkeypatch):
    captured = {}
    def runner(prompt, model, cwd, env):
        captured["cwd"] = cwd
        captured["marker"] = env.get("TOTALRECALL_ANALYSIS")
        return json.dumps({"type": "result", "result": "[]"})
    orchestrator.analyze(_sess(), [], "m", runner=runner)
    assert captured["marker"] == "1"
    assert "analysis" in captured["cwd"].replace("\\", "/")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/totalrecall/orchestrator.py`:
```python
from __future__ import annotations
import hashlib
import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path
from . import paths, config
from .models import NormalizedSession, Finding, Evidence

SKILL_PATH = Path("skills/totalrecall-analyze/SKILL.md")


def _session_payload(s: NormalizedSession) -> dict:
    return {
        "session_id": s.session_id, "tool": s.tool,
        "turns": [{"idx": t.idx, "role": t.role, "text": t.text[:2000],
                   "tool_name": t.tool_name, "tool_status": t.tool_status}
                  for t in s.turns if not t.is_meta],
        "events": [asdict(e) for e in s.events],
        "stats": asdict(s.stats),
    }


def build_prompt(session: NormalizedSession, catalog: list[dict]) -> str:
    skill = SKILL_PATH.read_text(encoding="utf-8") if SKILL_PATH.exists() else ""
    payload = {"session": _session_payload(session), "catalog": catalog}
    return (skill + "\n\n# INPUT\n```json\n"
            + json.dumps(payload, ensure_ascii=False) + "\n```\n"
            + "\nReturn ONLY the JSON array of findings.")


def _extract_json_array(text: str):
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []


def _snippet_hash(session: NormalizedSession, turn_refs: list[int]) -> str:
    by_idx = {t.idx: t.text for t in session.turns}
    blob = "\n".join(by_idx.get(i, "") for i in turn_refs)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def default_runner(prompt: str, model: str, cwd: str, env: dict) -> str:
    proc = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "json", "--model", model],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=300,
    )
    return proc.stdout


def analyze(session: NormalizedSession, catalog: list[dict], model: str,
            runner=default_runner) -> list[Finding]:
    paths.ensure_dirs()
    prompt = build_prompt(session, catalog)
    env = dict(os.environ)
    env[config.load().analysis_marker_env] = "1"
    raw_stdout = runner(prompt, model, str(paths.analysis_cwd()), env)
    try:
        result_text = json.loads(raw_stdout).get("result", "")
    except json.JSONDecodeError:
        result_text = raw_stdout
    items = _extract_json_array(result_text)

    findings: list[Finding] = []
    for it in items:
        refs = [int(x) for x in it.get("turn_refs", [])]
        ev = Evidence(session_id=session.session_id, tool=session.tool, turn_refs=refs,
                      ts=session.ended_at, snippet_hash=_snippet_hash(session, refs))
        findings.append(Finding(
            category=it.get("category", "unknown"),
            description=it.get("description", ""),
            severity=int(it.get("severity", 1)),
            evidence=ev,
            pattern_id=it.get("pattern_id"),
            slug=it.get("slug"),
            phase2_hint=it.get("phase2_hint"),
        ))
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator builds prompt, drives claude -p, parses findings"
```

---

## Task 16: Reconcile scan

**Files:**
- Create: `src/totalrecall/reconcile.py`
- Test: `tests/test_reconcile.py`

- [ ] **Step 1: Write the failing test**

`tests/test_reconcile.py`:
```python
from totalrecall import reconcile, ledger, queue, paths

def test_enqueues_unseen_skips_done_and_analysis(home, tmp_path, monkeypatch):
    paths.ensure_dirs()
    projects = tmp_path / "projects"
    (projects / "proj-a").mkdir(parents=True)
    (projects / "analysis").mkdir(parents=True)
    new = projects / "proj-a" / "s1.jsonl"; new.write_text("x", encoding="utf-8")
    done = projects / "proj-a" / "s2.jsonl"; done.write_text("y", encoding="utf-8")
    skip = projects / "analysis" / "a1.jsonl"; skip.write_text("z", encoding="utf-8")

    lg = ledger.Ledger.load(); lg.mark_done("s2", done); lg.save()
    monkeypatch.setattr(reconcile, "claude_projects_dir", lambda: projects)

    n = reconcile.run()
    queued = set(queue.drain())
    assert str(new) in queued
    assert str(done) not in queued     # already in ledger
    assert str(skip) not in queued     # analysis dir excluded
    assert n == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reconcile.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/totalrecall/reconcile.py`:
```python
from __future__ import annotations
from pathlib import Path
from . import ledger, queue


def claude_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def run() -> int:
    """Enqueue transcripts newer than the ledger. Returns count enqueued."""
    root = claude_projects_dir()
    if not root.exists():
        return 0
    lg = ledger.Ledger.load()
    done = lg.done_paths()
    count = 0
    for jsonl in root.rglob("*.jsonl"):
        norm = str(jsonl).replace("\\", "/")
        if "/analysis/" in norm:           # exclude self-produced analysis sessions
            continue
        if str(jsonl) in done:
            continue
        if not lg.is_new(jsonl):
            continue
        queue.enqueue(str(jsonl))
        count += 1
    return count
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reconcile.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/reconcile.py tests/test_reconcile.py
git commit -m "feat: reconcile scan enqueues stragglers, excludes analysis sessions"
```

---

## Task 17: Worker (drain-loop pipeline)

**Files:**
- Create: `src/totalrecall/worker.py`
- Test: `tests/test_worker.py`

- [ ] **Step 1: Write the failing test**

`tests/test_worker.py`:
```python
import json
from totalrecall import worker, queue, ledger, patterns_store, paths
from totalrecall.adapters.claude_code import ClaudeCodeAdapter

CC_LINE = ('{{"type":"user","isMeta":false,"isSidechain":false,'
           '"timestamp":"2026-06-10T10:0{n}:00Z","cwd":"/home/u/proj","sessionId":"{sid}",'
           '"gitBranch":"main","message":{{"role":"user","content":"use PowerShell not bash"}}}}')

def _write_session(home, sid):
    p = home / f"{sid}.jsonl"
    p.write_text(CC_LINE.format(n=0, sid=sid) + "\n", encoding="utf-8")
    return p

def _fake_analyze(session, catalog, model, runner=None):
    from totalrecall.models import Finding, Evidence
    return [Finding("repeated-correction", "use pwsh not bash", 3,
                    Evidence(session.session_id, "claude-code", [0], session.ended_at,
                             "h-" + session.session_id),
                    slug="pwsh-vs-bash")]

def test_process_one_updates_patterns_and_ledger(home, monkeypatch):
    paths.ensure_dirs()
    p = _write_session(home, "s1")
    queue.enqueue(str(p))
    monkeypatch.setattr(worker.orchestrator, "analyze", _fake_analyze)
    worker.run_once()
    assert patterns_store.get("pwsh-vs-bash").occurrences == 1
    assert ledger.Ledger.load().is_new(p) is False
    assert paths.insights_path().exists()

def test_drain_loop_picks_up_item_enqueued_during_processing(home, monkeypatch):
    paths.ensure_dirs()
    p1 = _write_session(home, "s1"); queue.enqueue(str(p1))
    calls = {"n": 0}
    def analyze_then_enqueue(session, catalog, model, runner=None):
        calls["n"] += 1
        if calls["n"] == 1:                         # mid-processing, a new session arrives
            p2 = _write_session(home, "s2"); queue.enqueue(str(p2))
        return _fake_analyze(session, catalog, model)
    monkeypatch.setattr(worker.orchestrator, "analyze", analyze_then_enqueue)
    monkeypatch.setattr(worker.reconcile, "run", lambda: 0)   # don't scan real ~/.claude
    worker.run()                                    # must drain BOTH via drain-loop
    assert calls["n"] == 2
    assert queue.size() == 0
    assert ledger.Ledger.load().is_new(_write_session(home, "s2")) is False

def test_second_worker_exits_when_locked(home, monkeypatch):
    paths.ensure_dirs()
    from totalrecall.locking import try_worker_lock
    with try_worker_lock() as got:
        assert got is True
        assert worker.run() == "busy"               # lock held -> no-op
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_worker.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/totalrecall/worker.py`:
```python
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from . import (queue, ledger, config, catalog, merger, render, reconcile,
               orchestrator, paths, synth)
from .adapters.claude_code import ClaudeCodeAdapter
from .events import extract_events
from .locking import try_worker_lock

_ADAPTER = ClaudeCodeAdapter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _count_projects(lg: ledger.Ledger) -> int:
    return len({str(Path(p).parent) for p in lg.done_paths()})


def process_path(path: str, cfg: config.Config) -> bool:
    """Process one transcript. Returns True if it produced an analysis."""
    lg = ledger.Ledger.load()
    p = Path(path)
    if not p.exists() or not lg.is_new(p):
        return False
    session = _ADAPTER.parse(p)
    if session.is_analysis_session:                 # ingest-layer self-exclusion
        lg.mark_done(session.session_id or path, p); lg.save()
        return False
    extract_events(session)
    cat = catalog.build(cfg.catalog_topk, _now())
    try:
        findings = orchestrator.analyze(session, cat, cfg.extract_model)
    except Exception:
        lg.mark_pending(session.session_id or path, str(p)); lg.save()
        return False
    merger.merge(findings, now=(session.ended_at or _now().isoformat()))
    lg.mark_done(session.session_id or path, p); lg.save()
    return True


def run_once() -> None:
    cfg = config.load()
    for path in queue.drain():
        process_path(path, cfg)
    _refresh(cfg)


def _refresh(cfg: config.Config) -> None:
    lg = ledger.Ledger.load()
    render.write(_now(), n_sessions=len(lg.done_paths()), n_projects=_count_projects(lg))


def run() -> str:
    with try_worker_lock() as got:
        if not got:
            return "busy"
        cfg = config.load()
        reconcile.run()
        processed = 0
        # drain-loop: keep going until the queue is truly empty before releasing the lock
        while True:
            batch = queue.drain()
            if not batch:
                break
            for path in batch:
                if process_path(path, cfg):
                    processed += 1
        _refresh(cfg)
        if processed and processed % cfg.synth_every_n_sessions == 0:
            synth.run(cfg)
        return "done"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_worker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/worker.py tests/test_worker.py
git commit -m "feat: worker pipeline with drain-loop + single-worker lock"
```

---

## Task 18: Synthesis pass

**Files:**
- Create: `src/totalrecall/synth.py`
- Test: `tests/test_synth.py`

- [ ] **Step 1: Write the failing test**

`tests/test_synth.py`:
```python
from datetime import datetime, timezone
from totalrecall import synth, patterns_store, paths, config
from totalrecall.models import Pattern, Evidence

def _p(pid, desc):
    return Pattern(pid, f"T {pid}", "repeated-correction", "llm", desc,
                   "2026-06-01T00:00:00Z", "2026-06-14T00:00:00Z", 2, 3,
                   evidence=[Evidence("s1", "claude-code", [1], None, "h" + pid + "1"),
                             Evidence("s2", "claude-code", [2], None, "h" + pid + "2")])

def test_synth_merges_pairs_returned_by_model(home, monkeypatch):
    paths.ensure_dirs()
    patterns_store.save(_p("pwsh-vs-bash", "use powershell not bash"))
    patterns_store.save(_p("use-powershell", "prefer powershell over bash"))
    # fake model says: merge use-powershell INTO pwsh-vs-bash
    monkeypatch.setattr(synth, "_ask_merges",
                        lambda patterns, model: [["pwsh-vs-bash", "use-powershell"]])
    synth.run(config.load())
    ids = {p.id for p in patterns_store.all()}
    assert ids == {"pwsh-vs-bash"}
    survivor = patterns_store.get("pwsh-vs-bash")
    assert survivor.occurrences == 4                 # 2 + 2 combined
    assert paths.insights_path().exists()            # narrative re-rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_synth.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/totalrecall/synth.py`:
```python
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from . import patterns_store, paths, config, render, orchestrator, ledger


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ask_merges(patterns: list, model: str) -> list[list[str]]:
    """Ask the model which pattern ids are duplicates. Returns groups [keep, dup, dup...]."""
    catalog = [{"id": p.id, "title": p.title, "description": p.description} for p in patterns]
    prompt = (
        "You are consolidating a friction pattern library. Given these patterns, "
        "group ones that describe the SAME underlying friction. Output ONLY a JSON array "
        "of groups; each group is an array of ids where the FIRST id is the canonical "
        "survivor, e.g. [[\"keep-id\",\"dup-id\"]]. Only include groups with >1 id.\n\n"
        + json.dumps(catalog, ensure_ascii=False)
    )
    env = {}
    import os
    env.update(os.environ)
    env[config.load().analysis_marker_env] = "1"
    raw = orchestrator.default_runner(prompt, model, str(paths.analysis_cwd()), env)
    try:
        text = json.loads(raw).get("result", "")
    except json.JSONDecodeError:
        text = raw
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []


def _merge_into(keep_id: str, dup_id: str) -> None:
    keep = patterns_store.get(keep_id)
    dup = patterns_store.get(dup_id)
    if not keep or not dup:
        return
    seen = {e.snippet_hash for e in keep.evidence}
    for e in dup.evidence:
        if e.snippet_hash not in seen:
            keep.evidence.append(e)
            seen.add(e.snippet_hash)
    keep.occurrences = len(keep.evidence)   # occurrences stays == distinct evidence
    keep.last_seen = max(keep.last_seen, dup.last_seen)
    keep.severity = max(keep.severity, dup.severity)
    keep.phase2_hint = keep.phase2_hint or dup.phase2_hint
    patterns_store.save(keep)
    (paths.patterns_dir() / f"{dup_id}.json").unlink(missing_ok=True)
    patterns_store.save(keep)   # rebuild index after deletion


def run(cfg: config.Config) -> None:
    patterns = patterns_store.all()
    if not patterns:
        return
    for group in _ask_merges(patterns, cfg.synth_model):
        if len(group) < 2:
            continue
        keep = group[0]
        for dup in group[1:]:
            _merge_into(keep, dup)
    lg = ledger.Ledger.load()
    n_projects = len({str(Path(p).parent) for p in lg.done_paths()})
    render.write(_now(), n_sessions=len(lg.done_paths()), n_projects=n_projects)
```

> The fake in the test overrides `_ask_merges`, so no real `claude` call happens in tests.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_synth.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/synth.py tests/test_synth.py
git commit -m "feat: periodic synthesis consolidates near-duplicate patterns"
```

---

## Task 19: init / hook install

**Files:**
- Create: `src/totalrecall/hookinstall.py`
- Test: `tests/test_hookinstall.py`

- [ ] **Step 1: Write the failing test**

`tests/test_hookinstall.py`:
```python
import json
from totalrecall import hookinstall, paths

def test_init_scaffolds_state_and_config(home, tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(hookinstall, "claude_settings_path", lambda: settings)
    hookinstall.init()
    assert paths.config_path().exists()
    assert paths.queue_dir().is_dir()
    data = json.loads(settings.read_text(encoding="utf-8"))
    cmds = [h["command"] for entry in data["hooks"]["SessionEnd"] for h in entry["hooks"]]
    assert any("totalrecall" in c and "hook" in c for c in cmds)

def test_init_is_idempotent_and_preserves_existing_hooks(home, tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {"SessionEnd": [
        {"hooks": [{"type": "command", "command": "echo other"}]}]}}), encoding="utf-8")
    monkeypatch.setattr(hookinstall, "claude_settings_path", lambda: settings)
    hookinstall.init()
    hookinstall.init()   # twice -> still single totalrecall hook, other preserved
    data = json.loads(settings.read_text(encoding="utf-8"))
    cmds = [h["command"] for entry in data["hooks"]["SessionEnd"] for h in entry["hooks"]]
    assert "echo other" in cmds
    assert sum("totalrecall" in c for c in cmds) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hookinstall.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/totalrecall/hookinstall.py`:
```python
from __future__ import annotations
import json
from pathlib import Path
from . import paths, config

HOOK_COMMAND = "totalrecall hook"


def claude_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _load_settings(p: Path) -> dict:
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _already_installed(session_end: list) -> bool:
    for entry in session_end:
        for h in entry.get("hooks", []):
            if HOOK_COMMAND in h.get("command", ""):
                return True
    return False


def install_hook() -> None:
    p = claude_settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = _load_settings(p)
    hooks = data.setdefault("hooks", {})
    session_end = hooks.setdefault("SessionEnd", [])
    if not _already_installed(session_end):
        session_end.append({"hooks": [{"type": "command", "command": HOOK_COMMAND}]})
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def scaffold_state() -> None:
    paths.ensure_dirs()
    if not paths.config_path().exists():
        paths.config_path().write_text(config.default_toml(), encoding="utf-8")


def init() -> None:
    scaffold_state()
    install_hook()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_hookinstall.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/hookinstall.py tests/test_hookinstall.py
git commit -m "feat: init scaffolds state + idempotently merges SessionEnd hook"
```

---

## Task 20: hook entrypoint (enqueue + self-exclusion + detached worker)

**Files:**
- Create: `src/totalrecall/hookcmd.py`
- Test: `tests/test_hookcmd.py`

- [ ] **Step 1: Write the failing test**

`tests/test_hookcmd.py`:
```python
import io, json
from totalrecall import hookcmd, queue, paths

def test_hook_enqueues_transcript_path(home, monkeypatch):
    paths.ensure_dirs()
    monkeypatch.setattr(hookcmd, "_spawn_worker", lambda: None)
    payload = json.dumps({"transcript_path": "/x/s1.jsonl", "session_id": "s1"})
    rc = hookcmd.handle(stdin=io.StringIO(payload), env={})
    assert rc == 0
    assert "/x/s1.jsonl" in queue.drain()

def test_hook_skips_when_analysis_marker_set(home, monkeypatch):
    paths.ensure_dirs()
    monkeypatch.setattr(hookcmd, "_spawn_worker", lambda: None)
    payload = json.dumps({"transcript_path": "/x/a1.jsonl"})
    rc = hookcmd.handle(stdin=io.StringIO(payload), env={"TOTALRECALL_ANALYSIS": "1"})
    assert rc == 0
    assert queue.size() == 0          # self-produced analysis session not enqueued

def test_hook_never_raises_on_bad_input(home, monkeypatch):
    monkeypatch.setattr(hookcmd, "_spawn_worker", lambda: None)
    rc = hookcmd.handle(stdin=io.StringIO("not json"), env={})
    assert rc == 0                    # must not break the user's session
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hookcmd.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/totalrecall/hookcmd.py`:
```python
from __future__ import annotations
import json
import os
import subprocess
import sys
from . import queue, config, paths


def _spawn_worker() -> None:
    """Spawn `totalrecall worker` fully detached so the hook returns instantly."""
    args = [sys.executable, "-m", "totalrecall.cli", "worker"]
    try:
        if os.name == "nt":
            DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(args, creationflags=DETACHED, close_fds=True)
        else:
            subprocess.Popen(args, start_new_session=True, close_fds=True)
    except Exception:
        pass


def handle(stdin, env) -> int:
    """SessionEnd hook body. MUST be fast, non-blocking, and never raise."""
    try:
        marker = config.load().analysis_marker_env
        if env.get(marker):                 # hook-layer self-exclusion
            return 0
        payload = json.loads(stdin.read() or "{}")
        path = payload.get("transcript_path")
        if path:
            queue.enqueue(path)
            _spawn_worker()
    except Exception as e:                    # never break the user's session
        try:
            paths.log_path().open("a", encoding="utf-8").write(f"hook error: {e}\n")
        except Exception:
            pass
    return 0


def main() -> int:
    return handle(sys.stdin, os.environ)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_hookcmd.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/hookcmd.py tests/test_hookcmd.py
git commit -m "feat: non-blocking SessionEnd hook (enqueue + self-exclusion + detached worker)"
```

---

## Task 21: CLI wiring

**Files:**
- Create: `src/totalrecall/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
from totalrecall import cli

def test_status_reports_counts(home, capsys):
    from totalrecall import paths, patterns_store
    from totalrecall.models import Pattern
    paths.ensure_dirs()
    patterns_store.save(Pattern("x", "T", "c", "llm", "d",
                                "2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z", 1, 1))
    rc = cli.main(["status"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "patterns: 1" in out

def test_dispatch_calls_subcommands(home, monkeypatch):
    called = {}
    monkeypatch.setattr(cli.hookinstall, "init", lambda: called.setdefault("init", True))
    monkeypatch.setattr(cli.worker, "run", lambda: called.setdefault("worker", "done") or "done")
    monkeypatch.setattr(cli.reconcile, "run", lambda: called.setdefault("recon", 0) or 0)
    assert cli.main(["init"]) == 0 and called.get("init")
    assert cli.main(["worker"]) == 0 and called.get("worker")
    assert cli.main(["reconcile"]) == 0 and "recon" in called

def test_ingest_one_path(home, monkeypatch, tmp_path):
    called = {}
    monkeypatch.setattr(cli.worker, "process_path",
                        lambda path, cfg: called.setdefault("p", path) or True)
    f = tmp_path / "s.jsonl"; f.write_text("x", encoding="utf-8")
    assert cli.main(["ingest", str(f)]) == 0
    assert called["p"] == str(f)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`src/totalrecall/cli.py`:
```python
from __future__ import annotations
import argparse
import sys
from . import (hookinstall, worker, reconcile, synth, config, ledger,
               patterns_store, hookcmd)


def _cmd_status() -> int:
    lg = ledger.Ledger.load()
    print(f"sessions: {len(lg.done_paths())}")
    print(f"patterns: {len(patterns_store.all())}")
    print(f"pending: {len(lg.pending_items())}")
    return 0


def _cmd_retry() -> int:
    cfg = config.load()
    lg = ledger.Ledger.load()
    for _sid, path in lg.pending_items():
        worker.process_path(path, cfg)
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="totalrecall")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p_ingest = sub.add_parser("ingest"); p_ingest.add_argument("path")
    sub.add_parser("worker")
    sub.add_parser("reconcile")
    sub.add_parser("synth")
    sub.add_parser("status")
    sub.add_parser("retry")
    sub.add_parser("hook")
    args = parser.parse_args(argv)

    if args.cmd == "init":
        hookinstall.init(); print("TotalRecall initialized."); return 0
    if args.cmd == "ingest":
        worker.process_path(args.path, config.load()); return 0
    if args.cmd == "worker":
        worker.run(); return 0
    if args.cmd == "reconcile":
        n = reconcile.run(); print(f"enqueued: {n}"); return 0
    if args.cmd == "synth":
        synth.run(config.load()); return 0
    if args.cmd == "status":
        return _cmd_status()
    if args.cmd == "retry":
        return _cmd_retry()
    if args.cmd == "hook":
        return hookcmd.main()
    return 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/cli.py tests/test_cli.py
git commit -m "feat: CLI wiring (init/ingest/worker/reconcile/synth/status/retry/hook)"
```

---

## Task 22: Full suite + README + manual smoke

**Files:**
- Create: `README.md`
- Test: full suite

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -v`
Expected: ALL PASS

- [ ] **Step 2: Write README**

`README.md`:
```markdown
# TotalRecall

Learns from your AI-coding sessions: after each Claude Code session ends, it extracts
*collaboration friction* (repeated corrections, misunderstandings, rework, tool errors)
and maintains a living `~/.totalrecall/insights.md`.

## Install
```
pip install -e .
totalrecall init      # scaffolds ~/.totalrecall and installs the SessionEnd hook
```

## How it works
SessionEnd hook → enqueue → detached `worker` → adapter → deterministic events +
`claude -p` semantic analysis → merge into pattern library → re-render `insights.md`.
Self-produced analysis sessions are excluded; crashed sessions are caught by `reconcile`.

## Commands
`init` · `worker` · `reconcile` · `synth` · `status` · `retry` · `ingest <path>`

## Config
`~/.totalrecall/config.toml` — models (default Sonnet), synth cadence, catalog top-K, sources.

Phase 1 = insights only. Phase 2 (planned) turns high-strength patterns into proposed
skill / CLAUDE.md / agent edits.
```

- [ ] **Step 3: Manual smoke test (real claude)**

Run:
```
totalrecall init
totalrecall reconcile     # enqueue a few real recent sessions
totalrecall worker        # process them (this calls the real `claude` CLI)
totalrecall status
```
Expected: `status` shows sessions/patterns > 0; `~/.totalrecall/insights.md` exists and the
Top friction items feel true. If `claude` is slow/unavailable, items land in `pending`;
`totalrecall retry` reprocesses them.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README + Phase 1 complete"
```

---

## Self-Review

**Spec coverage** (each spec section → task):
- §3 architecture (3 layers) → Tasks 5–21 collectively; trigger=20, CLI core=5–17, analysis skill=14–15.
- §4.1 trigger + two-layer self-exclusion → hook layer (Task 20, marker check) + ingest layer (Task 5 cwd detection; Task 17 `is_analysis_session` short-circuit).
- §4.2 worker drain-loop → Task 17 (`run` while-loop + `test_drain_loop...`).
- §4.3 adapter → Task 5. §4.4 NormalizedSession → Task 4/5.
- §4.5 orchestrator (marker env, analysis cwd, catalog, snippet_hash) → Task 15.
- §4.6 merger (id reuse / slug / similarity / hash dedup) → Task 11.
- §4.7 analyze skill (Finding schema, reuse pattern_id) → Task 14.
- §5 A-class signals → Task 6 (tool_error, churn, edits, duration). B-class → Task 14 categories.
  _Note: §5 also lists permission/interrupt/re-prompt A-signals; Phase-1 ships tool_error+churn+edits+duration; permission_denied/interrupt/reprompt are deferred refinements (see Deferred below)._
- §6.1 Finding / §6.2 Pattern / §6.3 insights.md → Tasks 4, 9, 13.
- §7 data flow → Task 17 (`run_once`/`run`) + Task 16 (reconcile) + Task 18 (synth-every-N in `run`).
- §8 cost tiers (Sonnet default extract, Sonnet synth, top-K catalog) → Tasks 3, 12, 15, 18.
- §9 idempotency/dedup/non-blocking/self-exclusion/reconcile/pending/concurrency → Tasks 7, 8, 11, 17, 20.
- §10 CLI commands → Task 21. §11 config → Task 3. §12 storage layout → Task 2.
- §13 testing → every task is TDD; drain-loop race + reconcile + self-exclusion explicitly tested.
- §14 MVP scope → Tasks 1–22. §15 Phase 2 seam → `phase2_hint` carried through Tasks 11/13. §16 risks → Deferred/Manual notes.

**Deferred within Phase 1 (intentional, logged here so they are not "silently dropped"):**
- A-class `permission_denied`, `interrupt`, and `re-prompt` signals — not yet extracted (Task 6 covers tool_error/churn/edits/duration). Add as follow-up events in `events.py` with the same pattern as churn.
- True edit→revert detection (`n_reverts`) — field exists in `Stats` but stays 0 in Phase 1; churn-by-count approximates rework.
- Risks §16 #2/#3 (`claude -p --output-format json` shape; whether `claude -p` fires SessionEnd) must be confirmed in Task 22's manual smoke; the two-layer self-exclusion is correct whether or not the hook fires.

**Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N". All steps carry runnable code.

**Type consistency:** `NormalizedSession`, `Finding`, `Evidence`, `Pattern` (Task 4) are used identically in Tasks 5/6/11/13/15/17/18. `orchestrator.analyze(session, catalog, model, runner=...)` signature matches its call in `worker.process_path` (Task 17) and its fake in `test_worker`. `patterns_store.get/all/save` consistent across Tasks 9/11/12/13/18. `queue.enqueue/drain/size/worker_lock` consistent across Tasks 8/16/17/20. `paths.*` consistent everywhere.
```
