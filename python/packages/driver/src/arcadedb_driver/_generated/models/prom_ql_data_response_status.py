from enum import StrEnum


class PromQLDataResponseStatus(StrEnum):
    SUCCESS = "success"

    def __str__(self) -> str:
        return str(self.value)
