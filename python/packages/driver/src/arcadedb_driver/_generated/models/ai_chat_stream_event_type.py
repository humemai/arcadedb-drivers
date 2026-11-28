from enum import StrEnum


class AiChatStreamEventType(StrEnum):
    DELTA = "delta"
    DONE = "done"
    ERROR = "error"
    RESET = "reset"
    TOOL_END = "tool_end"
    TOOL_START = "tool_start"

    def __str__(self) -> str:
        return str(self.value)
