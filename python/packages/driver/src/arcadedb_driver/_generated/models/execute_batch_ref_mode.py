from enum import StrEnum


class ExecuteBatchRefMode(StrEnum):
    ID = "id"
    ORDINAL = "ordinal"

    def __str__(self) -> str:
        return str(self.value)
