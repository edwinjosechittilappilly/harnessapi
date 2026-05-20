from harnessapi import SkillInput, SkillOutput


class Input(SkillInput):
    name: str


class Output(SkillOutput):
    message: str
