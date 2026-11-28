from enum import StrEnum


class FacetResultType(StrEnum):
    DISTINCT = "distinct"
    HIERARCHY = "hierarchy"
    HISTOGRAM = "histogram"
    RANGE = "range"
    STATS = "stats"
    TERMS = "terms"

    def __str__(self) -> str:
        return str(self.value)
