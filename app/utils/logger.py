from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class ReasoningLogger:
    @staticmethod
    def save_session(session: Dict[str, Any], file_path: Path) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding="utf-8") or "[]")
                if not isinstance(data, list):
                    data = []
            except Exception:
                data = []
        else:
            data = []

        data.append(session)
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
