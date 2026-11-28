from enum import StrEnum


class McpConfigUpdatePrincipalProfilesAdditionalProperty(StrEnum):
    ADMIN = "admin"
    ALL = "all"
    RAG = "rag"

    def __str__(self) -> str:
        return str(self.value)
