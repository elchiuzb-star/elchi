# AC01–AC44 qamrov matritsasi (spec §22)

**Avtomatik yaratilgan:** `py scripts/ac_coverage.py --junit <junit.xml> --format md` • **Sana:** 17.09.2026 (wave 7)
**Manba:** `ELCHI_TEST_PG_REQUIRED=1 py -m pytest -q --junitxml=…` — 2022 test, 0 failure, `alembic heads` = `20260917_0071`

**Natija:** 42 PASS · AC32 `FIELD` (Android dala sinovi — bu repo’da tekshirilmaydi) · AC40 `PROCEDURE` (restore mashqi — pytest node emas). “PASS” = shu run’da o‘tgan test bor; dala yoki tashqi tasdiq talab qiladigan bandlar **hech qachon** PASS deb yozilmaydi (AGENTS §7).

| AC | Holat | Testlar | Dalil (birinchi nomlar) | Izoh |
|---|---|---|---|---|
| AC01 | PASS | 2 | `tests/modules/marketplace/test_marketplace_rules.py::test_ac01_two_seats_times_200000_som_is_400000_som`<br>`tests/pg/marketplace/test_marketplace_pg.py::test_ac01_server_total_and_db_check` |  |
| AC02 | PASS | 2 | `tests/pg/bookings/test_accept_pg.py::test_ac02_driver_accepts_client_proposal_on_trip_offer`<br>`tests/pg/marketplace/test_marketplace_wave15_pg.py::test_ac02_client_proposal_on_trip_offer_with_baggage_snapshot` |  |
| AC03 | PASS | 1 | `tests/pg/bookings/test_accept_pg.py::test_ac03_client_accepts_driver_proposal_on_request` |  |
| AC04 | PASS | 2 | `tests/pg/bookings/test_accept_pg.py::test_ac04_stale_version_after_counter_is_rejected_without_booking`<br>`tests/pg/marketplace/test_marketplace_pg.py::test_ac04_counter_supersedes_and_stale_revision_is_rejected` |  |
| AC05 | PASS | 2 | `tests/pg/bookings/test_accept_pg.py::test_ac05_author_cannot_accept_own_version`<br>`tests/pg/marketplace/test_marketplace_pg.py::test_ac05_self_dealing_forbidden` |  |
| AC06 | PASS | 1 | `tests/pg/bookings/test_accept_pg.py::test_ac06_two_drivers_accept_the_same_demand_in_parallel` |  |
| AC07 | PASS | 1 | `tests/pg/bookings/test_accept_pg.py::test_ac07_twenty_parallel_accepts_for_the_last_seat` |  |
| AC08 | PASS | 3 | `tests/pg/bookings/test_accept_pg.py::test_ac08_ac09_http_replay_and_key_reuse`<br>`tests/pg/bookings/test_accept_pg.py::test_ac08_same_key_five_times_in_parallel_one_booking_one_hold_same_response`<br>… +1 |  |
| AC09 | PASS | 2 | `tests/pg/bookings/test_accept_pg.py::test_ac08_ac09_http_replay_and_key_reuse`<br>`tests/pg/platform/test_idempotency_outbox.py::test_ac09_same_key_different_body_is_409_and_not_executed` |  |
| AC10 | PASS | 4 | `tests/modules/trips/test_trip_rules.py::test_ac10_spec_example_remaining_per_segment`<br>`tests/modules/trips/test_trip_rules.py::test_ac10_two_seats_a_to_d_rejected_on_b_c`<br>… +2 |  |
| AC11 | PASS | 3 | `tests/modules/trips/test_trip_rules.py::test_ac11_three_seats_c_to_d_allowed`<br>`tests/pg/bookings/test_accept_pg.py::test_ac10_ac11_segment_capacity_through_accept`<br>… +1 |  |
| AC12 | PASS | 3 | `tests/modules/trips/test_trip_rules.py::test_ac12_baggage_over_capacity_is_cargo_limit`<br>`tests/pg/bookings/test_accept_pg.py::test_ac12_baggage_over_capacity_is_cargo_limit_exceeded`<br>… +1 |  |
| AC13 | PASS | 2 | `tests/pg/trips/test_trips_capacity_pg.py::test_ac13_driver_and_vehicle_overlap_rejected_by_constraint`<br>`tests/pg/trips/test_trips_capacity_pg.py::test_ac13_parallel_overlapping_trips_only_one_is_created` |  |
| AC14 | PASS | 2 | `tests/modules/geo/test_geo_matching.py::test_ac14_stop_not_on_route_is_not_matched`<br>`tests/pg/geo/test_geo_catalog_matching_pg.py::test_ac14_chiroqchi_not_on_fixture_route_gives_no_on_route` |  |
| AC15 | PASS | 1 | `tests/modules/geo/test_geo_matching.py::test_ac15_pickup_eta_uses_intermediate_stop_not_origin_departure` |  |
| AC16 | PASS | 4 | `tests/modules/geo/test_geo_matching.py::test_ac16_reverse_direction_is_rejected`<br>`tests/pg/geo/test_geo_catalog_matching_pg.py::test_ac16_reverse_direction_rejected_even_though_spatially_near`<br>… +2 |  |
| AC17 | PASS | 2 | `tests/modules/bookings/test_booking_contract_alignment.py::test_ac17_cumulative_detour_budget_in_seconds`<br>`tests/modules/geo/test_geo_matching.py::test_ac17_each_pickup_10_min_but_total_40_exceeds_30_limit` |  |
| AC18 | PASS | 1 | `tests/pg/marketplace/feed/test_feed_pg.py::test_ac18_offline_driver_with_future_trip_stays_in_feed_on_route_only` |  |
| AC19 | PASS | 3 | `tests/pg/bookings/test_accept_pg.py::test_ac19_insufficient_commission_balance_rolls_back_everything`<br>`tests/pg/wallet/test_wallet_money.py::test_ac19_hold_reduces_available_and_second_hold_rejected`<br>… +1 |  |
| AC20 | PASS | 4 | `tests/pg/bookings/test_booking_races_pg.py::test_ac20_parallel_completion_captures_once`<br>`tests/pg/wallet/test_wallet_money.py::test_ac20_parallel_capture_debits_once`<br>… +2 |  |
| AC21 | PASS | 1 | `tests/pg/bookings/test_lifecycle_pg.py::test_ac21_client_cancel_releases_allocation_and_hold_atomically` |  |
| AC22 | PASS | 3 | `tests/contracts/test_state_machines.py::test_parcel_in_custody_cannot_be_cancelled_ac22`<br>`tests/modules/bookings/test_booking_rules.py::test_ac22_parcel_in_custody_cannot_be_cancelled`<br>… +1 |  |
| AC23 | PASS | 2 | `tests/pg/wallet/test_wallet_money.py::test_ac23_parallel_approve_same_topup_credits_once`<br>`tests/pg/wallet/test_wallet_money.py::test_ac23_same_source_reference_on_two_topups_credits_once` |  |
| AC24 | PASS | 2 | `tests/pg/wallet/test_wallet_money.py::test_ac24_pending_topup_does_not_change_balance`<br>`tests/pg/wallet/test_wallet_api.py::test_driver_topup_flow_and_idempotent_replay` |  |
| AC25 | PASS | 3 | `tests/pg/wallet/test_wallet_money.py::test_ac25_d4_partial_reversals_create_new_entries_and_cap_at_captured`<br>`tests/pg/wallet/test_wallet_money.py::test_ac25_ledger_is_immutable_and_cache_cannot_drift`<br>… +1 |  |
| AC26 | PASS | 3 | `tests/pg/bookings/test_lifecycle_pg.py::test_ac26_contested_cash_keeps_service_status`<br>`tests/pg/bookings/test_wave21_pg.py::test_ac26_http_cash_report_and_acknowledge`<br>… +1 |  |
| AC27 | PASS | 2 | `tests/pg/tracking/test_tracking_sessions_pg.py::test_ac27_gap_turns_lost_then_new_batch_is_fresh_in_order`<br>`tests/contracts/test_tracking_crypto_policy.py::test_freshness_rejects_negative_age_and_uses_aware_times` | backend part here; force-stop/battery-saver field part is the Android developer's |
| AC28 | PASS | 2 | `tests/modules/tracking/test_tracking_rules.py::test_ac28_older_point_is_history_only`<br>`tests/pg/tracking/test_tracking_sessions_pg.py::test_ac28_old_and_mock_points_never_move_the_marker` |  |
| AC29 | PASS | 1 | `tests/pg/tracking/test_tracking_sessions_pg.py::test_ac29_new_session_supersedes_and_old_writer_gets_409` |  |
| AC30 | PASS | 1 | `tests/pg/tracking/test_tracking_access_pg.py::test_ac30_other_users_get_404_and_participant_dto_has_no_contacts` |  |
| AC31 | PASS | 1 | `tests/pg/tracking/test_tracking_access_pg.py::test_ac31_finished_booking_closes_rest_and_websocket` |  |
| AC32 | FIELD | 0 | — | Android field evidence (AC32) - out of stage-2 backend scope |
| AC33 | PASS | 2 | `tests/pg/communications/test_dispatch_pg.py::test_ac33_dispatcher_crash_before_commit_then_single_delivery`<br>`tests/pg/platform/test_idempotency_outbox.py::test_ac33_outbox_event_disappears_on_rollback_and_persists_on_commit` |  |
| AC34 | PASS | 28 | `tests/pg/communications/test_push_pg.py::test_disabled_provider_creates_no_push_rows_and_task_is_noop`<br>`tests/pg/communications/test_push_pg.py::test_duplicate_pushes_collapse_inside_the_dedup_window`<br>… +26 |  |
| AC35 | PASS | 2 | `tests/modules/geo/test_geo_matching.py::test_ac35_router_outage_gives_degraded_result_not_a_match`<br>`tests/pg/geo/test_geo_catalog_matching_pg.py::test_ac35_router_outage_writes_nothing_generic_error_and_cache_is_reused` |  |
| AC36 | PASS | 4 | `tests/contracts/test_wave3_additions.py::test_reputation_never_fakes_a_rating_ac36`<br>`tests/modules/marketplace/feed/test_feed_rules.py::test_ac36_adjusted_rating_one_five_star_is_not_first`<br>… +2 |  |
| AC37 | PASS | 2 | `tests/pg/ops/test_legacy_projection.py::test_ac37_rebuilding_the_projection_twice_duplicates_nothing_and_writes_nothing`<br>`tests/pg/ops/test_legacy_timestamps.py::test_projection_views_and_their_read_only_triggers_survive_the_conversion` |  |
| AC38 | PASS | 2 | `tests/pg/tracking/test_tracking_sessions_pg.py::test_ac38_flag_off_refuses_only_trips_without_a_session`<br>`tests/pg/geo/test_geo_flags_pg.py::test_flag_writes_touch_only_flag_tables_and_audit` |  |
| AC39 | PASS | 3 | `tests/test_v1_v2_isolation_ac39.py::test_ac39_v1_code_never_imports_a_v2_model_or_repository`<br>`tests/test_v1_v2_isolation_ac39.py::test_ac39_v1_code_never_queries_a_v2_table`<br>… +1 |  |
| AC40 | PROCEDURE | 0 | — | restore drill (scripts/restore_drill.sh) - DRILL evidence, not a pytest node |
| AC41 | PASS | 6 | `tests/pg/bookings/test_accept_pg.py::test_ac41_accept_before_block_is_a_legal_booking`<br>`tests/pg/bookings/test_accept_pg.py::test_ac41_block_before_accept_denies_after_accept_keeps_booking`<br>… +4 |  |
| AC42 | PASS | 2 | `tests/contracts/test_state_machines.py::test_trip_completion_guard_ac42_d1`<br>`tests/pg/bookings/test_lifecycle_pg.py::test_parcel_custody_trip_completion_return_and_fee_finalization` |  |
| AC43 | PASS | 3 | `tests/pg/bookings/test_accept_pg.py::test_ac43_frozen_fee_quote_and_d3_exempt_campaign`<br>`tests/pg/marketplace/test_marketplace_pg.py::test_ac43_fee_quote_frozen_per_version`<br>… +1 |  |
| AC44 | PASS | 2 | `tests/contracts/test_wave3_additions.py::test_passenger_window_opens_30_min_before_pickup_ac44`<br>`tests/pg/tracking/test_tracking_access_pg.py::test_ac44_two_days_before_is_403_with_opens_at` |  |
