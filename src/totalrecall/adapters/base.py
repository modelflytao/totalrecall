from __future__ import annotations
from pathlib import Path
from typing import Protocol
from ..models import NormalizedSession


class Adapter(Protocol):
    tool: str

    def parse(self, path: Path) -> NormalizedSession: ...
