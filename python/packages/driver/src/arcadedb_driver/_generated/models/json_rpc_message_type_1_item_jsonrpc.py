from enum import StrEnum


class JsonRpcMessageType1ItemJsonrpc(StrEnum):
    VALUE_0 = "2.0"

    def __str__(self) -> str:
        return str(self.value)
