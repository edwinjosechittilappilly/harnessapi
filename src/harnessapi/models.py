from pydantic import BaseModel, ConfigDict


class SkillInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
