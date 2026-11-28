from enum import StrEnum


class TerminationStatusStatus(StrEnum):
    COMPLETED = "completed"
    NOT_FOUND = "not found"
    TERMINATED = "terminated"
    TERMINATING = "terminating"

    def __str__(self) -> str:
        return str(self.value)
