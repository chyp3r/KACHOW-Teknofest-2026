class DocumentModel:
    """Skeletal SQLAlchemy model representing documents."""
    __tablename__ = "documents"
    id: str
    filename: str
    content: str
    classification: str
    analysis_results: str
    draft_text: str
    routed_unit: str
