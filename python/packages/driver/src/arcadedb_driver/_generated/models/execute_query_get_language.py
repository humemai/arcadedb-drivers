from enum import StrEnum


class ExecuteQueryGetLanguage(StrEnum):
    CYPHER = "cypher"
    GRAPHQL = "graphql"
    GREMLIN = "gremlin"
    MONGO = "mongo"
    SQL = "sql"

    def __str__(self) -> str:
        return str(self.value)
