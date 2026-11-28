from enum import StrEnum


class BatchVertexLineType(StrEnum):
    V = "v"
    VERTEX = "vertex"

    def __str__(self) -> str:
        return str(self.value)
