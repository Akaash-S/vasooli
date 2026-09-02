from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_summary_endpoint():
    mock_data = {
        "total_cases": 200,
        "recovered_count": 104,
        "escalated_count": 28,
        "abandoned_count": 68,
        "recovery_rate_pct": 52.0,
        "total_amount_at_risk": 2000000.0,
        "total_amount_recovered": 1037933.99,
        "dollar_recovery_rate_pct": 51.9,
        "avg_time_to_recovery_hours": 48.0,
        "median_time_to_recovery_hours": 48.0,
        "by_resolution_source": {"real": 1, "simulated": 199},
    }
    with patch("app.metrics.aggregations.get_batch_summary", return_value=mock_data):
        response = client.get("/api/metrics/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["total_cases"] == 200
        assert "recovery_rate_pct" in data
        assert "dollar_recovery_rate_pct" in data


def test_breakdown_endpoint_validation():
    mock_breakdown = [
        {
            "dimension": "soft_decline",
            "count": 50,
            "recovered_count": 28,
            "recovery_rate_pct": 56.0,
            "amount_at_risk": 50000.0,
            "amount_recovered": 28000.0,
            "dollar_recovery_rate_pct": 56.0,
        }
    ]
    with patch("app.metrics.aggregations.get_breakdown", return_value=mock_breakdown):
        res_valid = client.get("/api/metrics/breakdown?by=risk_status")
        assert res_valid.status_code == 200
        assert len(res_valid.json()) == 1

        res_invalid = client.get("/api/metrics/breakdown?by=invalid_param")
        assert res_invalid.status_code == 422


def test_exceptions_endpoint():
    mock_exceptions = {
        "total": 2,
        "real_note_used": 2,
        "fallback_used": 0,
        "cases": [
            {"case_id": "c-1", "outcome": "escalated"},
            {"case_id": "c-2", "outcome": "abandoned"},
        ],
    }
    with patch("app.metrics.aggregations.get_exception_list", return_value=mock_exceptions):
        response = client.get("/api/cases/exceptions")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == len(data["cases"]) == 2


def test_audit_trail_endpoint():
    mock_trail = {
        "case_id": "c-100",
        "events": [
            {"event_type": "case_detected", "occurred_at": "2026-08-25T10:00:00Z", "payload": {}},
            {"event_type": "case_resolved", "occurred_at": "2026-08-28T11:00:00Z", "payload": {}},
        ],
    }
    with patch("app.metrics.aggregations.get_case_audit_trail", return_value=mock_trail):
        response = client.get("/api/cases/c-100/audit-trail")
        assert response.status_code == 200
        data = response.json()
        assert data["case_id"] == "c-100"
        assert len(data["events"]) == 2


def test_list_cases_endpoint():
    mock_list = {
        "total": 104,
        "limit": 10,
        "offset": 0,
        "cases": [{"case_id": f"c-{i}", "outcome": "recovered"} for i in range(10)],
    }
    with patch("app.metrics.aggregations.list_cases", return_value=mock_list):
        response = client.get("/api/cases?outcome=recovered&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 104
        assert len(data["cases"]) == 10
