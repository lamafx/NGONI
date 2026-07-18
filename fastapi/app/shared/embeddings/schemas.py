from pydantic import BaseModel, Field


class EmbedRequest(BaseModel):
    model_config = {"extra": "forbid"}

    text: str = Field(min_length=1)


class EmbedResponse(BaseModel):
    model_config = {"extra": "forbid"}

    embedding: list[float]


class EmbedBatchRequest(BaseModel):
    model_config = {"extra": "forbid"}

    texts: list[str] = Field(min_length=1)


class EmbedBatchResponse(BaseModel):
    model_config = {"extra": "forbid"}

    embeddings: list[list[float]]
