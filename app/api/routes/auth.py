
import os
from pathlib import Path
from uuid import uuid4
from typing import Literal

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Depends
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from pydantic import BaseModel

from app.core.database import get_connection
from app.auth.dependencies import create_access_token, get_current_user

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

router = APIRouter()


class GoogleLoginRequest(BaseModel):
    credential: str
    mode: Literal["signin", "signup"]


@router.post("/google")
def google_login(data: GoogleLoginRequest):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=500,
            detail="Google authentication is not configured.",
        )

    try:
        google_user = id_token.verify_oauth2_token(
            data.credential,
            Request(),
            GOOGLE_CLIENT_ID,
        )
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Google authentication failed. Please try again.",
        )

    email = google_user.get("email")
    google_sub = google_user.get("sub")
    full_name = google_user.get("name")
    avatar_url = google_user.get("picture")

    if not email or not google_sub or not google_user.get("email_verified"):
        raise HTTPException(
            status_code=401,
            detail="A verified Google email is required.",
        )

    with get_connection() as connection:
        user = connection.execute(
            """
            SELECT id, email, full_name, avatar_url, google_sub
            FROM public.users
            WHERE google_sub = %s
               OR LOWER(email) = LOWER(%s)
            LIMIT 1
            """,
            (google_sub, email),
        ).fetchone()

        if data.mode == "signin" and not user:
            raise HTTPException(
                status_code=404,
                detail="No SpatialSparks account exists for this Google email. Please create an account first.",
            )

        if data.mode == "signup" and user:
            raise HTTPException(
                status_code=409,
                detail="An account with this email already exists. Please sign in instead.",
            )

        if user:
            if user["google_sub"] and user["google_sub"] != google_sub:
                raise HTTPException(
                    status_code=409,
                    detail="This email is linked to another Google account.",
                )

            user = connection.execute(
                """
                UPDATE public.users
                SET google_sub = %s,
                    full_name = COALESCE(%s, full_name),
                    avatar_url = COALESCE(%s, avatar_url),
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id, email, full_name, avatar_url
                """,
                (google_sub, full_name, avatar_url, user["id"]),
            ).fetchone()

        else:
            user = connection.execute(
                """
                INSERT INTO public.users (
                    id,
                    email,
                    full_name,
                    avatar_url,
                    google_sub,
                    provider
                )
                VALUES (%s, %s, %s, %s, %s, 'google')
                RETURNING id, email, full_name, avatar_url
                """,
                (str(uuid4()), email, full_name, avatar_url, google_sub),
            ).fetchone()

    access_token = create_access_token(
        str(user["id"]),
        user["email"],
    )

    return {
        "success": True,
        "message": "Authentication successful.",
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": str(user["id"]),
            "email": user["email"],
            "full_name": user["full_name"],
            "avatar_url": user["avatar_url"],
        },
    }


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    return {
        "success": True,
        "user": user,
    }
