from enum import StrEnum


class FacetResultSource(StrEnum):
    INDEX = "index"
    SCAN = "scan"
    UNAVAILABLE = "unavailable"

    def __str__(self) -> str:
        return str(self.value)
