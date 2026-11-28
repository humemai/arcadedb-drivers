from enum import StrEnum


class McpConfigUpdateProfile(StrEnum):
    ADMIN = "admin"
    ALL = "all"
    RAG = "rag"

    def __str__(self) -> str:
        return str(self.value)
