from enum import StrEnum


class BatchEdgeLineType(StrEnum):
    E = "e"
    EDGE = "edge"

    def __str__(self) -> str:
        return str(self.value)
