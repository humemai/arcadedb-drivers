from enum import StrEnum


class TimeSeriesQueryRequestAggregationRequestsItemType(StrEnum):
    AVG = "AVG"
    COUNT = "COUNT"
    MAX = "MAX"
    MIN = "MIN"
    SUM = "SUM"

    def __str__(self) -> str:
        return str(self.value)
