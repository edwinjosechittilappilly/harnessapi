class SkillAPIError(Exception):
    """Base exception for all harnessapi errors."""


class SkillNotFoundError(SkillAPIError):
    """Raised when a skill name cannot be resolved."""


class SkillValidationError(SkillAPIError):
    """Raised when input validation fails against the skill's input model."""


class SkillConflictError(SkillAPIError):
    """Raised when two skills with the same name are registered."""


class SkillHandlerError(SkillAPIError):
    """Raised when a skill handler raises an unexpected exception."""


class EditNotAllowedError(SkillAPIError):
    """Raised when an edit is attempted but the endpoint is disabled."""


class VariantNotFoundError(SkillAPIError):
    """Raised when a tenant skill variant cannot be resolved."""


class VariantValidationError(SkillAPIError):
    """Raised when submitted variant source fails static validation."""


class VariantPromotionError(SkillAPIError):
    """Raised when a variant cannot be promoted (e.g. wrong status, schema mismatch)."""
