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
