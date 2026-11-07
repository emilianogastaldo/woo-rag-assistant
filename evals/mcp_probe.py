"""Real MCP JSON-RPC over STDIO, invoked only in the disposable integration stack."""
from __future__ import annotations

import json


def probe(cli, run):
    expected = json.loads(run([*cli, "wp", "eval-file", "/mcp-setup.php"]))
    first_id = next(iter(expected.values()))["id"]

    def request(identifier, method, params):
        return {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}

    def call(identifier, name, arguments):
        return request(identifier, "tools/call", {"name": name, "arguments": arguments})

    def execute(identifier, ability, parameters):
        return call(identifier, "mcp-adapter-execute-ability",
                    {"ability_name": ability, "parameters": parameters})

    def exchange(user, requests):
        initialize = request(1, "initialize", {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "woo-rag-mcp-probe", "version": "1.0"},
        })
        messages = [initialize, {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    *requests]
        output = run([*cli, "wp", "mcp-adapter", "serve",
                      "--server=mcp-adapter-default-server", f"--user={user}"],
                     input="\n".join(json.dumps(m) for m in messages) + "\n")
        responses = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
        by_id = {r["id"]: r for r in responses}
        assert set(by_id) == {1, *(r["id"] for r in requests)}, "Missing MCP responses"
        assert by_id[1]["result"]["protocolVersion"] == "2025-11-25"
        return by_id

    def data(response):
        assert "error" not in response, response
        result = response["result"]
        assert not result.get("isError"), response
        if "structuredContent" in result:
            return result["structuredContent"]
        return json.loads(next(c["text"] for c in result["content"] if c["type"] == "text"))

    def failure(response):
        if "error" in response:
            assert response["error"]["code"] < 0, response
            return response["error"]["message"]
        result = response["result"]
        if result.get("isError") is True:
            return "\n".join(c["text"] for c in result["content"] if c["type"] == "text")
        value = data(response)
        assert value.get("success") is False, response
        return value["error"]

    responses = exchange("mcp-reader", [
        request(2, "tools/list", {}),
        call(3, "mcp-adapter-discover-abilities", {}),
        call(4, "mcp-adapter-get-ability-info", {"ability_name": "woocommerce/products-query"}),
        execute(5, "woocommerce/products-query", {"status": "publish", "per_page": 100}),
        execute(6, "woocommerce/products-query", {"sku": "TSHIRT-BIO", "status": "publish"}),
        execute(7, "woocommerce/products-query", {"status": "publish", "per_page": 2, "page": 2}),
        execute(8, "woocommerce/product-update", {"id": first_id, "name": "MUST NOT CHANGE"}),
        execute(9, "woocommerce/orders-query", {"per_page": 1}),
        execute(10, "woocommerce/products-query", {"per_page": 101}),
    ])
    tools = sorted(t["name"] for t in responses[2]["result"]["tools"])
    assert "mcp-adapter-execute-ability" in tools
    assert "woocommerce/products-query" in json.dumps(data(responses[3]))
    schema = data(responses[4])
    assert schema["input_schema"]["properties"]["per_page"]["maximum"] == 100
    catalog = data(responses[5])
    assert catalog["success"], catalog
    rows = catalog["data"]["products"]
    assert len(rows) == len(expected)
    actual = {p["sku"]: {k: p[k] for k in expected[p["sku"]]} for p in rows}
    assert actual == expected, "MCP results differ from WooCommerce data"
    filtered = data(responses[6])
    assert filtered["success"]
    assert [p["sku"] for p in filtered["data"]["products"]] == ["TSHIRT-BIO"]
    page = data(responses[7])
    assert page["success"] and len(page["data"]["products"]) == 2
    assert page["data"]["page"] == 2 and page["data"]["total_pages"] == 3
    assert page["data"]["per_page"] == 2
    assert page["data"]["products"] == rows[2:4]

    def denied(response):
        value = failure(response)
        text = value.lower()
        assert "permission" in text or "allowed" in text or "unauthorized" in text, value
        return value

    write_denial = denied(responses[8])
    orders_denial = denied(responses[9])
    invalid = failure(responses[10])
    assert "per_page" in invalid and "100" in invalid, invalid
    restricted = exchange("mcp-denied", [
        execute(5, "woocommerce/products-query", {"status": "publish"}),
    ])
    read_denial = denied(restricted[5])
    assert json.loads(run([*cli, "wp", "eval-file", "/mcp-setup.php"])) == expected
    return {"status": "PASS", "transport": "stdio", "protocol": "2025-11-25",
            "adapter": "0.7.1", "tools": tools, "products": len(rows),
            "schema_discovery": "PASS", "sku_filter": "PASS", "pagination": "PASS",
            "product_write_denied": "PASS", "orders_denied": "PASS",
            "missing_catalog_permission_denied": "PASS", "invalid_input_rejected": "PASS",
            "error_evidence": {"product_write": write_denial, "orders": orders_denial,
                               "missing_catalog_permission": read_denial,
                               "invalid_per_page": invalid},
            "catalog_unchanged": "PASS", "provider_calls": 0}
