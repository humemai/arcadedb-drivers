from enum import StrEnum


class ExecuteCommandAccept(StrEnum):
    APPLICATIONJSON = "application/json"
    APPLICATIONX_NDJSON = "application/x-ndjson"

    def __str__(self) -> str:
        return str(self.value)
