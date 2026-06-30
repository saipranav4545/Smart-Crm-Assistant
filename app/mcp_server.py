import os
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("smart-crm-server")

# In-memory mock database
CUSTOMERS = {
    "cust_001": {
        "id": "cust_001",
        "name": "Jane Smith",
        "email": "jane.smith@enterprise.com",
        "tier": "VIP",
        "lifetime_value": 25000.0,
        "company": "Enterprise Corp",
        "purchase_history": ["Enterprise License X10", "Premium Consulting Support"],
        "notes": "Interested in scaling their enterprise deployment next quarter."
    },
    "cust_002": {
        "id": "cust_002",
        "name": "Bob Johnson",
        "email": "bob@standardtech.io",
        "tier": "Basic",
        "lifetime_value": 1500.0,
        "company": "Standard Tech",
        "purchase_history": ["Single Developer License"],
        "notes": "Usually submits basic troubleshooting requests."
    }
}

TEMPLATES = {
    "sales": "Dear {name},\n\nThank you for reaching out to us! We are excited to assist you with your business needs. {custom_details}\n\nBest regards,\nSales Team",
    "support": "Dear {name},\n\nThank you for contacting Support. We've received your request and our team is looking into it. {custom_details}\n\nBest regards,\nSupport Team",
    "general": "Dear {name},\n\nThank you for your message. {custom_details}\n\nBest regards,\nCRM Team"
}

INTERACTION_LOGS = []

@mcp.tool()
def search_customer_database(query: str) -> str:
    """Searches the customer CRM database by query (e.g., name, company, email).
    
    Args:
        query: Search term.
    """
    query_lower = query.lower()
    results = []
    for c_id, profile in CUSTOMERS.items():
        if (query_lower in profile["name"].lower() or 
            query_lower in profile["email"].lower() or 
            query_lower in profile["company"].lower()):
            results.append(profile)
    return json.dumps(results, indent=2)

@mcp.tool()
def get_customer_profile(customer_id: str) -> str:
    """Retrieves detailed metadata for a specific customer.
    
    Args:
        customer_id: The ID of the customer (e.g. cust_001).
    """
    profile = CUSTOMERS.get(customer_id)
    if profile:
        return json.dumps(profile, indent=2)
    return f"Customer with ID {customer_id} not found."

@mcp.tool()
def log_interaction(customer_id: str, notes: str) -> str:
    """Records a log entry of the email interaction in the CRM database.
    
    Args:
        customer_id: The ID of the customer.
        notes: Summary of the interaction.
    """
    log_entry = {
        "customer_id": customer_id,
        "notes": notes,
        "timestamp": "2026-07-01T00:00:00Z"
    }
    INTERACTION_LOGS.append(log_entry)
    return f"Successfully logged interaction for customer {customer_id}."

@mcp.tool()
def get_templates(category: str) -> str:
    """Retrieves company-approved response templates.
    
    Args:
        category: The response category (e.g. 'sales', 'support', 'general').
    """
    template = TEMPLATES.get(category.lower())
    if template:
        return template
    return json.dumps(TEMPLATES, indent=2)

if __name__ == "__main__":
    mcp.run("stdio")
