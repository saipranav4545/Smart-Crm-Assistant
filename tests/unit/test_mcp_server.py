import json
import pytest
from app.mcp_server import (
    search_customer_database,
    get_customer_profile,
    log_interaction,
    get_templates,
    INTERACTION_LOGS
)

def test_search_customer_database():
    # Search by name
    results_str = search_customer_database("Jane")
    results = json.loads(results_str)
    assert len(results) == 1
    assert results[0]["name"] == "Jane Smith"

    # Search by company
    results_str = search_customer_database("Standard Tech")
    results = json.loads(results_str)
    assert len(results) == 1
    assert results[0]["company"] == "Standard Tech"

    # Search non-existent
    results_str = search_customer_database("nonexistent_company")
    results = json.loads(results_str)
    assert len(results) == 0

def test_get_customer_profile():
    # Valid customer
    profile_str = get_customer_profile("cust_001")
    profile = json.loads(profile_str)
    assert profile["id"] == "cust_001"
    assert profile["name"] == "Jane Smith"

    # Invalid customer
    error_msg = get_customer_profile("cust_unknown")
    assert "not found" in error_msg

def test_log_interaction():
    initial_log_count = len(INTERACTION_LOGS)
    res = log_interaction("cust_001", "Customer requested product pricing details.")
    assert "Successfully logged interaction" in res
    assert len(INTERACTION_LOGS) == initial_log_count + 1
    assert INTERACTION_LOGS[-1]["customer_id"] == "cust_001"
    assert INTERACTION_LOGS[-1]["notes"] == "Customer requested product pricing details."

def test_get_templates():
    # Valid category
    sales_template = get_templates("sales")
    assert "Dear {name}" in sales_template
    assert "Sales Team" in sales_template

    # Invalid category returns all templates in JSON
    all_templates_str = get_templates("unknown_category")
    all_templates = json.loads(all_templates_str)
    assert "sales" in all_templates
    assert "support" in all_templates
