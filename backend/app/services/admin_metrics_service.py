"""Admin metrics use case. HTTP and MongoDB details remain outside this service."""
from backend.app.data_access.operations.system_operations import read_admin_metrics


def get_admin_metrics(admin_id: str):
    return read_admin_metrics(principal_id=admin_id)

