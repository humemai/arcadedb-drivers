from enum import StrEnum


class HybridSearchResponseResultsItemSourcesItem(StrEnum):
    EXPAND = "expand"
    FULLTEXT = "fulltext"
    VECTOR = "vector"

    def __str__(self) -> str:
        return str(self.value)
