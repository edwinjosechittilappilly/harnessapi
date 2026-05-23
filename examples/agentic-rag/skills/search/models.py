from harnessapi import SkillInput, SkillOutput


class Input(SkillInput):
    query: str
    top_k: int = 5
    include_sources: bool = True


class Output(SkillOutput):
    answer: str
    sources: list[dict]
