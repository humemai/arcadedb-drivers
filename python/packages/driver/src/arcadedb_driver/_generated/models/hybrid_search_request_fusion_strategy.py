from enum import StrEnum


class HybridSearchRequestFusionStrategy(StrEnum):
    DBSF = "DBSF"
    LINEAR = "LINEAR"
    RRF = "RRF"

    def __str__(self) -> str:
        return str(self.value)
