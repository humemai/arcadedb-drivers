from enum import StrEnum


class ClusterStatusPeersItemCapabilitiesUnknownKind(StrEnum):
    ADDRESS_REFUSED = "ADDRESS_REFUSED"
    ROUTE_MISSING = "ROUTE_MISSING"
    STALE = "STALE"
    UNREACHABLE = "UNREACHABLE"

    def __str__(self) -> str:
        return str(self.value)
