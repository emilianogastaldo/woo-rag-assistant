"""Tool ordini: scoping sul cliente della sessione.

Copre gli scenari obbligatori 3 e 4 di CLAUDE.md: il cliente vede il proprio
ordine, e l'ordine di un altro cliente risulta "non trovato".
"""
from __future__ import annotations

from app.tools.orders import ORDER_NOT_FOUND, OrderService
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


async def test_data_completamento_esposta_per_il_caso_reso():
    """Il caso misto (posso ancora rendere?) ha bisogno della data di consegna."""
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
    assert "20/06/2026" in result
