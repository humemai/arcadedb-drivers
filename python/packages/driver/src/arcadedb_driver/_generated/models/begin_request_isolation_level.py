from enum import StrEnum


class BeginRequestIsolationLevel(StrEnum):
    READ_COMMITTED = "READ_COMMITTED"
    REPEATABLE_READ = "REPEATABLE_READ"

    def __str__(self) -> str:
        return str(self.value)
