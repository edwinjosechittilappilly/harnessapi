from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import SkillVariant


class TenantSkillRegistry:
    """In-memory index of promoted and sandbox skill variants."""

    def __init__(self) -> None:
        # (tenant_id, skill_name) → promoted variant
        self._promoted: dict[tuple[str, str], SkillVariant] = {}
        # (tenant_id, skill_name) → preview variant
        self._preview: dict[tuple[str, str], SkillVariant] = {}
        # variant_id → sandbox variant
        self._sandbox: dict[str, SkillVariant] = {}

    # ------------------------------------------------------------------
    # promoted

    def get_promoted(self, tenant_id: str, skill_name: str) -> SkillVariant | None:
        return self._promoted.get((tenant_id, skill_name))

    def set_promoted(self, variant: SkillVariant) -> SkillVariant | None:
        """Promote a variant, returning the previously promoted one (if any)."""
        key = (variant.tenant_id, variant.base_skill_name)
        previous = self._promoted.get(key)
        self._promoted[key] = variant
        # remove from sandbox index if it was there
        self._sandbox.pop(variant.variant_id, None)
        return previous

    def demote(self, variant: SkillVariant) -> None:
        key = (variant.tenant_id, variant.base_skill_name)
        if self._promoted.get(key) is variant:
            del self._promoted[key]
        self._preview.pop(key, None)
        self._sandbox[variant.variant_id] = variant

    def list_promoted_for_tenant(self, tenant_id: str) -> list[SkillVariant]:
        return [v for (tid, _), v in self._promoted.items() if tid == tenant_id]

    # ------------------------------------------------------------------
    # preview

    def set_preview(self, variant: SkillVariant) -> SkillVariant | None:
        """Set a variant as preview, returning the displaced preview variant (if any).

        The displaced preview is moved back to the sandbox index.
        """
        key = (variant.tenant_id, variant.base_skill_name)
        previous = self._preview.get(key)
        self._preview[key] = variant
        self._sandbox.pop(variant.variant_id, None)
        if previous is not None and previous.variant_id != variant.variant_id:
            self._sandbox[previous.variant_id] = previous
        return previous

    def get_preview(self, tenant_id: str, skill_name: str) -> SkillVariant | None:
        return self._preview.get((tenant_id, skill_name))

    def clear_preview(self, tenant_id: str, skill_name: str) -> SkillVariant | None:
        return self._preview.pop((tenant_id, skill_name), None)

    def list_preview_for_tenant(self, tenant_id: str) -> list[SkillVariant]:
        return [v for (tid, _), v in self._preview.items() if tid == tenant_id]

    # ------------------------------------------------------------------
    # sandbox

    def add_sandbox(self, variant: SkillVariant) -> None:
        self._sandbox[variant.variant_id] = variant

    def get_sandbox(self, variant_id: str) -> SkillVariant | None:
        return self._sandbox.get(variant_id)

    def list_sandbox_for_tenant(self, tenant_id: str) -> list[SkillVariant]:
        return [v for v in self._sandbox.values() if v.tenant_id == tenant_id]

    # ------------------------------------------------------------------
    # combined

    def get_variant(self, variant_id: str) -> SkillVariant | None:
        """Look up any variant (promoted, preview, or sandbox) by variant_id."""
        for v in self._promoted.values():
            if v.variant_id == variant_id:
                return v
        for v in self._preview.values():
            if v.variant_id == variant_id:
                return v
        return self._sandbox.get(variant_id)

    def remove_variant(self, variant_id: str) -> bool:
        """Remove a variant from all indexes. Returns True if found."""
        removed = False
        keys_to_del = [k for k, v in self._promoted.items() if v.variant_id == variant_id]
        for k in keys_to_del:
            del self._promoted[k]
            removed = True
        keys_to_del = [k for k, v in self._preview.items() if v.variant_id == variant_id]
        for k in keys_to_del:
            del self._preview[k]
            removed = True
        if self._sandbox.pop(variant_id, None) is not None:
            removed = True
        return removed

    def list_all_for_tenant(self, tenant_id: str) -> list[SkillVariant]:
        return (
            self.list_promoted_for_tenant(tenant_id)
            + self.list_preview_for_tenant(tenant_id)
            + self.list_sandbox_for_tenant(tenant_id)
        )
