from enum import StrEnum


class McpConfigPrincipalProfilesAdditionalProperty(StrEnum):
    ADMIN = "admin"
    ALL = "all"
    RAG = "rag"

    def __str__(self) -> str:
        return str(self.value)
