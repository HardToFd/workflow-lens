"""Short cross-process lock for the shared task metrics document and active markers."""

import errno
import os
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def metrics_lock(task_dir: Path, timeout: float = 10.0):
    directory = task_dir / "scratch" / "metrics"
    directory.mkdir(parents=True, exist_ok=True)
    # 用操作系统锁而非持久化的占用标记；进程退出后锁自动释放。
    with (directory / ".write.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise ValueError("task metrics are being updated; retry after the other writer finishes")
                time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
