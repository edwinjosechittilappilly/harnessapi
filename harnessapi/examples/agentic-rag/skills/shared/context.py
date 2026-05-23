from contextvars import ContextVar

tenant_id_var: ContextVar[str] = ContextVar("tenant_id", default="default")
