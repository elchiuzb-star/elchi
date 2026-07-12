from dataclasses import dataclass
from pathlib import PurePath

from fastapi import UploadFile

ALLOWED_UPLOAD_TYPES = {
    "cargo_photo",
    "passport",
    "selfie",
    "license",
    "car_document",
    "car_photo",
}
IMAGE_ONLY_TYPES = {"cargo_photo", "selfie", "car_photo"}
DOCUMENT_TYPES = {"passport", "license", "car_document"}

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
ALLOWED_DOCUMENT_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | {"pdf"}
DANGEROUS_EXTENSIONS = {"exe", "bat", "cmd", "sh", "php", "js", "html", "svg", "zip", "rar", "7z"}

ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_DOCUMENT_MIME_TYPES = ALLOWED_IMAGE_MIME_TYPES | {"application/pdf"}


@dataclass(frozen=True)
class FileValidationResult:
    upload_type: str
    extension: str
    mime_type: str
    size_bytes: int
    original_filename: str
    content: bytes


class FileValidationError(ValueError):
    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def validate_upload_file(
    upload_file: UploadFile | None,
    upload_type: str | None,
    max_image_bytes: int,
    max_document_bytes: int,
) -> FileValidationResult:
    if upload_file is None:
        raise FileValidationError("VALIDATION_ERROR", "File is required")
    if not upload_type:
        raise FileValidationError("VALIDATION_ERROR", "File type is required")
    if upload_type not in ALLOWED_UPLOAD_TYPES:
        raise FileValidationError(
            "VALIDATION_ERROR",
            "Invalid file type",
            {"allowed_types": sorted(ALLOWED_UPLOAD_TYPES)},
        )

    original_filename = PurePath(upload_file.filename or "").name
    if not original_filename:
        raise FileValidationError("VALIDATION_ERROR", "File is required")

    extension = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else ""
    if not extension:
        raise FileValidationError("VALIDATION_ERROR", "Invalid file extension")
    if extension in DANGEROUS_EXTENSIONS:
        raise FileValidationError("VALIDATION_ERROR", "Dangerous file extension is not allowed")

    allowed_extensions = ALLOWED_IMAGE_EXTENSIONS if upload_type in IMAGE_ONLY_TYPES else ALLOWED_DOCUMENT_EXTENSIONS
    if extension not in allowed_extensions:
        raise FileValidationError(
            "VALIDATION_ERROR",
            "Invalid file extension",
            {"allowed_extensions": sorted(allowed_extensions)},
        )

    mime_type = upload_file.content_type or ""
    allowed_mime_types = ALLOWED_IMAGE_MIME_TYPES if upload_type in IMAGE_ONLY_TYPES else ALLOWED_DOCUMENT_MIME_TYPES
    if mime_type not in allowed_mime_types:
        raise FileValidationError(
            "VALIDATION_ERROR",
            "Invalid MIME type",
            {"allowed_mime_types": sorted(allowed_mime_types)},
        )
    if extension == "pdf" and mime_type != "application/pdf":
        raise FileValidationError("VALIDATION_ERROR", "Invalid MIME type for PDF")
    if extension != "pdf" and mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise FileValidationError("VALIDATION_ERROR", "Invalid MIME type for image")

    content = upload_file.file.read()
    size_bytes = len(content)
    if size_bytes == 0:
        raise FileValidationError("VALIDATION_ERROR", "File is empty")

    max_bytes = max_image_bytes if upload_type in IMAGE_ONLY_TYPES else max_document_bytes
    if size_bytes > max_bytes:
        raise FileValidationError("FILE_TOO_LARGE", "File size exceeds allowed limit")

    return FileValidationResult(
        upload_type=upload_type,
        extension=extension,
        mime_type=mime_type,
        size_bytes=size_bytes,
        original_filename=original_filename,
        content=content,
    )
