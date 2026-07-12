from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import verify_token
from app.db.session import get_db
from app.models import User
from app.schemas.file import FileUploadResponse
from app.utils.file_storage import store_upload_file
from app.utils.file_validation import FileValidationError, validate_upload_file

router = APIRouter(prefix="/files")
bearer_scheme = HTTPBearer(auto_error=False)


def error_response(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    body = {"success": False, "error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=body)


def authenticate_upload_user(
    credentials: HTTPAuthorizationCredentials | None,
    db: Session,
) -> User | JSONResponse:
    if credentials is None:
        return error_response(
            status.HTTP_401_UNAUTHORIZED,
            "UNAUTHORIZED",
            "Authentication required",
        )

    payload = verify_token(credentials.credentials)
    if payload is None or payload.get("type") != "access" or payload.get("sub") is None:
        return error_response(
            status.HTTP_401_UNAUTHORIZED,
            "UNAUTHORIZED",
            "Authentication required",
        )

    user = db.get(User, int(payload["sub"]))
    if user is None:
        return error_response(
            status.HTTP_401_UNAUTHORIZED,
            "UNAUTHORIZED",
            "Authentication required",
        )
    if user.status != "active":
        return error_response(
            status.HTTP_403_FORBIDDEN,
            "FORBIDDEN",
            "User account is not active",
        )
    return user


@router.post("/upload", response_model=FileUploadResponse)
def upload_file_endpoint(
    file: UploadFile | None = File(None),
    upload_type: str | None = Form(None, alias="type"),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> FileUploadResponse | JSONResponse:
    current_user = authenticate_upload_user(credentials, db)
    if isinstance(current_user, JSONResponse):
        return current_user

    try:
        validated_file = validate_upload_file(
            upload_file=file,
            upload_type=upload_type,
            max_image_bytes=settings.max_image_upload_mb * 1024 * 1024,
            max_document_bytes=settings.max_document_upload_mb * 1024 * 1024,
        )
    except FileValidationError as exc:
        response_status = (
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            if exc.code == "FILE_TOO_LARGE"
            else status.HTTP_400_BAD_REQUEST
        )
        return error_response(response_status, exc.code, exc.message, exc.details)

    file_url = store_upload_file(validated_file)
    return FileUploadResponse(
        data={
            "file_url": file_url,
            "type": validated_file.upload_type,
            "mime_type": validated_file.mime_type,
            "size_bytes": validated_file.size_bytes,
            "original_filename": validated_file.original_filename,
        },
        message="File uploaded successfully",
    )
