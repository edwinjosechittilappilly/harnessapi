from harnessapi import SkillInput, SkillOutput


class Input(SkillInput):
    pass


class Output(SkillOutput):
    tenant_id: str
    document_count: int
    total_chunks: int
    documents: list[dict]
