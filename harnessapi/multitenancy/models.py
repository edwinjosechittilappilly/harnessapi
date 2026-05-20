from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import SkillInput, SkillOutput


@dataclass
class SkillVariant:
    variant_id: str
    tenant_id: str
    base_skill_name: str
    handler_source: str
    handler: Callable
    status: Literal["sandbox", "promoted"]
    created_at: datetime
    input_model: type[SkillInput]
    output_model: type[SkillOutput]
    meta_overrides: dict[str, Any] = field(default_factory=dict)
    storage_path: Path | None = None

    def is_streaming_handler(self) -> bool:
        return inspect.isasyncgenfunction(self.handler)


class VariantResponse:
    def __init__(
        self,
        variant_id: str,
        tenant_id: str,
        base_skill_name: str,
        status: Literal["sandbox", "promoted"],
        source_code: str | None = None,
    ) -> None:
        self.variant_id = variant_id
        self.tenant_id = tenant_id
        self.base_skill_name = base_skill_name
        self.status = status
        self.source_code = source_code

    def model_dump(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "variant_id": self.variant_id,
            "tenant_id": self.tenant_id,
            "base_skill_name": self.base_skill_name,
            "status": self.status,
        }
        if self.source_code is not None:
            d["source_code"] = self.source_code
        return d


class VariantSummary:
    def __init__(self, variant: SkillVariant) -> None:
        self.variant_id = variant.variant_id
        self.tenant_id = variant.tenant_id
        self.base_skill_name = variant.base_skill_name
        self.status = variant.status
        self.created_at = variant.created_at.isoformat()

    def model_dump(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "tenant_id": self.tenant_id,
            "base_skill_name": self.base_skill_name,
            "status": self.status,
            "created_at": self.created_at,
        }
