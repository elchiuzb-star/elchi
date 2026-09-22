"""Wave 6 / §17.6: "refresh revoke qilingan sessiya real-time kanalda ham yopiladi".

Before this wave an access token stayed usable for its full hour after a logout, on REST **and** on the tracking
WebSocket - the revocation only stopped the refresh. Now the access token carries the login session id (``sid``)
and both the v2 surface and the WebSocket refuse a token whose session is gone.

Deliberately unchanged: **v1**. Making a v1 access token stop working at logout is a v1 behaviour change and
needs its own decision (AGENTS §2), so v1 keeps answering until the token expires - this test pins that too, so
the difference is a recorded choice and not an accident.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.security import create_access_token, verify_token
from app.services import auth_service
from tests.pg.bookings.conftest import (  # noqa: F401  (shared A4 fixtures)
    BW,
    auth,
    bw,
    rows,
    scalar,
)
from tests.pg.identity.a1_world import world  # noqa: F401  (shared A1 fixture)

pytestmark = pytest.mark.pg


def _login(bw: BW, user_id: int) -> tuple[str, str]:  # noqa: F811
    """A real login through the v1 flow: access token + the session id it is bound to."""
    from app.models import User

    with bw.db.session() as session:
        user = session.get(User, user_id)
        payload = auth_service.build_token_response(session, user)
        session.commit()
    token = payload["data"]["access_token"]
    claims = verify_token(token)
    assert claims is not None
    return token, claims["sid"]


def test_access_token_is_bound_to_its_login_session(bw: BW) -> None:  # noqa: F811
    token, sid = _login(bw, bw.w.client_id)
    assert sid, "the access token must name the session it belongs to (§17.6)"
    with bw.db.session() as session:
        assert auth_service.session_revoked(session, verify_token(token)) is False


def test_revoked_session_is_refused_at_once(bw: BW) -> None:  # noqa: F811
    token, sid = _login(bw, bw.w.client_id)
    with bw.db.session() as session:
        session.execute(text("UPDATE refresh_sessions SET is_revoked = true WHERE jti = :jti"), {"jti": sid})
        session.commit()
    with bw.db.session() as session:
        assert auth_service.session_revoked(session, verify_token(token)) is True


def test_expired_or_unknown_session_counts_as_revoked(bw: BW) -> None:  # noqa: F811
    token, sid = _login(bw, bw.w.client_id)
    with bw.db.session() as session:
        session.execute(text("DELETE FROM refresh_sessions WHERE jti = :jti"), {"jti": sid})
        session.commit()
    with bw.db.session() as session:
        assert auth_service.session_revoked(session, verify_token(token)) is True


def test_token_without_the_claim_keeps_working(bw: BW) -> None:  # noqa: F811
    """A token issued before this release has no ``sid``; it is not treated as revoked, it just expires."""
    legacy = create_access_token(str(bw.w.client_id), extra_claims={"role": "client"})
    with bw.db.session() as session:
        assert auth_service.session_revoked(session, verify_token(legacy)) is False


def test_websocket_authentication_stops_at_a_revoked_session(bw: BW) -> None:  # noqa: F811
    """The WS re-authenticates on every push, so a logout closes the live channel within one interval."""
    from app.modules.tracking.ws import _authenticated_user_id

    token, sid = _login(bw, bw.w.client_id)
    with bw.db.session() as session:
        assert _authenticated_user_id(session, token) == bw.w.client_id
    with bw.db.session() as session:
        session.execute(text("UPDATE refresh_sessions SET is_revoked = true WHERE jti = :jti"), {"jti": sid})
        session.commit()
    with bw.db.session() as session:
        assert _authenticated_user_id(session, token) is None
