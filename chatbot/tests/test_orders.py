"""Tool ordini: scoping sul cliente della sessione.

Copre gli scenari obbligatori 3 e 4 di CLAUDE.md: il cliente vede il proprio
ordine, e l'ordine di un altro cliente risulta "non trovato".
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent import ElencoOrdini, StatoOrdine, build_toolset
from app.auth.session import Session
from app.config import Settings, settings
from app.resilience import FailureKind, RecoverableFailure
from app.tools.orders import ORDER_NOT_FOUND, SEARCH_LIMIT, OrderService
from tests.conftest import FakeWooClient, make_order

CUSTOMER_A = 12
CUSTOMER_B = 13


async def test_ordine_proprio_viene_restituito():
    woo = FakeWooClient({"orders": [make_order(22, CUSTOMER_A)]})
    result = await OrderService(CUSTOMER_A, client=woo).get_order(22)
    assert "Ordine #22" in result
    assert "in lavorazione" in result
    assert "Zaino Urban" in result


async def test_query_sempre_filtrata_per_customer():
    """Il filtro di autorizzazione sta nella query, non nel prompt."""
    woo = FakeWooClient({"orders": [make_order(22, CUSTOMER_A)]})
    await OrderService(CUSTOMER_A, client=woo).get_order(22)
    params = woo.params_for("orders")
    assert params["customer"] == CUSTOMER_A
    assert params["include"] == 22


async def test_ordine_di_altro_cliente_risulta_non_trovato():
    """Anche se l'API restituisse l'ordine altrui, il codice lo scarta."""
    woo = FakeWooClient({"orders": [make_order(23, CUSTOMER_B)]})
    result = await OrderService(CUSTOMER_A, client=woo).get_order(23)
    assert result == ORDER_NOT_FOUND
    assert "non autorizzat" not in result.lower()


async def test_ordine_inesistente_risulta_non_trovato():
    woo = FakeWooClient({"orders": []})
    assert await OrderService(CUSTOMER_A, client=woo).get_order(999) == ORDER_NOT_FOUND


async def test_numero_ordine_non_numerico_non_arriva_alle_api():
    woo = FakeWooClient({"orders": []})
    assert await OrderService(CUSTOMER_A, client=woo).get_order("../admin") == ORDER_NOT_FOUND
    assert woo.calls == []


async def test_elenco_ordini_scarta_ordini_non_del_cliente():
    woo = FakeWooClient(
        {"orders": [make_order(22, CUSTOMER_A), make_order(23, CUSTOMER_B)]}
    )
    result = await OrderService(CUSTOMER_A, client=woo).list_orders()
    assert "Ordine #22" in result
    assert "Ordine #23" not in result


async def test_reso_calcolato_solo_da_data_consegna_verificata():
    """I 30 giorni decorrono dal metadata di tracking, non dal completamento."""
    woo = FakeWooClient(
        {
            "orders": [
                make_order(
                    21,
                    CUSTOMER_A,
                    status="completed",
                    date_completed="2026-06-20T10:15:00",
                    meta_data=[{"key": "_wrag_delivery_date", "value": "2026-06-22T14:30:00Z"}],
                )
            ]
        }
    )
    result = await OrderService(CUSTOMER_A, client=woo).get_order(21)
    assert "Data completamento: 20/06/2026" in result
    assert "Data consegna verificata: 22/06/2026" in result
    assert "Scadenza reso (30 giorni dalla consegna verificata): 22/07/2026" in result


async def test_sola_data_completamento_non_prova_la_consegna_ne_calcola_il_reso():
    woo = FakeWooClient(
        {
            "orders": [
                make_order(
                    21,
                    CUSTOMER_A,
                    status="completed",
                    date_completed="2026-06-20T10:15:00",
                )
            ]
        }
    )

    result = await OrderService(CUSTOMER_A, client=woo).get_order(21)

    assert "Data completamento: 20/06/2026" in result
    assert "Data consegna verificata: non disponibile" in result
    assert "Scadenza reso: non calcolabile" in result
    assert "20/07/2026" not in result


async def test_public_number_is_exact_and_distinct_from_legacy_internal_id():
    rows = [make_order(22, CUSTOMER_A, number="INV-2026-22"),
            make_order(44, CUSTOMER_A, number="22"), make_order(45, CUSTOMER_A, number="220")]
    woo = FakeWooClient({"orders": rows})
    service = OrderService(CUSTOMER_A, woo)
    assert "Ordine #INV-2026-22" in await service.get_order(22)
    assert "Ordine #22\n" in await service.get_order("22")
    assert "Ordine #INV-2026-22" in await service.get_order("INV-2026-22")
    assert woo.calls[0][1]["include"] == 22
    assert "include" not in woo.calls[1][1]
    assert all(params["customer"] == CUSTOMER_A for _, params in woo.calls)


async def test_public_number_lookup_paginates_with_customer_and_rechecks_ownership():
    first = [make_order(i, CUSTOMER_A, number=f"OTHER-{i}") for i in range(1, 21)]
    second = [make_order(44, CUSTOMER_A, number="WEB-001"),
              make_order(45, CUSTOMER_B, number="WEB-001")]
    woo = FakeWooClient({"orders": lambda p: first if p["page"] == 1 else second})
    result = await OrderService(CUSTOMER_A, woo).get_order("WEB-001")
    assert "Ordine #WEB-001" in result
    assert len(woo.calls) == 2
    assert [p["page"] for _, p in woo.calls] == [1, 2]
    assert all(p["customer"] == CUSTOMER_A and p["per_page"] == 20 for _, p in woo.calls)


async def test_public_number_ambiguity_never_picks_one_order():
    woo = FakeWooClient({"orders": [make_order(22, CUSTOMER_A, number="DUP"),
                                   make_order(23, CUSTOMER_A, number="DUP")]})
    result = await OrderService(CUSTOMER_A, woo).get_order("DUP")
    assert "ambiguo" in result and "Zaino" not in result


async def test_bounded_public_lookup_does_not_claim_unique_match_in_partial_search():
    rows = [make_order(i, CUSTOMER_A, number=f"N-{i}") for i in range(1, 21)]
    woo = FakeWooClient({"orders": rows})
    result = await OrderService(CUSTOMER_A, woo).get_order("N-1")
    assert result == SEARCH_LIMIT
    assert len(woo.calls) == 5 and "Zaino" not in result


async def test_foreign_public_number_and_missing_number_are_indistinguishable():
    woo = FakeWooClient({"orders": [make_order(23, CUSTOMER_B, number="FOREIGN")]})
    service = OrderService(CUSTOMER_A, woo)
    assert await service.get_order("FOREIGN") == await service.get_order("MISSING")
    assert await service.get_order("FOREIGN") == ORDER_NOT_FOUND


@pytest.mark.parametrize("payload", [{}, [None], [make_order(22, "12")],
                                    [make_order(True, CUSTOMER_A)]])
async def test_malformed_order_response_never_reaches_formatter(payload):
    woo = FakeWooClient({"orders": payload})
    for action in (lambda: OrderService(CUSTOMER_A, woo).get_order("22"),
                   lambda: OrderService(CUSTOMER_A, woo).get_order(22),
                   lambda: OrderService(CUSTOMER_A, woo).list_orders()):
        with pytest.raises(RecoverableFailure) as exc:
            await action()
        assert exc.value.kind == FailureKind.MALFORMED_RESPONSE


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "", "../admin", "x\ny"])
async def test_strict_order_reference_rejects_invalid_values_before_query(value):
    woo = FakeWooClient()
    assert await OrderService(CUSTOMER_A, woo).get_order(value) == ORDER_NOT_FOUND
    assert not woo.calls
    with pytest.raises(ValidationError):
        StatoOrdine(numero_ordine=value)


@pytest.mark.parametrize("arguments", [
    {"date_from": "2026-02-29"}, {"date_to": "2026-13-01"},
    {"date_from": "20260329"}, {"date_from": "2026-03-29T00:00:00Z"},
    {"date_from": "2026-04-01", "date_to": "2026-03-29"},
    {"page": 0}, {"page": 51}, {"page": True}, {"page": "2"},
    {"limit": 0}, {"limit": 21}, {"limit": 2.5}, {"customer_id": CUSTOMER_B},
])
def test_order_list_schema_rejects_invalid_dates_limits_or_identity(arguments):
    with pytest.raises(ValidationError):
        ElencoOrdini(**arguments)


async def test_inclusive_calendar_day_uses_explicit_shop_timezone_across_dst(monkeypatch):
    monkeypatch.setattr(settings, "wc_order_timezone", "Europe/Rome")
    rows = [make_order(20, CUSTOMER_A, date_created_gmt="2026-03-28T23:00:00"),
            make_order(21, CUSTOMER_A, date_created_gmt="2026-03-29T21:59:59"),
            make_order(22, CUSTOMER_A, date_created_gmt="2026-03-29T22:00:00"),
            make_order(23, CUSTOMER_A, date_created_gmt="2026-03-28T22:59:59"),
            make_order(24, CUSTOMER_B, date_created_gmt="2026-03-29T12:00:00")]
    woo = FakeWooClient({"orders": rows})
    result = await OrderService(CUSTOMER_A, woo).list_orders(
        date_from="2026-03-29", date_to="2026-03-29", limit=10,
    )
    assert "Ordine #20\n" in result and "Ordine #21\n" in result
    assert all(f"Ordine #{i}\n" not in result for i in (22, 23, 24))
    params = woo.params_for("orders")
    assert params["after"] == "2026-03-28T22:59:59"
    assert params["before"] == "2026-03-29T22:00:00"
    assert params["dates_are_gmt"] == "true" and params["customer"] == CUSTOMER_A
    assert "Europe/Rome" in result


async def test_order_list_interval_and_pagination_are_forwarded_by_tool():
    woo = FakeWooClient({"orders": [make_order(22, CUSTOMER_A)]})
    toolset = build_toolset(Session("a@example.invalid", CUSTOMER_A),
                           order_service=OrderService(CUSTOMER_A, woo))
    tool = next(t for t in toolset.tools if t.name == "elenco_ordini")
    result = await tool.ainvoke({"date_from": "2026-07-01", "date_to": "2026-07-31",
                                "page": 2, "limit": 1})
    assert "Ordine #22" in result and "Pagina 2" in result and "parziali" in result
    params = woo.params_for("orders")
    assert params["page"] == 2 and params["per_page"] == 1
    assert params["after"] == "2026-06-30T21:59:59"
    assert params["before"] == "2026-07-31T22:00:00"
    assert "customer_id" not in tool.args_schema.model_fields
    with pytest.raises(ValidationError):
        await tool.ainvoke({"customer_id": CUSTOMER_B})
    assert len(woo.calls) == 1


async def test_final_page_and_empty_filtered_page_do_not_claim_full_history():
    woo = FakeWooClient({"orders": [make_order(22, CUSTOMER_B)]})
    result = await OrderService(CUSTOMER_A, woo).list_orders(page=50, limit=1)
    assert "Nessun ordine trovato" in result and "Limite di 50 pagine" in result
    assert "L'account non ha ordini" not in result


def test_invalid_order_timezone_fails_configuration():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, wc_order_timezone="Not/AZone")
