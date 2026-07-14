from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Iterator

import pandas as pd


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temporary_sibling(path)
    try:
        temp_path.write_text(content, encoding=encoding)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def atomic_write_csv(frame: pd.DataFrame, path: Path, **kwargs) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temporary_sibling(path)
    try:
        frame.to_csv(temp_path, **kwargs)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temporary_sibling(target)
    try:
        shutil.copy2(source, temp_path)
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)


@contextmanager
def exclusive_file_lock(
    path: Path,
    *,
    owner: str,
    timeout_seconds: float = 0,
    stale_after: timedelta = timedelta(hours=12),
) -> Iterator[None]:
    """Cross-process lock based on atomic file creation.

    A stale lock is removed only after its age exceeds ``stale_after``. This is
    intentionally conservative because a duplicate research run is riskier
    than waiting for the next scheduled run.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    payload = f"owner={owner}\npid={os.getpid()}\ncreated_at={datetime.now().isoformat(timespec='seconds')}\n"
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            break
        except FileExistsError:
            if _is_stale_lock(path, stale_after=stale_after):
                path.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                detail = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
                raise RuntimeError(f"已有任务持有运行锁: {path}\n{detail}".rstrip())
            time.sleep(0.2)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def _temporary_sibling(path: Path) -> Path:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    return Path(name)


def _is_stale_lock(path: Path, *, stale_after: timedelta) -> bool:
    try:
        age_seconds = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    return age_seconds > stale_after.total_seconds()
