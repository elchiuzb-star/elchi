"""Compatibility shim (integration pass 2): the shared v2 HTTP plumbing moved to ``app.api.v2.web``.

Every name is re-exported unchanged so A1 routers and tests keep importing from here.
New code should import from ``app.api.v2.web``.
"""

from app.api.v2.web import (  # noqa: F401
    ERROR_RESPONSES,
    T,
    _cursor_secret,
    _optional_bearer,
    _route_template,
    current_user_id,
    decode_id_cursor,
    decode_time_id_cursor,
    domain_error_handler,
    encode_page_cursor,
    envelope_body,
    get_session,
    optional_user_id,
    page_scope,
    run_command,
    run_versioned,
)
