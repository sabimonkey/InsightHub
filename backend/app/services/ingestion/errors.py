class IngestionError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


DUPLICATE_MESSAGE = "已识别重复资料。已复用已有 Source。本次收集记录已保存。"
STORED_MESSAGE = "资料已保存。"
