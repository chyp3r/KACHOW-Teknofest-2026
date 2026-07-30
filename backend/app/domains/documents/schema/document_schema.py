from pydantic import BaseModel, Field
from typing import List

class DocumentUploadSchema(BaseModel):
    filename: str

class DocumentClassificationSchema(BaseModel):
    document_id: str
    document_type: str
    confidence: float

class DocumentAnalysisSchema(BaseModel):
    document_id: str
    extracted_entities: List[str]
    missing_info: List[str]
    recommended_rules: List[str]
    summary: str

class DocumentDraftSchema(BaseModel):
    document_id: str
    draft_type: str
    draft_content: str
    is_official_tone: bool

class DocumentRouteSchema(BaseModel):
    document_id: str
    target_unit: str
    reason: str
