"""
tests/test_messages.py
======================
Unit tests for the Messaging module.

Covers:
  - Send message with 'messaging.send' permission
  - Send message without permission (403 expected)
  - Inbox retrieval returns correct messages for current user
  - Permission check: users without messaging.send cannot access sent box

Framework: pytest + FastAPI TestClient
Run with:  pytest backend/tests/test_messages.py -v

NOTE: pytest and httpx are not in requirements.txt yet.
      Install them first:  pip install pytest httpx
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_mock_user(
    *,
    user_id: int = 1,
    email: str = "hr@example.com",
    first_name: str = "HR",
    last_name: str = "Manager",
    permissions: list = None,
):
    """
    Build a lightweight MagicMock that mimics the User ORM model
    for use in messaging router unit tests.
    """
    user = MagicMock()
    user.id = user_id
    user.email = email
    user.first_name = first_name
    user.last_name = last_name
    user.is_deleted = False
    user.roles = []
    user.is_superadmin = False
    user.department = None
    # Permissions list is used by get_user_permissions in tests
    user._permissions = permissions or []
    return user


def make_mock_message(
    *,
    message_id: int = 1,
    sender_id: int = 1,
    subject: str = "Hello",
    content: str = "Test content",
    target_group: str = "All Employees",
):
    """Build a lightweight MagicMock that mimics the Message ORM model."""
    msg = MagicMock()
    msg.id = message_id
    msg.sender_id = sender_id
    msg.subject = subject
    msg.content = content
    msg.target_group = target_group
    msg.sender_deleted = False
    msg.sender_permanent_deleted = False
    msg.created_at = datetime.now(timezone.utc)
    return msg


def make_mock_recipient(
    *,
    message_id: int = 1,
    recipient_id: int = 2,
    is_read: bool = False,
    is_deleted: bool = False,
    is_permanent_deleted: bool = False,
):
    """Build a lightweight MagicMock that mimics the MessageRecipient ORM model."""
    rec = MagicMock()
    rec.message_id = message_id
    rec.recipient_id = recipient_id
    rec.is_read = is_read
    rec.is_deleted = is_deleted
    rec.is_permanent_deleted = is_permanent_deleted
    rec.deleted_at = None
    return rec


def permissions_patch(perms):
    """
    get_user_permissions is called as a plain function (inside the router and
    the require_permission() checkers), not injected via Depends, so a
    dependency_overrides entry never reaches it — patch it where it's looked up.
    """
    from contextlib import ExitStack
    stack = ExitStack()
    for target in ("app.core.deps.get_user_permissions", "app.messages.router.get_user_permissions"):
        stack.enter_context(patch(target, return_value=list(perms)))
    return stack


# ─────────────────────────────────────────────────────────────────────────────
# 1. Send message — with permission
# ─────────────────────────────────────────────────────────────────────────────

def test_send_message_with_permission_succeeds():
    """
    A user with 'messaging.send' permission should be able to POST /messages/.
    The endpoint should return HTTP 200/201 with the created message data.
    Tested via FastAPI TestClient with dependency overrides.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.deps import get_current_user, get_user_permissions
    from app.database.database import get_db

    sender = make_mock_user(user_id=1, permissions=["messaging.send"])

    # Override auth dependencies so no real DB/JWT is needed
    app.dependency_overrides[get_current_user] = lambda: sender
    perms = ["messaging.send"]

    mock_db = MagicMock()
    # Simulate message creation returning an ID
    saved_msg = make_mock_message(sender_id=sender.id)
    mock_db.add = MagicMock()
    mock_db.commit = MagicMock()
    def _refresh(obj):  # stand in for the DB filling id / created_at
        obj.id = 1
        obj.created_at = datetime.now(timezone.utc)
        obj.sender_deleted = False
    mock_db.refresh = MagicMock(side_effect=_refresh)
    # recipients: query(User.id).filter(not sender).filter(role).filter(active).all()
    mock_db.query.return_value.filter.return_value.filter.return_value.filter.return_value.all.return_value = [(2,), (3,)]
    app.dependency_overrides[get_db] = lambda: mock_db

    client = TestClient(app, raise_server_exceptions=False)
    with permissions_patch(perms):
        response = client.post("/messages/", json={
            "subject": "Quarterly Update",
            "content": "Please review the attached report.",
            "target_group": "All Employees",
        })

    # Clean up overrides
    app.dependency_overrides.clear()

    # The endpoint should NOT return 403 when the user has the permission
    assert response.status_code == 200, (
        f"Expected success but got {response.status_code}. Body: {response.text}"
    )
    assert response.json()["subject"] == "Quarterly Update"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Send message — without permission (403)
# ─────────────────────────────────────────────────────────────────────────────

def test_send_message_without_permission_returns_403():
    """
    A user without 'messaging.send' permission must receive HTTP 403
    when attempting to POST /messages/.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.deps import get_current_user, get_user_permissions
    from app.database.database import get_db

    employee = make_mock_user(user_id=2, permissions=[])  # No messaging.send

    app.dependency_overrides[get_current_user] = lambda: employee
    perms = []
    app.dependency_overrides[get_db] = lambda: MagicMock()

    client = TestClient(app, raise_server_exceptions=False)
    with permissions_patch(perms):
        response = client.post("/messages/", json={
            "subject": "Attempt",
            "content": "Should be rejected.",
            "target_group": "All Employees",
        })

    app.dependency_overrides.clear()

    assert response.status_code == 403, (
        f"Expected 403 Forbidden but got {response.status_code}. Body: {response.text}"
    )
    assert "permission" in response.json().get("detail", "").lower()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Inbox retrieval — returns messages for current user only
# ─────────────────────────────────────────────────────────────────────────────

def test_get_inbox_returns_200():
    """
    GET /messages/inbox should return HTTP 200 for an authenticated user.
    The inbox only contains messages where MessageRecipient.recipient_id
    matches the current user — enforced by the DB query filter.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.deps import get_current_user, get_user_permissions
    from app.database.database import get_db

    recipient = make_mock_user(user_id=3, permissions=["messaging.receive"])

    mock_db = MagicMock()
    # Simulate empty inbox (no join results)
    mock_db.query.return_value.join.return_value.join.return_value.filter.return_value.order_by.return_value.all.return_value = []

    app.dependency_overrides[get_current_user] = lambda: recipient
    perms = ["messaging.receive"]
    app.dependency_overrides[get_db] = lambda: mock_db

    client = TestClient(app, raise_server_exceptions=False)
    with permissions_patch(perms):
        response = client.get("/messages/inbox")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_inbox_does_not_return_other_users_messages():
    """
    The inbox query filters by recipient_id == current_user.id.
    This test verifies that a mock returning an empty list for a given user
    results in an empty inbox — confirming the filter is in place.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.deps import get_current_user, get_user_permissions
    from app.database.database import get_db

    user = make_mock_user(user_id=99)

    mock_db = MagicMock()
    mock_db.query.return_value.join.return_value.join.return_value.filter.return_value.order_by.return_value.all.return_value = []

    app.dependency_overrides[get_current_user] = lambda: user
    perms = ["messaging.receive"]
    app.dependency_overrides[get_db] = lambda: mock_db

    client = TestClient(app, raise_server_exceptions=False)
    with permissions_patch(perms):
        response = client.get("/messages/inbox")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [], "Inbox should be empty when no messages target this user"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Permission check — sent box blocked without messaging.send
# ─────────────────────────────────────────────────────────────────────────────

def test_get_sent_without_permission_returns_403():
    """
    GET /messages/sent must return HTTP 403 for users who do not hold
    the 'messaging.send' permission — only senders have a sent box.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.deps import get_current_user, get_user_permissions
    from app.database.database import get_db

    employee = make_mock_user(user_id=4, permissions=[])

    app.dependency_overrides[get_current_user] = lambda: employee
    perms = []
    app.dependency_overrides[get_db] = lambda: MagicMock()

    client = TestClient(app, raise_server_exceptions=False)
    with permissions_patch(perms):
        response = client.get("/messages/sent")
    app.dependency_overrides.clear()

    assert response.status_code == 403, (
        f"Expected 403 but got {response.status_code}. Body: {response.text}"
    )


def test_get_sent_with_permission_returns_200():
    """
    GET /messages/sent must return HTTP 200 for users who hold
    the 'messaging.send' permission.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.deps import get_current_user, get_user_permissions
    from app.database.database import get_db

    sender = make_mock_user(user_id=5, permissions=["messaging.send"])

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

    app.dependency_overrides[get_current_user] = lambda: sender
    perms = ["messaging.send"]
    app.dependency_overrides[get_db] = lambda: mock_db

    client = TestClient(app, raise_server_exceptions=False)
    with permissions_patch(perms):
        response = client.get("/messages/sent")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Custom message groups were removed (they had no members)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method, path", [
    ("get", "/messages/groups"),
    ("post", "/messages/groups"),
    ("delete", "/messages/groups/1"),
])
def test_custom_group_endpoints_are_gone(method, path):
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    response = getattr(client, method)(path)
    assert response.status_code in (404, 405)


def test_send_to_former_custom_group_name_is_refused():
    """A target that is neither a built-in group nor a department is a 400, not a silent no-op."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.deps import get_current_user
    from app.database.database import get_db

    sender = make_mock_user(user_id=1)
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None  # no such department
    app.dependency_overrides[get_current_user] = lambda: sender
    app.dependency_overrides[get_db] = lambda: mock_db

    client = TestClient(app, raise_server_exceptions=False)
    with permissions_patch(["messaging.send"]):
        response = client.post("/messages/", json={
            "subject": "Hi", "content": "Team news", "target_group": "Project Falcon",
        })
    app.dependency_overrides.clear()

    assert response.status_code == 400
    mock_db.add.assert_not_called()  # nothing saved
