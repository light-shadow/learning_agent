"""自学 Agent 的稳定业务错误。"""

from __future__ import annotations


class StudyError(Exception):
    """携带可供 Runtime、CLI 和测试共同识别的错误码。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
