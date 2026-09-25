from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str


class Source(BaseModel):
    document: str
    page: int


class AskResponse(BaseModel):
    answer: str
    sources: list[Source] = []