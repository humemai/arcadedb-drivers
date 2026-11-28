from enum import StrEnum


class AiChatMessagesItemRole(StrEnum):
    ASSISTANT = "assistant"
    USER = "user"

    def __str__(self) -> str:
        return str(self.value)
