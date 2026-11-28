from enum import StrEnum


class JsonRpcMessageType0Jsonrpc(StrEnum):
    VALUE_0 = "2.0"

    def __str__(self) -> str:
        return str(self.value)
