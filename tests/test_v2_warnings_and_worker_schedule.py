"""Wave 1.6 integration: Envelope.warnings mapping (Q43) and interim worker scheduling (no DB)."""

from __future__ import annotations

from app.api.v2.web import envelope_body, split_handler_result, to_api_warnings
from app.contracts.contact_filter import CONTACT_FILTER_VERSION, scan
from app.contracts.dto import ApiWarning, ContractModel, Envelope
from app.contracts.errors import WARNING_CATALOGUE, WarningCode


class _DTO(ContractModel):
    id: str


def _marketplace_warning() -> dict:
    return {"code": WarningCode.CONTACT_INFO_MASKED.value, "field": "comment", **scan("90 123 45 67").warning_details()}


def test_marketplace_warning_dict_maps_to_api_warning() -> None:
    (warning,) = to_api_warnings([_marketplace_warning()])
    assert warning == ApiWarning(
        code="CONTACT_INFO_MASKED",
        message=WARNING_CATALOGUE[WarningCode.CONTACT_INFO_MASKED],
        field="comment",
        details={"categories": ["phone"], "match_count": 1, "filter_version": CONTACT_FILTER_VERSION},
    )


def test_api_warning_passthrough_and_unknown_code_message() -> None:
    ready = ApiWarning(code="X", message="m")
    assert to_api_warnings([ready]) == [ready]
    (unknown,) = to_api_warnings([{"code": "SOMETHING_NEW"}])
    assert unknown.message == "SOMETHING_NEW" and unknown.details is None and unknown.field is None
    assert to_api_warnings(None) == [] and to_api_warnings([]) == []


def test_handler_results_plain_or_with_warnings() -> None:
    dto = _DTO(id="x")
    assert split_handler_result(dto) == (dto, [])
    same, warnings = split_handler_result((dto, [_marketplace_warning()]))
    assert same is dto and warnings[0].code == "CONTACT_INFO_MASKED"


def test_envelope_body_adds_warnings_only_when_present() -> None:
    dto = _DTO(id="x")
    assert "warnings" not in envelope_body(dto)
    assert "warnings" not in envelope_body(dto, warnings=[])
    body = envelope_body(dto, warnings=to_api_warnings([_marketplace_warning()]))
    assert body["warnings"][0]["details"]["categories"] == ["phone"]
    assert Envelope[_DTO].model_validate(body).warnings[0].field == "comment"


def test_marketplace_dtos_no_longer_carry_warnings_field() -> None:
    from app.modules.marketplace import schemas

    assert "warnings" not in schemas.ListingDTO.model_fields
    assert "warnings" not in schemas.ProposalThreadDTO.model_fields
    assert not hasattr(schemas, "TextWarningDTO")


# --- worker scheduling ---------------------------------------------------------------------------


def test_every_runs_first_call_then_once_per_interval() -> None:
    from app.worker import every

    now = [1000.0]
    calls: list[float] = []
    task = every(3600, lambda: calls.append(now[0]), clock=lambda: now[0])
    task()
    now[0] += 5
    task()
    now[0] += 3600
    task()
    assert calls == [1000.0, 4605.0]


def test_register_default_tasks_is_idempotent_and_hourly() -> None:
    from app.modules.geo.jobs import routing_cache_cleanup_task
    from app.worker import ROUTING_CACHE_CLEANUP_INTERVAL_SECONDS, TASKS, register_default_tasks

    before = list(TASKS)
    tasks: list = []
    register_default_tasks(tasks)
    first_count = len(tasks)
    register_default_tasks(tasks)
    # Wave 2.1: A10a registers more jobs (expiry, signals, geo scan); only idempotency and the hourly routing
    # cleanup are pinned here, not the number of other jobs.
    assert len(tasks) == first_count >= 1
    routing = [task for task in tasks if getattr(task, "wrapped_task", None) is routing_cache_cleanup_task]
    assert len(routing) == 1
    assert ROUTING_CACHE_CLEANUP_INTERVAL_SECONDS == 3600
    assert TASKS == before  # explicit list: the global registry is untouched
