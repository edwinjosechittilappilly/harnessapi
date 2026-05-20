from harnessapi import SkillInput, SkillOutput


class Input(SkillInput):
    n: int


class Output(SkillOutput):
    result: int
    steps: list[str]
