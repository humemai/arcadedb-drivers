from enum import StrEnum


class HybridSearchResponseLegsFulltextSimilarity(StrEnum):
    BM25 = "BM25"
    CLASSIC = "CLASSIC"

    def __str__(self) -> str:
        return str(self.value)
