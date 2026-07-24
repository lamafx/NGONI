from pydantic import BaseModel


class DiagnosticQuery(BaseModel):
    symptom: str


class DiagnosticResult(BaseModel):
    symptom: str
    diagnosis: str
    next_steps: str
