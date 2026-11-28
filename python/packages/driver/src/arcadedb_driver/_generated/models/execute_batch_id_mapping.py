from enum import StrEnum


class ExecuteBatchIdMapping(StrEnum):
    AUTO = "auto"
    FALSE = "false"
    TRUE = "true"

    def __str__(self) -> str:
        return str(self.value)
