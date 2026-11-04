
import base64
import logging
import mimetypes
import os
import tempfile

from pathlib import Path
from functools import lru_cache

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool
from gradio_client import Client, handle_file

router = APIRouter(prefix="/api/v1/sam", tags=["SAM Vision"])

SPACE_ID = "prithivMLmods/SAM3-Demo"
MAX_IMAGE_SIZE = 12 * 1024 * 1024

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_sam_client():
    """Reuse the Gradio client instead of reconnecting for every request."""
    return Client(SPACE_ID)


def encode_result(value):
    """Convert returned local image files into browser-readable data URLs."""

    if isinstance(value, dict):
        return {
            key: encode_result(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [encode_result(item) for item in value]

    if isinstance(value, str) and os.path.isfile(value):
        mime_type, _ = mimetypes.guess_type(value)
        mime_type = mime_type or "image/png"

        with open(value, "rb") as image_file:
            encoded = base64.b64encode(
                image_file.read()
            ).decode("utf-8")

        return f"data:{mime_type};base64,{encoded}"

    return value


def run_sam_segmentation(image_path: str, prompt: str, confidence: float):
    client = get_sam_client()

    return client.predict(
        source_img=handle_file(image_path),
        text_query=prompt,
        conf_thresh=confidence,
        api_name="/run_image_segmentation",
    )


@router.post("/segment")
async def segment_image(
    image: UploadFile = File(...),
    text_query: str = Form(..., min_length=1, max_length=200),
    conf_thresh: float = Form(default=0.45, ge=0, le=1),
):
    """Segment objects in an uploaded image using the hosted SAM demo."""

    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Please upload a valid image.",
        )

    contents = await image.read(MAX_IMAGE_SIZE + 1)

    if not contents:
        raise HTTPException(status_code=400, detail="Image is empty.")

    if len(contents) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Image must be smaller than 12 MB.",
        )

    suffix = Path(image.filename or "inspection.png").suffix or ".png"

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as temp_file:
            temp_file.write(contents)
            temp_path = temp_file.name

        result = await run_in_threadpool(
            run_sam_segmentation,
            temp_path,
            text_query.strip(),
            conf_thresh,
        )

        return {
            "success": True,
            "model": SPACE_ID,
            "prompt": text_query,
            "confidence": conf_thresh,
            "result": encode_result(result),
        }

    except Exception:
        logger.exception("SAM segmentation request failed.")

        raise HTTPException(
            status_code=502,
            detail="SAM segmentation service failed. Please try again.",
        )

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
