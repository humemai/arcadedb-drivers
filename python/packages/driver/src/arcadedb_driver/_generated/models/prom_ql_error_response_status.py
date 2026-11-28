from enum import StrEnum


class PromQLErrorResponseStatus(StrEnum):
    ERROR = "error"

    def __str__(self) -> str:
        return str(self.value)
