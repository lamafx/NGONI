from pydantic import BaseModel


class NluEngineSummary(BaseModel):
    id: str
    label: str


class NluEnginesResponse(BaseModel):
    models: list[NluEngineSummary]
    default: str
