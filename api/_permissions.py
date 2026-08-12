from __future__ import annotations

import json
import os
from typing import Any

from api._lark import LarkAPIError
from api._postgres_base import _connection


ROLES = ("viewer", "entry_user", "schedule_manager", "super_admin")
ROLE_RANK = {role: index for index, role in enumerate(ROLES)}
ROLE_LABELS = {
    "viewer": "Viewer only",
    "entry_user": "Entry user",
    "schedule_manager": "Schedule manager",
    "super_admin": "Super admin",
}
REQUESTABLE_ROLES = ("viewer", "entry_user", "schedule_manager")
_SCHEMA_READY = False


def admin_ids() -> set[str]:
    return {
        value.strip()
        for value in os.environ.get("LARK_ADMIN_OPEN_IDS", "").split(",")
        if value.strip()
    }


def ensure_permission_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    try:
        with _connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workforce_app_users (
                        open_id TEXT PRIMARY KEY,
                        display_name TEXT NOT NULL DEFAULT '',
                        avatar_url TEXT NOT NULL DEFAULT '',
                        role TEXT NOT NULL DEFAULT 'viewer'
                            CHECK (role IN ('viewer', 'entry_user',
                                           'schedule_manager', 'super_admin')),
                        role_assigned_by TEXT,
                        role_assigned_at TIMESTAMPTZ,
                        first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workforce_access_requests (
                        id BIGSERIAL PRIMARY KEY,
                        requester_open_id TEXT NOT NULL
                            REFERENCES workforce_app_users(open_id)
                            ON DELETE CASCADE,
                        requested_role TEXT NOT NULL
                            CHECK (requested_role IN ('viewer', 'entry_user',
                                                     'schedule_manager')),
                        reason TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'approved', 'rejected',
                                             'cancelled')),
                        requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        reviewed_by TEXT,
                        reviewed_at TIMESTAMPTZ,
                        review_note TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS
                        workforce_access_requests_one_pending
                    ON workforce_access_requests (requester_open_id)
                    WHERE status = 'pending'
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS workforce_access_requests_status
                    ON workforce_access_requests (status, requested_at DESC)
                    """
                )
        _SCHEMA_READY = True
    except LarkAPIError:
        raise
    except Exception as error:
        raise LarkAPIError(
            f"Could not initialize permission storage: {type(error).__name__}.",
            status=503,
        ) from error


def _clean_text(value: Any, *, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def register_user(current_session: dict) -> dict:
    ensure_permission_schema()
    open_id = _clean_text(current_session.get("sub"), limit=160)
    if not open_id:
        raise LarkAPIError("The signed-in Lark account has no user ID.", status=401)
    name = _clean_text(current_session.get("name"), limit=160)
    avatar = _clean_text(current_session.get("avatar"), limit=1000)
    try:
        with _connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO workforce_app_users
                        (open_id, display_name, avatar_url)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (open_id) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        avatar_url = EXCLUDED.avatar_url,
                        last_seen_at = NOW()
                    RETURNING open_id, display_name, avatar_url, role,
                              first_seen_at, last_seen_at
                    """,
                    (open_id, name, avatar),
                )
                row = cursor.fetchone()
    except LarkAPIError:
        raise
    except Exception as error:
        raise LarkAPIError(
            f"Could not register the signed-in user: {type(error).__name__}.",
            status=503,
        ) from error
    return _user_row(row, open_id in admin_ids())


def _user_row(row: tuple, env_super_admin: bool = False) -> dict:
    stored_role = str(row[3] or "viewer")
    effective_role = "super_admin" if env_super_admin else stored_role
    return {
        "open_id": str(row[0]),
        "name": str(row[1] or ""),
        "avatar": str(row[2] or ""),
        "stored_role": stored_role,
        "role": effective_role,
        "role_label": ROLE_LABELS[effective_role],
        "env_super_admin": env_super_admin,
        "first_seen_at": row[4].isoformat() if row[4] else "",
        "last_seen_at": row[5].isoformat() if row[5] else "",
    }


def effective_role(current_session: dict, *, register: bool = True) -> str:
    open_id = _clean_text(current_session.get("sub"), limit=160)
    if open_id in admin_ids():
        if register:
            register_user(current_session)
        return "super_admin"
    if register:
        return str(register_user(current_session)["role"])
    ensure_permission_schema()
    try:
        with _connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT role FROM workforce_app_users WHERE open_id = %s",
                    (open_id,),
                )
                row = cursor.fetchone()
        return str(row[0]) if row else "viewer"
    except Exception as error:
        raise LarkAPIError(
            f"Could not read user permission: {type(error).__name__}.", status=503,
        ) from error


def is_super_admin(current_session: dict) -> bool:
    if _clean_text(current_session.get("sub"), limit=160) in admin_ids():
        return True
    try:
        return effective_role(current_session, register=False) == "super_admin"
    except LarkAPIError:
        return False


def role_allows(role: str, minimum_role: str) -> bool:
    return ROLE_RANK.get(role, 0) >= ROLE_RANK[minimum_role]


def permissions_for(role: str) -> dict[str, bool]:
    return {
        "can_view": True,
        "can_enter": role_allows(role, "entry_user"),
        "can_manage_schedule": role_allows(role, "schedule_manager"),
        "can_approve_conflicts": role_allows(role, "schedule_manager"),
        "can_manage_access": role == "super_admin",
    }


def require_role(handler, current_session: dict, minimum_role: str) -> bool:
    role = effective_role(current_session)
    if role_allows(role, minimum_role):
        return True
    from api._shared import json_response

    json_response(
        handler,
        {
            "error": f"This action requires {ROLE_LABELS[minimum_role]} access.",
            "code": "role_required",
            "required_role": minimum_role,
            "current_role": role,
        },
        403,
    )
    return False


def _request_row(row: tuple) -> dict:
    return {
        "id": int(row[0]),
        "open_id": str(row[1]),
        "name": str(row[2] or ""),
        "avatar": str(row[3] or ""),
        "current_role": str(row[4] or "viewer"),
        "requested_role": str(row[5]),
        "requested_role_label": ROLE_LABELS[str(row[5])],
        "reason": str(row[6] or ""),
        "status": str(row[7]),
        "requested_at": row[8].isoformat() if row[8] else "",
        "reviewed_by": str(row[9] or ""),
        "reviewed_at": row[10].isoformat() if row[10] else "",
        "review_note": str(row[11] or ""),
    }


def access_snapshot(current_session: dict) -> dict:
    ensure_permission_schema()
    current_user = register_user(current_session)
    open_id = current_user["open_id"]
    can_manage = current_user["role"] == "super_admin"
    try:
        with _connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT request.id, request.requester_open_id,
                           app_user.display_name, app_user.avatar_url,
                           app_user.role, request.requested_role, request.reason,
                           request.status, request.requested_at,
                           request.reviewed_by, request.reviewed_at,
                           request.review_note
                    FROM workforce_access_requests AS request
                    JOIN workforce_app_users AS app_user
                      ON app_user.open_id = request.requester_open_id
                    WHERE request.requester_open_id = %s
                    ORDER BY request.requested_at DESC
                    LIMIT 1
                    """,
                    (open_id,),
                )
                own_request_row = cursor.fetchone()
                pending_rows = []
                users_rows = []
                if can_manage:
                    cursor.execute(
                        """
                        SELECT request.id, request.requester_open_id,
                               app_user.display_name, app_user.avatar_url,
                               app_user.role, request.requested_role,
                               request.reason, request.status,
                               request.requested_at, request.reviewed_by,
                               request.reviewed_at, request.review_note
                        FROM workforce_access_requests AS request
                        JOIN workforce_app_users AS app_user
                          ON app_user.open_id = request.requester_open_id
                        WHERE request.status = 'pending'
                        ORDER BY request.requested_at ASC
                        """
                    )
                    pending_rows = cursor.fetchall()
                    cursor.execute(
                        """
                        SELECT open_id, display_name, avatar_url, role,
                               first_seen_at, last_seen_at
                        FROM workforce_app_users
                        ORDER BY LOWER(display_name), open_id
                        """
                    )
                    users_rows = cursor.fetchall()
    except LarkAPIError:
        raise
    except Exception as error:
        raise LarkAPIError(
            f"Could not load access settings: {type(error).__name__}.", status=503,
        ) from error
    return {
        "user": current_user,
        "permissions": permissions_for(current_user["role"]),
        "requestable_roles": [
            {"id": role, "label": ROLE_LABELS[role]}
            for role in REQUESTABLE_ROLES
        ],
        "latest_request": _request_row(own_request_row) if own_request_row else None,
        "pending_requests": [_request_row(row) for row in pending_rows],
        "users": [
            _user_row(row, str(row[0]) in admin_ids()) for row in users_rows
        ],
    }


def schedule_notification_recipients(current_open_id: str = "") -> list[dict]:
    """Return users who may receive schedule-conflict notifications.

    Super administrators are marked as required recipients. Schedule managers
    remain optional and can be selected by the person submitting the plan.
    Environment bootstrap administrators are included even when their stored
    database role has not yet been updated.
    """
    ensure_permission_schema()
    configured_admins = admin_ids()
    try:
        with _connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT open_id, display_name, role
                    FROM workforce_app_users
                    WHERE role IN ('schedule_manager', 'super_admin')
                       OR open_id = ANY(%s::text[])
                    ORDER BY LOWER(display_name), open_id
                    """,
                    (list(configured_admins),),
                )
                rows = cursor.fetchall()
    except LarkAPIError:
        raise
    except Exception as error:
        raise LarkAPIError(
            f"Could not load schedule notification recipients: {type(error).__name__}.",
            status=503,
        ) from error

    recipients: dict[str, dict] = {}
    for open_id, display_name, stored_role in rows:
        recipient_id = str(open_id or "").strip()
        if not recipient_id:
            continue
        role = "super_admin" if recipient_id in configured_admins else str(stored_role)
        recipients[recipient_id] = {
            "open_id": recipient_id,
            "name": str(display_name or "").strip() or "Unnamed Lark user",
            "role": role,
            "role_label": ROLE_LABELS.get(role, role),
            "required": role == "super_admin",
            "current": recipient_id == current_open_id,
        }

    # A configured administrator may not have signed in since the permission
    # table was introduced. Keep the ID available so conflicts still attempt
    # to notify every bootstrap administrator.
    for recipient_id in configured_admins:
        recipients.setdefault(
            recipient_id,
            {
                "open_id": recipient_id,
                "name": "Configured administrator",
                "role": "super_admin",
                "role_label": ROLE_LABELS["super_admin"],
                "required": True,
                "current": recipient_id == current_open_id,
            },
        )

    return sorted(
        recipients.values(),
        key=lambda item: (
            not item["required"],
            item["name"].casefold(),
            item["open_id"],
        ),
    )


def submit_request(current_session: dict, requested_role: str, reason: str) -> dict:
    ensure_permission_schema()
    current_user = register_user(current_session)
    if requested_role not in REQUESTABLE_ROLES:
        raise ValueError("Choose Viewer only, Entry user, or Schedule manager.")
    if role_allows(current_user["role"], requested_role):
        raise ValueError("Your current access already includes that role.")
    reason = _clean_text(reason, limit=500)
    try:
        with _connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO workforce_access_requests
                        (requester_open_id, requested_role, reason)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (requester_open_id)
                        WHERE status = 'pending'
                    DO UPDATE SET requested_role = EXCLUDED.requested_role,
                                  reason = EXCLUDED.reason,
                                  requested_at = NOW()
                    """,
                    (current_user["open_id"], requested_role, reason),
                )
        return _notify_super_admins(current_user, requested_role, reason)
    except Exception as error:
        if isinstance(error, LarkAPIError):
            raise
        raise LarkAPIError(
            f"Could not submit the access request: {type(error).__name__}.",
            status=503,
        ) from error


def _app_link() -> str:
    configured = os.environ.get("APP_URL", "").strip().rstrip("/")
    if configured:
        return f"{configured}/#settings"
    production = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL", "").strip().rstrip("/")
    if production:
        if not production.startswith("http"):
            production = f"https://{production}"
        return f"{production}/#settings"
    return "https://workforce-app-theta.vercel.app/#settings"


def _notify_super_admins(user: dict, requested_role: str, reason: str) -> dict:
    """Best-effort Lark notification; the database request is authoritative."""
    try:
        from api._lark import LarkAPIError as LarkMessageError
        from api._lark import lark_api, tenant_access_token

        with _connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT open_id FROM workforce_app_users WHERE role = 'super_admin'"
                )
                recipients = {str(row[0]) for row in cursor.fetchall() if row[0]}
        recipients.update(admin_ids())
        if not recipients:
            return {"attempted": 0, "sent": 0, "failed": 0}
        text = (
            "Workforce access request\n"
            f"User: {user.get('name') or user.get('open_id')}\n"
            f"Requested role: {ROLE_LABELS[requested_role]}\n"
            f"Reason: {reason or 'No reason supplied.'}\n"
            f"Review: {_app_link()}"
        )
        token = tenant_access_token()
        sent = 0
        failed = 0
        for recipient in recipients:
            try:
                lark_api(
                    "POST",
                    "/im/v1/messages",
                    token=token,
                    query={"receive_id_type": "open_id"},
                    body={
                        "receive_id": recipient,
                        "msg_type": "text",
                        "content": json.dumps({"text": text}, ensure_ascii=False),
                    },
                )
                sent += 1
            except LarkMessageError:
                failed += 1
        return {"attempted": len(recipients), "sent": sent, "failed": failed}
    except Exception:
        # Notification permissions, recipient availability, and network state
        # must never turn a persisted access request into a failed request.
        return {"attempted": 0, "sent": 0, "failed": 1}


def review_request(
    current_session: dict, request_id: int, decision: str, review_note: str,
) -> None:
    reviewer = register_user(current_session)
    if reviewer["role"] != "super_admin":
        raise PermissionError("Only a Super Admin can review access requests.")
    if decision not in {"approved", "rejected"}:
        raise ValueError("Choose Approve or Reject.")
    review_note = _clean_text(review_note, limit=500)
    try:
        with _connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT requester_open_id, requested_role
                    FROM workforce_access_requests
                    WHERE id = %s AND status = 'pending'
                    FOR UPDATE
                    """,
                    (request_id,),
                )
                request_row = cursor.fetchone()
                if not request_row:
                    raise ValueError("This access request is no longer pending.")
                requester_id, requested_role = request_row
                cursor.execute(
                    """
                    UPDATE workforce_access_requests
                    SET status = %s, reviewed_by = %s, reviewed_at = NOW(),
                        review_note = %s
                    WHERE id = %s
                    """,
                    (decision, reviewer["open_id"], review_note, request_id),
                )
                if decision == "approved":
                    cursor.execute(
                        """
                        UPDATE workforce_app_users
                        SET role = %s, role_assigned_by = %s,
                            role_assigned_at = NOW()
                        WHERE open_id = %s
                        """,
                        (requested_role, reviewer["open_id"], requester_id),
                    )
    except (ValueError, PermissionError):
        raise
    except Exception as error:
        raise LarkAPIError(
            f"Could not review the access request: {type(error).__name__}.",
            status=503,
        ) from error


def set_user_role(current_session: dict, target_open_id: str, role: str) -> None:
    reviewer = register_user(current_session)
    if reviewer["role"] != "super_admin":
        raise PermissionError("Only a Super Admin can change user roles.")
    if role not in ROLES:
        raise ValueError("Choose a valid role.")
    target_open_id = _clean_text(target_open_id, limit=160)
    if target_open_id in admin_ids() and role != "super_admin":
        raise ValueError("A Vercel bootstrap administrator cannot be demoted here.")
    try:
        with _connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE workforce_app_users
                    SET role = %s, role_assigned_by = %s,
                        role_assigned_at = NOW()
                    WHERE open_id = %s
                    """,
                    (role, reviewer["open_id"], target_open_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("The selected user has not signed in yet.")
    except ValueError:
        raise
    except Exception as error:
        raise LarkAPIError(
            f"Could not change the user role: {type(error).__name__}.", status=503,
        ) from error
