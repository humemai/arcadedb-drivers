from enum import StrEnum


class McpConfigProfile(StrEnum):
    ADMIN = "admin"
    ALL = "all"
    RAG = "rag"

    def __str__(self) -> str:
        return str(self.value)
