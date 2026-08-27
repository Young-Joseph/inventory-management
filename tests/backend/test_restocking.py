"""
Tests for restocking API endpoints.
"""
from datetime import datetime

import pytest

import mock_data


@pytest.fixture(autouse=True)
def restore_orders():
    """Undo restocking orders appended during a test.

    The test client shares a single imported app, so the in-memory orders list
    persists across tests. Snapshot its length and truncate afterwards so a POST
    in one test cannot leak into another.
    """
    original_length = len(mock_data.orders)
    yield
    del mock_data.orders[original_length:]


def build_order_payload(client, budget=25000):
    """Build a restocking order request from the recommendations at a budget."""
    response = client.get(f"/api/restocking/recommendations?budget={budget}")
    recommendations = response.json()["recommendations"]

    return {
        "budget": budget,
        "items": [
            {
                "sku": item["item_sku"],
                "name": item["item_name"],
                "quantity": item["recommended_quantity"],
                "unit_price": item["unit_cost"],
            }
            for item in recommendations
        ],
    }


class TestRestockingRecommendationEndpoints:
    """Test suite for restocking recommendation endpoints."""

    def test_get_recommendations(self, client):
        """Test getting restocking recommendations."""
        response = client.get("/api/restocking/recommendations?budget=25000")
        assert response.status_code == 200

        data = response.json()
        assert "budget" in data
        assert "recommendations" in data
        assert "total_cost" in data
        assert "budget_remaining" in data
        assert "items_recommended" in data
        assert "unfunded_count" in data
        assert isinstance(data["recommendations"], list)
        assert len(data["recommendations"]) > 0

    def test_recommendation_structure(self, client):
        """Test that recommendations have proper structure."""
        response = client.get("/api/restocking/recommendations?budget=50000")
        data = response.json()

        for item in data["recommendations"]:
            assert "item_sku" in item
            assert "item_name" in item
            assert "category" in item
            assert "warehouse" in item
            assert "quantity_on_hand" in item
            assert "reorder_point" in item
            assert "forecasted_demand" in item
            assert "trend" in item
            assert "unit_cost" in item
            assert "recommended_quantity" in item
            assert "line_cost" in item
            assert "lead_time_days" in item
            assert "urgency" in item

            assert isinstance(item["recommended_quantity"], int)
            assert isinstance(item["lead_time_days"], int)
            assert isinstance(item["unit_cost"], (int, float))
            assert item["recommended_quantity"] > 0
            assert item["lead_time_days"] > 0

    def test_zero_budget_recommends_nothing(self, client):
        """Test that a zero budget produces no recommendations."""
        response = client.get("/api/restocking/recommendations?budget=0")
        assert response.status_code == 200

        data = response.json()
        assert data["recommendations"] == []
        assert data["total_cost"] == 0
        assert data["items_recommended"] == 0

    def test_negative_budget_rejected(self, client):
        """Test that a negative budget returns a bad request error."""
        response = client.get("/api/restocking/recommendations?budget=-100")
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data
        assert "negative" in data["detail"].lower()

    def test_total_cost_never_exceeds_budget(self, client):
        """Test that recommendations always fit inside the budget."""
        for budget in [500, 5000, 15000, 25000, 50000]:
            response = client.get(f"/api/restocking/recommendations?budget={budget}")
            assert response.status_code == 200

            data = response.json()
            assert data["total_cost"] <= budget

            # Line costs must add up to the reported total
            calculated_total = sum(item["line_cost"] for item in data["recommendations"])
            assert abs(data["total_cost"] - calculated_total) < 0.01

            # And the remainder must reconcile
            assert abs(data["budget_remaining"] - (budget - data["total_cost"])) < 0.01

    def test_line_cost_calculation(self, client):
        """Test that each line cost is quantity times unit cost."""
        response = client.get("/api/restocking/recommendations?budget=50000")
        data = response.json()

        for item in data["recommendations"]:
            calculated = item["recommended_quantity"] * item["unit_cost"]
            assert abs(item["line_cost"] - calculated) < 0.01

    def test_recommendations_sorted_by_urgency(self, client):
        """Test that recommendations are ordered most urgent first."""
        response = client.get("/api/restocking/recommendations?budget=50000")
        data = response.json()

        urgencies = [item["urgency"] for item in data["recommendations"]]
        assert urgencies == sorted(urgencies, reverse=True)

    def test_recommended_quantity_covers_shortfall_at_most(self, client):
        """Test that no item is over-ordered beyond its forecast shortfall."""
        response = client.get("/api/restocking/recommendations?budget=50000")
        data = response.json()

        for item in data["recommendations"]:
            shortfall = item["forecasted_demand"] - item["quantity_on_hand"]
            assert shortfall > 0
            assert item["recommended_quantity"] <= shortfall

    def test_well_stocked_items_excluded(self, client):
        """Test that items already covering their forecast are never recommended."""
        response = client.get("/api/restocking/recommendations?budget=50000")
        data = response.json()

        recommended_skus = {item["item_sku"] for item in data["recommendations"]}
        # MTR-304 has a decreasing forecast and PSU-501 is well stocked
        assert "MTR-304" not in recommended_skus
        assert "PSU-501" not in recommended_skus

    def test_recommendations_grow_with_budget(self, client):
        """Test that raising the budget never funds fewer items."""
        previous_count = -1
        for budget in [0, 5000, 15000, 25000, 50000]:
            response = client.get(f"/api/restocking/recommendations?budget={budget}")
            count = response.json()["items_recommended"]
            assert count >= previous_count
            previous_count = count

    def test_get_recommendations_by_warehouse(self, client):
        """Test filtering recommendations by warehouse."""
        response = client.get("/api/restocking/recommendations?budget=50000&warehouse=Tokyo")
        assert response.status_code == 200

        data = response.json()
        assert len(data["recommendations"]) > 0
        for item in data["recommendations"]:
            assert item["warehouse"] == "Tokyo"

    def test_get_recommendations_by_category(self, client):
        """Test filtering recommendations by category."""
        response = client.get("/api/restocking/recommendations?budget=50000&category=sensors")
        assert response.status_code == 200

        data = response.json()
        for item in data["recommendations"]:
            assert item["category"].lower() == "sensors"

    def test_unfunded_count_accounts_for_remaining_candidates(self, client):
        """Test that a generous budget leaves nothing unfunded."""
        response = client.get("/api/restocking/recommendations?budget=50000")
        data = response.json()
        assert data["unfunded_count"] == 0

        response = client.get("/api/restocking/recommendations?budget=0")
        assert response.json()["unfunded_count"] > 0


class TestRestockingOrderEndpoints:
    """Test suite for restocking order submission endpoints."""

    def test_get_restocking_orders_empty(self, client):
        """Test getting restocking orders before any are submitted."""
        response = client.get("/api/restocking/orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_restocking_order(self, client):
        """Test submitting a restocking order."""
        payload = build_order_payload(client)
        response = client.post("/api/restocking/orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        assert order["order_type"] == "restock"
        assert order["status"] == "Processing"
        assert order["customer"] == "Internal Restock"
        assert order["order_number"].startswith("RST-")
        assert len(order["items"]) == len(payload["items"])

    def test_created_order_total_value_calculation(self, client):
        """Test that the submitted order total matches its line items."""
        payload = build_order_payload(client)
        order = client.post("/api/restocking/orders", json=payload).json()

        calculated_total = sum(
            item["quantity"] * item["unit_price"] for item in order["items"]
        )
        assert abs(order["total_value"] - calculated_total) < 0.01

    def test_created_order_delivery_uses_longest_lead_time(self, client):
        """Test that expected delivery reflects the slowest item in the order."""
        recommendations = client.get(
            "/api/restocking/recommendations?budget=25000"
        ).json()["recommendations"]
        expected_lead_time = max(item["lead_time_days"] for item in recommendations)

        payload = build_order_payload(client)
        order = client.post("/api/restocking/orders", json=payload).json()

        ordered = datetime.fromisoformat(order["order_date"])
        expected = datetime.fromisoformat(order["expected_delivery"])
        assert (expected - ordered).days == expected_lead_time

    def test_created_order_dates_format(self, client):
        """Test that submitted order dates are in ISO format."""
        payload = build_order_payload(client)
        order = client.post("/api/restocking/orders", json=payload).json()

        assert "T" in order["order_date"]
        assert "T" in order["expected_delivery"]
        assert order["actual_delivery"] is None

    def test_submitted_order_appears_in_restocking_orders(self, client):
        """Test that a submitted order is listed under restocking orders."""
        payload = build_order_payload(client)
        created = client.post("/api/restocking/orders", json=payload).json()

        response = client.get("/api/restocking/orders")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert data[0]["order_number"] == created["order_number"]

    def test_submitted_order_excluded_from_customer_orders(self, client):
        """Test that restocking orders do not appear in the customer order list."""
        before = len(client.get("/api/orders").json())

        payload = build_order_payload(client)
        created = client.post("/api/restocking/orders", json=payload).json()

        orders_after = client.get("/api/orders").json()
        assert len(orders_after) == before
        assert all(order["id"] != created["id"] for order in orders_after)

    def test_submitted_order_does_not_change_dashboard(self, client):
        """Test that submitting a restocking order leaves dashboard totals intact."""
        before = client.get("/api/dashboard/summary").json()

        payload = build_order_payload(client)
        client.post("/api/restocking/orders", json=payload)

        after = client.get("/api/dashboard/summary").json()
        assert after["pending_orders"] == before["pending_orders"]
        assert abs(after["total_orders_value"] - before["total_orders_value"]) < 0.01

    def test_restocking_orders_newest_first(self, client):
        """Test that restocking orders are returned newest first."""
        client.post("/api/restocking/orders", json=build_order_payload(client, 5000))
        client.post("/api/restocking/orders", json=build_order_payload(client, 15000))

        data = client.get("/api/restocking/orders").json()
        assert len(data) == 2
        assert data[0]["order_date"] >= data[1]["order_date"]

    def test_create_order_with_no_items(self, client):
        """Test that an empty restocking order is rejected."""
        response = client.post("/api/restocking/orders", json={"budget": 1000, "items": []})
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data
        assert "at least one item" in data["detail"].lower()

    def test_create_order_with_unknown_sku(self, client):
        """Test that an unknown SKU is rejected."""
        response = client.post(
            "/api/restocking/orders",
            json={
                "budget": 1000,
                "items": [
                    {"sku": "NOPE-999", "name": "Unknown", "quantity": 5, "unit_price": 10.0}
                ],
            },
        )
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data
        assert "unknown sku" in data["detail"].lower()

    def test_create_order_with_zero_quantity(self, client):
        """Test that a non-positive quantity is rejected."""
        response = client.post(
            "/api/restocking/orders",
            json={
                "budget": 1000,
                "items": [
                    {"sku": "WDG-001", "name": "Industrial Widget Type A",
                     "quantity": 0, "unit_price": 24.99}
                ],
            },
        )
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data
        assert "greater than zero" in data["detail"].lower()

    def test_create_order_missing_items_field(self, client):
        """Test that a malformed request body returns a validation error."""
        response = client.post("/api/restocking/orders", json={"budget": 1000})
        assert response.status_code == 422

        data = response.json()
        assert "detail" in data
