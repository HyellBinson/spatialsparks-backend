
from uuid import uuid4
from io import BytesIO

import logging
import httpx

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from PIL import Image, UnidentifiedImageError

from app.core.database import get_connection
from app.auth.dependencies import (
    get_current_user,
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
)

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_IMAGES_PER_REQUEST = 8
BUCKET_NAME = "inspection-images"

ALLOWED_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}


@router.post("/images")
async def upload_images(
    files: list[UploadFile] = File(...),
    user: dict = Depends(get_current_user),
):
    if not files:
        raise HTTPException(
            status_code=400,
            detail="Select at least one image.",
        )

    if len(files) > MAX_IMAGES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail="Maximum 8 images per request.",
        )

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(
            status_code=500,
            detail="Supabase Storage is not configured.",
        )

    validated_files = []

    for file in files:
        content = await file.read(MAX_FILE_SIZE + 1)

        if not content:
            raise HTTPException(
                status_code=400,
                detail="An uploaded image is empty.",
            )

        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail="Image exceeds the 10 MB limit.",
            )

        try:
            image = Image.open(BytesIO(content))
            image_format = image.format
            image.verify()

        except (
            UnidentifiedImageError,
            OSError,
            Image.DecompressionBombError,
        ):
            raise HTTPException(
                status_code=400,
                detail="Invalid image.",
            )

        if image_format not in ALLOWED_FORMATS:
            raise HTTPException(
                status_code=415,
                detail="Only JPEG, PNG and WEBP images are supported.",
            )

        content_type, extension = ALLOWED_FORMATS[image_format]

        validated_files.append({
            "content": content,
            "original_filename": file.filename,
            "content_type": content_type,
            "extension": extension,
        })

    uploaded_images = []

    try:
        async with httpx.AsyncClient(timeout=60) as client:

            for item in validated_files:
                image_id = str(uuid4())

                storage_path = (
                    f"{user['id']}/{image_id}{item['extension']}"
                )

                response = await client.post(
                    f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/"
                    f"{BUCKET_NAME}/{storage_path}",
                    headers={
                        "apikey": SUPABASE_SERVICE_ROLE_KEY,
                        "Authorization": (
                            f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"
                        ),
                        "Content-Type": item["content_type"],
                        "x-upsert": "false",
                    },
                    content=item["content"],
                )

                if response.status_code not in (200, 201):
                    logger.error(
                        "Supabase Storage upload failed: "
                        "status=%s body=%s",
                        response.status_code,
                        response.text[:2000],
                    )

                    raise HTTPException(
                        status_code=502,
                        detail="Image storage upload failed. Check backend logs.",
                    )

                with get_connection() as connection:
                    connection.execute(
                        """
                        INSERT INTO uploads
                        (
                            id,
                            filename,
                            content_type,
                            file_size,
                            user_id,
                            storage_path
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            image_id,
                            item["original_filename"]
                            or f"{image_id}{item['extension']}",
                            item["content_type"],
                            len(item["content"]),
                            user["id"],
                            storage_path,
                        ),
                    )

                uploaded_images.append({
                    "image_id": image_id,
                    "filename": item["original_filename"],
                    "content_type": item["content_type"],
                    "size": len(item["content"]),
                    "storage_path": storage_path,
                })

    except HTTPException:
        raise

    except httpx.RequestError as error:
        logger.exception(
            "Supabase Storage connection failed: %s",
            str(error),
        )

        raise HTTPException(
            status_code=503,
            detail="Supabase Storage is temporarily unavailable.",
        )

    except Exception:
        logger.exception("Unexpected image upload error.")

        raise HTTPException(
            status_code=500,
            detail="An unexpected image upload error occurred.",
        )

    return {
        "success": True,
        "count": len(uploaded_images),
        "images": uploaded_images,
    }
