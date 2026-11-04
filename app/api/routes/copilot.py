
import os
import json
import base64
from uuid import uuid4
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Literal


from app.core.database import get_connection
from app.auth.dependencies import (
    get_current_user,
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
)

router = APIRouter()

BASETEN_API_KEY = os.getenv("BASETEN_API_KEY")
BASETEN_BASE_URL = os.getenv(
    "BASETEN_BASE_URL",
    "https://inference.baseten.co/v1",
).rstrip("/")
BASETEN_MODEL = os.getenv(
    "BASETEN_MODEL",
    "meta-models/muse-spark-open",
)

BUCKET_NAME = "inspection-images"
MAX_IMAGES_PER_REQUEST = 8
MAX_TOTAL_IMAGE_BYTES = 50 * 1024 * 1024
MAX_HISTORY_MESSAGES = 12

SYSTEM_PROMPT = """
You are SpatialSparks Copilot, an expert AI assistant for inspecting
electronic devices, circuit boards, hardware, electrical components,
and technical equipment.

Your responsibilities:
- Carefully analyze images supplied by the user.
- Identify visible components, ports, wires, labels, damage, and defects.
- Explain technical problems in clear, practical language.
- Suggest safe, step-by-step troubleshooting.
- Distinguish between what you can actually see and what you are inferring.
- Never invent component values, model numbers, or measurements.
- If an image is unclear, ask the user for a clearer image.
- Warn users before potentially dangerous electrical work.
- Never instruct users to touch exposed live electrical components.

Be helpful, precise, and conversational. Keep answers readable.
"""


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    image_ids: list[str] = Field(default_factory=list, max_length=8)


class CreateSessionRequest(BaseModel):
    title: str = Field(default="New inspection", min_length=1, max_length=120)
    project_type: Literal["inspection", "copilot"] = "inspection"


class RenameSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)

def get_image_records(image_ids: list[str], user_id: str):
    """Retrieve image metadata belonging to the authenticated user."""

    if not image_ids:
        return []

    placeholders = ", ".join(["%s"] * len(image_ids))

    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT id, filename, content_type, storage_path, file_size
            FROM uploads
            WHERE id IN ({placeholders})
              AND user_id = %s
            """,
            (*image_ids, user_id),
        ).fetchall()

    if len(rows) != len(image_ids):
        raise HTTPException(
            status_code=404,
            detail="One or more images were not found or do not belong to you.",
        )

    for row in rows:
        if not row["storage_path"]:
            raise HTTPException(
                status_code=400,
                detail="An attached image has no storage path.",
            )

    return rows


async def download_images(image_records):
    """Download private images from Supabase Storage."""

    if not image_records:
        return []

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(
            status_code=500,
            detail="Supabase Storage is not configured.",
        )

    total_size = sum(
        int(record["file_size"] or 0)
        for record in image_records
    )

    if total_size > MAX_TOTAL_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Attached images exceed the combined size limit.",
        )

    downloaded = []

    try:
        async with httpx.AsyncClient(timeout=90) as client:
            for record in image_records:
                storage_path = quote(record["storage_path"], safe="/")

                response = await client.get(
                    f"{SUPABASE_URL}/storage/v1/object/"
                    f"{BUCKET_NAME}/{storage_path}",
                    headers={
                        "apikey": SUPABASE_SERVICE_ROLE_KEY,
                        "Authorization": (
                            f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"
                        ),
                    },
                )

                if response.status_code != 200:
                    raise HTTPException(
                        status_code=502,
                        detail="Could not retrieve an attached image.",
                    )

                content_type = record["content_type"]

                if content_type not in (
                    "image/jpeg",
                    "image/png",
                    "image/webp",
                ):
                    raise HTTPException(
                        status_code=415,
                        detail="An attached image has an unsupported format.",
                    )

                image_base64 = base64.b64encode(
                    response.content
                ).decode("utf-8")

                downloaded.append({
                    "filename": record["filename"],
                    "content_type": content_type,
                    "base64": image_base64,
                })

    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail="Supabase Storage is temporarily unavailable.",
        )

    return downloaded


async def generate_ai_reply(
    content: str,
    conversation_history: list,
    images: list,
):
    """Send conversation and image content to Muse Spark Open."""

    if not BASETEN_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Baseten API key is not configured on the backend.",
        )

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        }
    ]

    for message in conversation_history:
        role = message["role"]

        if role not in ("user", "assistant"):
            continue

        messages.append({
            "role": role,
            "content": message["content"],
        })

    # Attach actual image content to the current user message.
    user_content = [
        {
            "type": "text",
            "text": content,
        }
    ]

    for image in images:
        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": (
                    f"data:{image['content_type']};base64,"
                    f"{image['base64']}"
                )
            },
        })

    # If images exist, use multimodal content.
    # Otherwise, send an ordinary text message.
    if images:
        messages.append({
            "role": "user",
            "content": user_content,
        })
    else:
        messages.append({
            "role": "user",
            "content": content,
        })

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                f"{BASETEN_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {BASETEN_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": BASETEN_MODEL,
                    "messages": messages,
                    "max_tokens": 1500,
                    "reasoning_effort": "medium",
                },
            )

        if response.status_code == 401:
            raise HTTPException(
                status_code=502,
                detail="Baseten rejected the API key. Check your backend configuration.",
            )

        if response.status_code == 429:
            raise HTTPException(
                status_code=503,
                detail="Baseten rate limit or usage limit reached. Please try again later.",
            )

        if response.status_code == 402:
            raise HTTPException(
                status_code=503,
                detail="Baseten requires available credits or billing before inference.",
            )

        if response.status_code >= 400:
            print(
                "Baseten error:",
                response.status_code,
                response.text[:1000],
            )
            raise HTTPException(
                status_code=502,
                detail="The AI provider could not process this request.",
            )

        data = response.json()

        reply = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content")
        )

        if isinstance(reply, list):
            reply = "\n".join(
                item.get("text", "")
                for item in reply
                if isinstance(item, dict)
            )

        if not isinstance(reply, str) or not reply.strip():
            raise HTTPException(
                status_code=502,
                detail="The AI provider returned an empty response.",
            )

        return reply.strip()

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="The AI request timed out. Please try again.",
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail="Could not connect to the AI provider.",
        )


@router.post("/sessions")
async def create_session(
    request: CreateSessionRequest | None = None,
    user: dict = Depends(get_current_user),
):
    request = request or CreateSessionRequest()

    session_id = str(uuid4())
    title = request.title.strip() or "New inspection"

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO conversations
                (id, user_id, title, project_type, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            """,
            (
                session_id,
                user["id"],
                title,
                request.project_type,
            ),
        )

    return {
        "success": True,
        "conversation_id": session_id,
        "title": title,
        "project_type": request.project_type,
    }    


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    request: MessageRequest,
    user: dict = Depends(get_current_user),
):
    content = request.content.strip()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty.",
        )

    if len(set(request.image_ids)) != len(request.image_ids):
        raise HTTPException(
            status_code=400,
            detail="Duplicate image IDs are not allowed.",
        )

    # Verify conversation ownership.
    with get_connection() as connection:
        session = connection.execute(
            """
            SELECT id
            FROM conversations
            WHERE id = %s AND user_id = %s
            """,
            (session_id, user["id"]),
        ).fetchone()

        if not session:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found.",
            )

    # Verify image ownership before calling the AI.
    image_records = get_image_records(
        request.image_ids,
        user["id"],
    )

    # Retrieve private image bytes from Supabase.
    images = await download_images(image_records)

    # Save the user's message.
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO messages
            (conversation_id, role, content, image_ids)
            VALUES (%s, %s, %s, %s)
            """,
            (
                session_id,
                "user",
                content,
                json.dumps(request.image_ids),
            ),
        )

                # Update activity and automatically name a new inspection.
        connection.execute(
            """
            UPDATE conversations
            SET
                updated_at = NOW(),
                title = CASE
                    WHEN title = 'New inspection'
                    THEN LEFT(%s, 60)
                    ELSE title
                END
            WHERE id = %s AND user_id = %s
            """,
            (content, session_id, user["id"]),
        )

        connection.execute(
            """
            UPDATE conversations
            SET updated_at = NOW()
            WHERE id = %s AND user_id = %s
            """,
            (session_id, user["id"]),
        )

        # Load recent conversation history, including this message.
        history_rows = connection.execute(
            """
            SELECT role, content
            FROM (
                SELECT id, role, content
                FROM messages
                WHERE conversation_id = %s
                ORDER BY id DESC
                LIMIT %s
            ) recent
            ORDER BY id ASC
            """,
            (session_id, MAX_HISTORY_MESSAGES),
        ).fetchall()

    # The current user message is sent separately with its images.
    # Remove it from the history to avoid sending it twice.
    conversation_history = list(history_rows[:-1])

    # Generate the actual Muse Spark Open response.
    assistant_reply = await generate_ai_reply(
        content,
        conversation_history,
        images,
    )

    # Save the assistant response.
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO messages
            (conversation_id, role, content, image_ids)
            VALUES (%s, %s, %s, %s)
            """,
            (
                session_id,
                "assistant",
                assistant_reply,
                "[]",
            ),
        )

    return {
        "success": True,
        "conversation_id": session_id,
        "user_message": content,
        "attached_images": request.image_ids,
        "assistant_reply": assistant_reply,
        "ai_connected": True,
    }


@router.get("/sessions")
async def get_sessions(
    user: dict = Depends(get_current_user),
):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                c.id,
                c.title,
                c.project_type,
                c.created_at,
                c.updated_at,
                (
                    SELECT content
                    FROM messages m
                    WHERE m.conversation_id = c.id
                    ORDER BY m.id DESC
                    LIMIT 1
                ) AS last_message
            FROM conversations c
            WHERE c.user_id = %s
            ORDER BY c.updated_at DESC, c.created_at DESC
            """,
            (user["id"],),
        ).fetchall()

    return {
        "success": True,
        "conversations": [
            {
                "id": str(row["id"]),
                "title": row["title"],
                "project_type": row["project_type"],
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat(),
                "last_message": row["last_message"],
            }
            for row in rows
        ],
    }

@router.get("/sessions/{session_id}/messages")
async def get_messages(
    session_id: str,
    user: dict = Depends(get_current_user),
):
    with get_connection() as connection:
        session = connection.execute(
            """
            SELECT id
            FROM conversations
            WHERE id = %s AND user_id = %s
            """,
            (session_id, user["id"]),
        ).fetchone()

        if not session:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found.",
            )

        rows = connection.execute(
            """
            SELECT id, role, content, image_ids, created_at
            FROM messages
            WHERE conversation_id = %s
            ORDER BY id ASC
            """,
            (session_id,),
        ).fetchall()

    return {
        "success": True,
        "conversation_id": session_id,
        "messages": [
            {
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "image_ids": json.loads(row["image_ids"]),
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ],
    }


@router.patch("/sessions/{session_id}")
async def rename_session(
    session_id: str,
    request: RenameSessionRequest,
    user: dict = Depends(get_current_user),
):
    title = request.title.strip()

    if not title:
        raise HTTPException(
            status_code=400,
            detail="Inspection name cannot be empty.",
        )

    with get_connection() as connection:
        result = connection.execute(
            """
            UPDATE conversations
            SET title = %s, updated_at = NOW()
            WHERE id = %s AND user_id = %s
            RETURNING id, title, project_type, updated_at
            """,
            (title, session_id, user["id"]),
        ).fetchone()

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    return {
        "success": True,
        "id": str(result["id"]),
        "title": result["title"],
        "project_type": result["project_type"],
        "updated_at": result["updated_at"].isoformat(),
    }


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    user: dict = Depends(get_current_user),
):
    with get_connection() as connection:
        result = connection.execute(
            """
            DELETE FROM conversations
            WHERE id = %s AND user_id = %s
            RETURNING id
            """,
            (session_id, user["id"]),
        ).fetchone()

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    return {
        "success": True,
        "message": "Inspection deleted successfully.",
    }



import asyncio


FAL_API_KEY = os.getenv("FAL_KEY")
FAL_SAM_MODEL = "fal-ai/sam-3/image"


class SegmentImageRequest(BaseModel):
    image_id: str
    prompt: str = Field(
        default="electronic component",
        min_length=1,
        max_length=200,
    )


@router.post("/sessions/{session_id}/segment")
async def segment_inspection_image(
    session_id: str,
    request: SegmentImageRequest,
    user: dict = Depends(get_current_user),
):
    """
    Segment a requested object in an image using Meta SAM 3
    hosted by fal.ai.
    """

    if not FAL_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="fal.ai API key is not configured on the backend.",
        )

    # Verify that this conversation belongs to the user.
    with get_connection() as connection:
        session = connection.execute(
            """
            SELECT id
            FROM conversations
            WHERE id = %s AND user_id = %s
            """,
            (session_id, user["id"]),
        ).fetchone()

    if not session:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    # Verify that the image belongs to this user.
    image_records = get_image_records(
        [request.image_id],
        user["id"],
    )

    images = await download_images(image_records)

    if not images:
        raise HTTPException(
            status_code=404,
            detail="Inspection image not found.",
        )

    image = images[0]

    # fal.ai accepts base64 data URIs for image inputs.
    image_data_uri = (
        f"data:{image['content_type']};base64,"
        f"{image['base64']}"
    )

    try:
        import fal_client

        result = await asyncio.to_thread(
            fal_client.subscribe,
            FAL_SAM_MODEL,
            arguments={
                "image_url": image_data_uri,
                "prompt": request.prompt.strip(),
                "apply_mask": True,
                "return_multiple_masks": True,
                "max_masks": 3,
                "include_scores": True,
                "include_boxes": True,
            },
        )

        return {
            "success": True,
            "model": FAL_SAM_MODEL,
            "prompt": request.prompt.strip(),
            "segmentation": result,
        }

    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="fal-client is not installed. Run pip install fal-client.",
        )

    except Exception as error:
        error_text = str(error)
        print("SAM segmentation error:", error_text[:1000])

        if "402" in error_text or "payment" in error_text.lower():
            raise HTTPException(
                status_code=402,
                detail="fal.ai requires available credits for SAM inference.",
            )

        if "401" in error_text or "unauthorized" in error_text.lower():
            raise HTTPException(
                status_code=502,
                detail="fal.ai rejected the API key. Check FAL_KEY.",
            )

        raise HTTPException(
            status_code=502,
            detail="SAM could not segment this image. Please try again.",
        )
