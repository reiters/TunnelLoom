from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot


class Worker(QObject):
    """Run one blocking backend function in a dedicated QThread.

    Keeping the worker as a QObject with thread affinity ensures its result
    signals are queued back to MainWindow's GUI-thread slots. This avoids
    touching Qt widgets from a QThreadPool worker and avoids the QRunnable
    lifetime race that could cause a native PySide crash while pkexec waited
    for administrator authorization.
    """

    finished = Signal(int, object)
    failed = Signal(int, object)
    done = Signal()

    def __init__(self, task_id: int, function: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.task_id = task_id
        self.function = function
        self.args = args
        self.kwargs = kwargs

    @Slot()
    def run(self) -> None:
        try:
            result = self.function(*self.args, **self.kwargs)
        except Exception as exc:  # delivered to the GUI thread
            self.failed.emit(self.task_id, exc)
        else:
            self.finished.emit(self.task_id, result)
        finally:
            self.done.emit()
