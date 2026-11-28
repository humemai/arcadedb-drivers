from enum import StrEnum


class FullTextSearchResponseSimilarity(StrEnum):
    BM25 = "BM25"
    CLASSIC = "CLASSIC"

    def __str__(self) -> str:
        return str(self.value)
