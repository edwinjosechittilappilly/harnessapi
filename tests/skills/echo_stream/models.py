from harnessapi import SkillInput, SkillOutput


class Input(SkillInput):
    text: str


class Output(SkillOutput):
    result: str
