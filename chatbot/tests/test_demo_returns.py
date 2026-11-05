"""Date demo esplicite: stessa finestra backend, nessun provider o clock finto."""
from datetime import date, datetime

import pytest

from app.tools.orders import format_order


@pytest.mark.parametrize(
    ("delivery", "reference", "expected_deadline", "within"),
    [
        ("2026-11-19T14:30:00Z", "2026-12-18", "19/12/2026", True),
        ("2026-11-19T14:30:00Z", "2026-12-19", "19/12/2026", True),
        ("2026-11-19T14:30:00Z", "2026-12-20", "19/12/2026", False),
        ("2026-06-22T14:30:00Z", "2026-12-18", "22/07/2026", False),
        ("2026-06-22T14:30:00Z", "2026-12-19", "22/07/2026", False),
    ],
)
def test_demo_return_window(delivery, reference, expected_deadline, within):
    result = format_order({"meta_data": [{"key": "_wrag_delivery_date", "value": delivery}]})
    deadline_line = next(line for line in result.splitlines() if line.startswith("Scadenza reso"))
    deadline = deadline_line.rsplit(": ", 1)[1]
    assert deadline == expected_deadline
    deadline_date = datetime.strptime(deadline, "%d/%m/%Y").date()
    assert (date.fromisoformat(reference) <= deadline_date) is within


def test_completed_demo_order_without_tracking_has_no_return_deadline():
    result = format_order({"status": "completed", "date_completed": "2026-11-19T14:30:00Z"})
    assert "Data completamento: 19/11/2026" in result
    assert "Scadenza reso: non calcolabile senza una data di consegna verificata" in result
    assert "19/12/2026" not in result
