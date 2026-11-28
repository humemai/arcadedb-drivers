from enum import StrEnum


class ClusterAuthSessionRequestAction(StrEnum):
    REVOKE = "revoke"
    VALIDATE = "validate"

    def __str__(self) -> str:
        return str(self.value)
