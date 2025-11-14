"""매크로 저장 및 불러오기 유틸리티."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from .macro import Macro

PathLike = Union[str, Path]


def save_macro(macro: Macro, path: PathLike) -> None:
    """매크로를 JSON 형식으로 저장."""
    target = Path(path)
    target.write_text(
        json.dumps(macro.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_macro(path: PathLike) -> Macro:
    """JSON 파일에서 매크로 로드."""
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    return Macro.from_dict(data)
