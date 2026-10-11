from fastapi import Request

from src.api.errors import NotReadyError
from src.services.container import ServiceContainer


def get_container(request: Request) -> ServiceContainer:
    return request.app.state.container


def require_ready(request: Request) -> ServiceContainer:
    c: ServiceContainer = request.app.state.container
    if not c.ready:
        raise NotReadyError(c.missing)
    return c


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")
