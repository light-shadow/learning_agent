"""网关稳定错误定义。"""


class GatewayError(Exception):
    """将内部异常映射为可安全返回给调用方的错误。"""

    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)
