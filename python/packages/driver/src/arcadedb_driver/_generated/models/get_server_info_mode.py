from enum import StrEnum


class GetServerInfoMode(StrEnum):
    BASIC = "basic"
    CLUSTER = "cluster"
    DEFAULT = "default"

    def __str__(self) -> str:
        return str(self.value)
