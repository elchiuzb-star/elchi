from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.utils.file_validation import FileValidationResult


def store_upload_file(validated_file: FileValidationResult) -> str:
    now = datetime.now()
    target_dir = Path(settings.upload_dir) / validated_file.upload_type / f"{now:%Y}" / f"{now:%m}"
    target_dir.mkdir(parents=True, exist_ok=True)

    while True:
        filename = f"{uuid4().hex}.{validated_file.extension}"
        target_path = target_dir / filename
        try:
            with target_path.open("xb") as file:
                file.write(validated_file.content)
            break
        except FileExistsError:
            continue

    return "/".join(
        [
            settings.public_upload_base_url.rstrip("/"),
            validated_file.upload_type,
            f"{now:%Y}",
            f"{now:%m}",
            filename,
        ]
    )
