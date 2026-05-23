from harnessapi import SkillInput, SkillOutput


class Input(SkillInput):
    value: int = 1


class Output(SkillOutput):
    doubled: int
