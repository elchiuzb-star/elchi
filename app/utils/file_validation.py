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
    # Stage 2 (Q27/Q47): corridor meeting-point photo; staff with ops.corridor_manage only (v1 files route).
    "stop_photo",
    # Stage 2 wave 3.1 (H0): private stage-2 images. `dispute_evidence` is attached to a v2 dispute (S6) by its
    # uploader only; `chat_photo` is refused while communications.CHAT_ATTACHMENTS_ENABLED is False.
    "dispute_evidence",
    "chat_photo",
}
STOP_PHOTO_UPLOAD_TYPE = "stop_photo"
DISPUTE_EVIDENCE_UPLOAD_TYPE = "dispute_evidence"
CHAT_PHOTO_UPLOAD_TYPE = "chat_photo"
IMAGE_ONLY_TYPES = {"cargo_photo", "selfie", "car_photo", "stop_photo", "dispute_evidence", "chat_photo"}
DOCUMENT_TYPES = {"passport", "license", "car_document"}

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
ALLOWED_DOCUMENT_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | {"pdf"}
DANGEROUS_EXTENSIONS = {"exe", "bat", "cmd", "sh", "php", "js", "html", "svg", "zip", "rar", "7z"}

ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_DOCUMENT_MIME_TYPES = ALLOWED_IMAGE_MIME_TYPES | {"application/pdf"}


def detect_content_format(content: bytes) -> tuple[str, str] | None:
    """(extension, mime) from header magic bytes, or None. Dependency-free."""
    if content.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp", "image/webp"
    # PDF readers accept the header within the first 1024 bytes.
    if b"%PDF-" in content[:1024]:
        return "pdf", "application/pdf"
    return None


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

    detected = detect_content_format(content)
    if detected is None:
        raise FileValidationError("VALIDATION_ERROR", "File content does not match an allowed file type")
    detected_extension, detected_mime = detected
    # Image vs PDF must agree with the declared extension and the upload type.
    # Within images a mislabelled format (a PNG named .jpg, which the Android
    # picker fallback name can produce) is accepted and stored under its real
    # format, so the served Content-Type is always the true one.
    if (detected_extension == "pdf") != (extension == "pdf") or detected_extension not in allowed_extensions:
        raise FileValidationError("VALIDATION_ERROR", "File content does not match the declared file type")

    return FileValidationResult(
        upload_type=upload_type,
        extension=detected_extension,
        mime_type=detected_mime,
        size_bytes=size_bytes,
        original_filename=original_filename,
        content=content,
    )
