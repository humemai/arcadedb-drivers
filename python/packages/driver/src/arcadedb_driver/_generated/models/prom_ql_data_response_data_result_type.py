from enum import StrEnum


class PromQLDataResponseDataResultType(StrEnum):
    MATRIX = "matrix"
    SCALAR = "scalar"
    VECTOR = "vector"

    def __str__(self) -> str:
        return str(self.value)
