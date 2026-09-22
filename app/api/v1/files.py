from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import verify_token
from app.db.session import get_db
from app.models import User
from app.schemas.file import FileUploadResponse
from app.utils.file_access import (
    MIME_BY_EXTENSION,
    is_valid_key,
    key_extension,
    resolve_upload_path,
    sign_file_key,
    verify_file_signature,
)
from app.utils.file_storage import store_upload_file
from app.utils.file_validation import (
    CHAT_PHOTO_UPLOAD_TYPE,
    STOP_PHOTO_UPLOAD_TYPE,
    FileValidationError,
    validate_upload_file,
)

router = APIRouter(prefix="/files")
bearer_scheme = HTTPBearer(auto_error=False)


def _can_upload_stop_photo(db: Session, user_id: int) -> bool:
    """Corridor stop evidence photos (Q27/Q47): staff holding ops.corridor_manage only."""
    from app.contracts.enums import Capability
    from app.contracts.errors import DomainError
    from app.modules.identity import service as identity_service

    try:
        return Capability.OPS_CORRIDOR_MANAGE in identity_service.get_capabilities(db, user_id).capabilities
    except DomainError:
        return False


def _chat_attachments_enabled() -> bool:
    """Chat photos are accepted only once A7's contract flag is on (§16, U3/H0)."""
    from app.contracts.communications import CHAT_ATTACHMENTS_ENABLED

    return bool(CHAT_ATTACHMENTS_ENABLED)


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
    if upload_type == STOP_PHOTO_UPLOAD_TYPE and not _can_upload_stop_photo(db, current_user.id):
        # Stage-2 staff-only type; every existing type keeps its v1 behaviour.
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "Not allowed to upload this file type")
    if upload_type == CHAT_PHOTO_UPLOAD_TYPE and not _chat_attachments_enabled():
        # H0 wave 3.1: the type exists so it can be switched on later; until then no orphan chat file is stored.
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "Not allowed to upload this file type")

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

    storage_key = store_upload_file(validated_file, owner_id=current_user.id)
    return FileUploadResponse(
        data={
            # Same field, still a relative URL: now a short-lived signed link.
            # Clients send it back in document/order payloads; the server
            # resolves it to the uploader-bound storage key.
            "file_url": sign_file_key(storage_key),
            "type": validated_file.upload_type,
            "mime_type": validated_file.mime_type,
            "size_bytes": validated_file.size_bytes,
            "original_filename": validated_file.original_filename,
        },
        message="File uploaded successfully",
    )


@router.get("/{file_key:path}", response_model=None)
def download_file_endpoint(
    file_key: str,
    exp: str | None = Query(None),
    sig: str | None = Query(None),
) -> FileResponse | JSONResponse:
    """Serve a private upload through a short-lived signed URL.

    No Bearer header: v1 clients render these URLs in plain image tags. The
    URL is only ever minted inside a response already authorized for the viewer.
    """
    if not is_valid_key(file_key):
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "File not found")
    if not verify_file_signature(file_key, exp, sig):
        return error_response(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "Invalid or expired file link")
    path = resolve_upload_path(file_key)
    if path is None or not path.is_file():
        return error_response(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "File not found")

    extension = key_extension(file_key)
    return FileResponse(
        path,
        media_type=MIME_BY_EXTENSION[extension],
        headers={
            "Content-Disposition": f'inline; filename="{path.name}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )
