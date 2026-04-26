from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable

ProtectFile = Callable[[Path], None]


def write_json_artifact(
    output_file: Path,
    payload: dict[str, Any],
    *,
    protect_file: ProtectFile | None = None,
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        dir=output_file.parent,
        prefix=f"{output_file.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        if protect_file is not None:
            protect_file(temp_path)
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(temp_path, output_file)
    if protect_file is not None:
        protect_file(output_file)


def write_binary_artifact(
    output_file: Path,
    payload: bytes,
    *,
    protect_file: ProtectFile | None = None,
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "wb",
        dir=output_file.parent,
        prefix=f"{output_file.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        if protect_file is not None:
            protect_file(temp_path)
        handle.write(payload)
    os.replace(temp_path, output_file)
    if protect_file is not None:
        protect_file(output_file)
