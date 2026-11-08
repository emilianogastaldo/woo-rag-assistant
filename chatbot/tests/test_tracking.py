"""Synthetic metadata only: no selected courier/plugin and no network requests."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.config import Settings, settings
from app.tools.orders import ORDER_NOT_FOUND, OrderService, format_order
from app.tools.tracking import read_tracking, safe_tracking_url
from tests.conftest import FakeWooClient, make_order


@pytest.fixture
def configured_tracking(monkeypatch):
    monkeypatch.setattr(settings, "tracking_delivery_date_meta_key", "_fixture_delivered")
    monkeypatch.setattr(settings, "tracking_status_meta_key", "_fixture_state")
    monkeypatch.setattr(settings, "tracking_url_meta_key", "_fixture_url")
    monkeypatch.setattr(settings, "tracking_status_map", {
        "label": "created", "collected": "accepted", "moving": "in_transit",
        "confirmed": "delivered", "incident": "exception",
    })
    monkeypatch.setattr(settings, "order_return_window_days", 14)
    monkeypatch.setattr(settings, "wc_order_timezone", "Europe/Rome")


def tracking_order(*, state=None, delivered=None, url=None, **overrides):
    metadata = [{"key": key, "value": value} for key, value in (
        ("_fixture_state", state), ("_fixture_delivered", delivered), ("_fixture_url", url),
    ) if value is not None]
    return make_order(22, overrides.pop("customer_id", 12), meta_data=metadata, **overrides)


@pytest.mark.parametrize(("state", "label"), [
    ("label", "spedizione creata"), ("collected", "presa in carico"),
    ("moving", "in transito"), ("incident", "anomalia segnalata dal tracking"),
])
def test_shipment_stage_is_mapped_explicitly_and_separate_from_order_status(
    configured_tracking, state, label,
):
    result = format_order(tracking_order(state=state, status="completed"))
    assert "Stato: completato" in result
    assert f"Stato spedizione: {label}" in result
    assert "Data consegna verificata: non disponibile" in result
    assert "Scadenza reso: non calcolabile" in result


def test_verified_metadata_date_link_and_configured_policy(configured_tracking):
    order = tracking_order(state="confirmed", delivered="2026-06-22T14:30:00Z",
                           url="https://tracking.example/parcel?id=SYNTHETIC")
    original = deepcopy(order)
    result = format_order(order)
    assert "Stato spedizione: consegnata" in result
    assert "Data consegna verificata: 22/06/2026" in result
    assert "Scadenza reso (14 giorni dalla consegna verificata): 06/07/2026" in result
    assert "Link tracking: https://tracking.example/parcel?id=SYNTHETIC" in result
    assert order == original


def test_completed_without_tracking_is_not_verified_delivery_or_anomaly(configured_tracking):
    result = format_order(make_order(22, 12, status="completed", date_completed="2026-06-22"))
    assert "Stato: completato" in result
    assert "Stato spedizione: non disponibile" in result
    assert "Data consegna verificata: non disponibile" in result
    assert "Scadenza reso: non calcolabile" in result
    assert "anomalia" not in result and "Link tracking" not in result


def test_delivered_status_without_date_does_not_invent_date_or_return_deadline(configured_tracking):
    result = format_order(tracking_order(state="confirmed"))
    assert "Stato spedizione: consegnata" in result
    assert "Tracking incompleto" in result
    assert "Data consegna verificata: non disponibile" in result
    assert "Scadenza reso: non calcolabile" in result


def test_unknown_status_is_not_interpreted_or_echoed_as_an_anomaly(configured_tracking):
    result = format_order(tracking_order(state="completed-dangerous-delay"))
    assert "Stato spedizione: non disponibile" in result
    assert "Tracking incompleto" in result
    assert "completed-dangerous-delay" not in result and "anomalia" not in result


def test_link_alone_does_not_prove_delivery_or_anomaly(configured_tracking):
    result = format_order(tracking_order(url="https://tracking.example/parcel"))
    assert "Link tracking:" in result and "Tracking incompleto" in result
    assert "Stato spedizione: non disponibile" in result
    assert "consegnata" not in result and "anomalia" not in result


@pytest.mark.parametrize("state", ["moving", "incident", "unknown"])
def test_conflicting_status_suppresses_stale_delivery_date(configured_tracking, state):
    result = format_order(tracking_order(state=state, delivered="2026-06-22T14:30:00Z"))
    assert "Data consegna verificata: non disponibile" in result
    assert "Tracking incompleto" in result
    assert "06/07/2026" not in result


@pytest.mark.parametrize("value", [None, "not-an-ISO-date", 123, {}, ["2026-06-22"]])
def test_malformed_delivery_date_does_not_invent_a_deadline(configured_tracking, value):
    result = format_order(tracking_order(delivered=value))
    assert "Data consegna verificata: non disponibile" in result
    assert "Scadenza reso: non calcolabile" in result


def test_duplicate_metadata_does_not_choose_a_convenient_state(configured_tracking):
    order = tracking_order(delivered="2026-06-22T14:30:00Z", state="confirmed")
    order["meta_data"].append({"key": "_fixture_state", "value": "moving"})
    info = read_tracking(order)
    assert info.incomplete and info.delivered_at is None and info.state is None


def test_unconfigured_vendor_metadata_is_ignored(configured_tracking):
    order = make_order(22, 12, meta_data=[{"key": "_unknown_plugin", "value": {
        "status": "delivered", "tracking_url": "https://tracking.example/parcel",
    }}])
    info = read_tracking(order)
    assert info.state is None and info.url is None and info.delivered_at is None


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "data:text/html,test", "//tracking.example/parcel",
    "http://tracking.example/parcel", "https://user:password@tracking.example/parcel",
    "https://tracking.example:invalid/parcel", "https://tracking.example:8443/parcel",
    "https://tracking.example/\nInjected", "https://tracking.example\\@evil.example/",
    "https://localhost/", "https://127.0.0.1/", "https://10.0.0.1/",
    "https://[::1]/", "https://tracking.local/", "https://%65vil.example/",
    "https://.example/", "https:///parcel", "https://tracking.example/<script>",
])
def test_dangerous_or_invalid_tracking_link_is_never_exposed(configured_tracking, url):
    assert safe_tracking_url(url) is None
    result = format_order(tracking_order(state="moving", url=url))
    assert "Link tracking:" not in result and url not in result
    assert "Tracking incompleto" in result


def test_return_calculation_can_be_disabled_even_with_verified_delivery(
    configured_tracking, monkeypatch,
):
    monkeypatch.setattr(settings, "order_return_window_days", 0)
    result = format_order(tracking_order(delivered="2026-06-22T14:30:00Z"))
    assert "Data consegna verificata: 22/06/2026" in result
    assert "Scadenza reso: calcolo disabilitato" in result
    assert "06/07/2026" not in result and "22/07/2026" not in result


def test_delivery_calendar_uses_configured_shop_timezone(configured_tracking):
    result = format_order(tracking_order(delivered="2026-06-22T23:30:00Z"))
    assert "Data consegna verificata: 23/06/2026" in result
    assert "Scadenza reso (14 giorni dalla consegna verificata): 07/07/2026" in result


def test_delivery_date_source_can_be_disabled(configured_tracking, monkeypatch):
    monkeypatch.setattr(settings, "tracking_delivery_date_meta_key", "")
    info = read_tracking(tracking_order(delivered="2026-06-22T14:30:00Z"))
    assert info.delivered_at is None


@pytest.mark.parametrize("arguments", [
    {"order_return_window_days": -1}, {"order_return_window_days": 3651},
    {"tracking_status_map": {"some-code": "invented-shipping-stage"}},
])
def test_invalid_tracking_or_policy_configuration_is_rejected(arguments):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **arguments)


def test_tracking_environment_mapping_and_policy_opt_out(monkeypatch):
    monkeypatch.setenv("TRACKING_STATUS_META_KEY", "_fixture_state")
    monkeypatch.setenv("TRACKING_STATUS_MAP", '{"confirmed":"delivered"}')
    monkeypatch.setenv("TRACKING_DELIVERY_DATE_META_KEY", "")
    monkeypatch.setenv("ORDER_RETURN_WINDOW_DAYS", "0")
    config = Settings(_env_file=None)
    assert config.tracking_status_meta_key == "_fixture_state"
    assert config.tracking_status_map == {"confirmed": "delivered"}
    assert config.tracking_delivery_date_meta_key == "" and config.order_return_window_days == 0


async def test_tracking_is_still_customer_scoped(configured_tracking):
    foreign = tracking_order(state="confirmed", delivered="2026-06-22T14:30:00Z",
                             url="https://tracking.example/PRIVATE", customer_id=13)
    woo = FakeWooClient({"orders": [foreign]})
    service = OrderService(12, woo)
    assert await service.get_order(22) == ORDER_NOT_FOUND
    assert await service.get_order("22") == ORDER_NOT_FOUND
    assert "PRIVATE" not in await service.list_orders()
    assert all(params["customer"] == 12 for _, params in woo.calls)
