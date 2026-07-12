from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict | None = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorBody


class FileUploadData(BaseModel):
    file_url: str
    type: str
    mime_type: str
    size_bytes: int
    original_filename: str


class FileUploadResponse(BaseModel):
    success: bool = True
    data: FileUploadData
    message: str
