from enum import StrEnum


class HybridSearchResponseLegsExpandDirection(StrEnum):
    BOTH = "both"
    IN = "in"
    OUT = "out"

    def __str__(self) -> str:
        return str(self.value)
