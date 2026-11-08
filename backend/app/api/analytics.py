from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


# ── Admin endpoints (per-institution) ─────────────────────────────────────────

@router.get("/usage")
async def get_usage(user: dict = Depends(get_current_user)):
    """Full usage stats for the logged-in institution including channel breakdown."""
    return await analytics_service.get_usage_stats(user["client_id"])


@router.get("/channel/{channel}")
async def get_channel_usage(channel: str, user: dict = Depends(get_current_user)):
    """Detailed stats for one channel for the logged-in institution."""
    return await analytics_service.get_channel_stats(user["client_id"], channel)


@router.get("/queries")
async def get_queries(page: int = 1, page_size: int = 20, user: dict = Depends(get_current_user)):
    return await analytics_service.get_query_logs(user["client_id"], page, page_size)


@router.get("/webhook-logs")
async def get_webhook_logs(
    client_id: str | None = None,
    channel: str | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 25,
    user: dict = Depends(get_current_user),
):
    """
    Retrieve real-time request and webhook logs with full JSON payloads and metadata.
    Super admins can filter across all institutions or select a specific institution.
    Regular admins only see their own institution.
    """
    is_super_admin = user.get("role") == "super_admin"
    if is_super_admin:
        target_client_id = client_id if (client_id and client_id != "all") else None
    else:
        target_client_id = user["client_id"]

    return await analytics_service.get_webhook_logs(
        client_id=target_client_id,
        channel=channel,
        status=status,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.get("/user-conversations")
async def get_user_conversations(
    client_id: str | None = None,
    channel: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 25,
    user: dict = Depends(get_current_user),
):
    """
    Retrieve list of segregated user conversations with interaction summary.
    """
    is_super_admin = user.get("role") == "super_admin"
    if is_super_admin:
        target_client_id = client_id if (client_id and client_id != "all") else None
    else:
        target_client_id = user["client_id"]

    return await analytics_service.get_segregated_user_conversations(
        client_id=target_client_id,
        channel=channel,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.get("/user-conversations/{sender_id:path}")
async def get_user_chat_thread(
    sender_id: str,
    client_id: str | None = None,
    channel: str | None = None,
    user: dict = Depends(get_current_user),
):
    """
    Retrieve full WhatsApp-style chat thread for a specific user / phone number.
    """
    is_super_admin = user.get("role") == "super_admin"
    if is_super_admin:
        target_client_id = client_id if (client_id and client_id != "all") else None
    else:
        target_client_id = user["client_id"]

    return await analytics_service.get_user_chat_thread(
        sender_id=sender_id,
        client_id=target_client_id,
        channel=channel,
    )


# ── Super-admin endpoints ──────────────────────────────────────────────────────

@router.get("/super-admin/overview")
async def super_admin_overview(user: dict = Depends(get_current_user)):
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Super admin access required")
    return await analytics_service.get_all_clients_usage()


@router.get("/super-admin/clients/{client_id}")
async def super_admin_client_detail(
    client_id: str,
    page: int = 1,
    page_size: int = 20,
    user: dict = Depends(get_current_user),
):
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Super admin access required")
    return await analytics_service.get_client_detail_usage(client_id, page, page_size)


@router.get("/super-admin/clients/{client_id}/channel/{channel}")
async def super_admin_channel_detail(
    client_id: str,
    channel: str,
    user: dict = Depends(get_current_user),
):
    """Per-channel analytics for a specific institution — super admin view."""
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Super admin access required")
    return await analytics_service.get_channel_stats(client_id, channel)
