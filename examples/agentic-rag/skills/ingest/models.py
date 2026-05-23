from harnessapi import SkillInput, SkillOutput


class Input(SkillInput):
    text: str
    doc_id: str
    metadata: dict[str, str] = {}
    chunk_size: int = 500
    chunk_overlap: int = 50


class Output(SkillOutput):
    doc_id: str
    chunk_count: int
    status: str
