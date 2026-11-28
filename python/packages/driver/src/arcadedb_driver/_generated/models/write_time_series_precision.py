from enum import StrEnum


class WriteTimeSeriesPrecision(StrEnum):
    MS = "ms"
    NS = "ns"
    S = "s"
    US = "us"

    def __str__(self) -> str:
        return str(self.value)
