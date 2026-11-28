from enum import StrEnum


class PromQLLabelsResponseStatus(StrEnum):
    SUCCESS = "success"

    def __str__(self) -> str:
        return str(self.value)
