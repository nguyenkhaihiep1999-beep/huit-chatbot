"""Domain adapters for bounded health and administrator reads (v2.0.0)."""
from backend.app.data_access.operation_gateway import execute_registered_operation
from backend.app.data_access.registered_operations.system_observability_v2 import (
    ADMIN_METRICS,
    DATABASE_SNAPSHOT,
)

DATABASE_SNAPSHOT_CHECKSUM = "07ca7b33a72955cb8e6d2470f7bd26657ea7bebe1c9ce5deb1ace28f70162143"
ADMIN_METRICS_CHECKSUM = "9c1f90ed335411e08b0fa9df55b9631069dd887489ae2d13a953faab74eda324"


def read_database_snapshot(*, request_id: str = "health"):
    return execute_registered_operation(
        key=DATABASE_SNAPSHOT.key,
        version=DATABASE_SNAPSHOT.version,
        checksum=DATABASE_SNAPSHOT_CHECKSUM,
        parameters={"include_job_counts": True},
        principal_id="system",
        request_id=request_id,
    )


def read_admin_metrics(*, principal_id: str, request_id: str = "admin-metrics", recent_limit: int = 20):
    return execute_registered_operation(
        key=ADMIN_METRICS.key,
        version=ADMIN_METRICS.version,
        checksum=ADMIN_METRICS_CHECKSUM,
        parameters={"recent_limit": recent_limit},
        principal_id=principal_id,
        request_id=request_id,
    )
