# ruff: noqa
# Copyright 2026 Google LLC

import os
import re
import sys
import json
import logging
from typing import Any
from pydantic import BaseModel, Field

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types
from google.adk.workflow import Workflow, Edge, START, node
from google.adk.tools import AgentTool, McpToolset, ToolContext
from mcp import StdioServerParameters

from .config import config

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("smart-crm-assistant")

# State schemas
class CRMState(BaseModel):
    user_query: str = ""
    lead_score: float = 0.0
    lead_classification: str = ""
    draft_response: str = ""
    approval_status: str = "pending"
    approver_comments: str = ""

class LeadEvaluation(BaseModel):
    lead_score: float = Field(description="Score between 0.0 and 1.0 based on business potential and urgency")
    lead_classification: str = Field(description="Classification: 'High Value', 'Mid Value', or 'Low Value'")

# MCP Server integration
mcp_server_path = os.path.join(os.path.dirname(__file__), 'mcp_server.py')
crm_mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command=sys.executable,
        args=[mcp_server_path],
    )
)

# Specialized sub-agents
lead_scoring_agent = LlmAgent(
    name="lead_scoring_agent",
    instruction="""Analyze the customer's email query.
First, call the `search_customer_database` tool using the sender's email or name if present in the query.
If found, call `get_customer_profile` with the customer ID to see their subscription tier, lifetime value, and past notes.

Calculate a lead score between 0.0 and 1.0 based on:
- Opportunity size/interest (VIP tier customer or enterprise buying interest gets higher score).
- Urgency (urgent requests get higher score).

Also classify the lead into one of these tiers:
- 'High Value': Clear buying interest, enterprise query, VIP tier customer, or high urgency.
- 'Mid Value': Standard product questions, general inquiries.
- 'Low Value': Spam, complaints, or unrelated inquiries.

You must structure your response according to the output schema.""",
    tools=[crm_mcp_toolset],
    output_schema=LeadEvaluation,
    model=Gemini(
        model=config.model,
        retry_options=types.HttpRetryOptions(attempts=6),
    ),
)

email_drafting_agent = LlmAgent(
    name="email_drafting_agent",
    instruction="""You are a professional CRM email writer.
Draft a polite, helpful, and personalized reply to the customer's inquiry.
First, call `get_templates` tool for the appropriate category ('sales', 'support', or 'general') based on the query type.
Then use that template to draft the response.

Tailor your tone based on the lead classification:
- For 'High Value': Use a highly attentive, professional, VIP consultative tone. Suggest scheduling a call.
- For 'Mid Value': Use a helpful, friendly, and standard professional tone.
- For 'Low Value': Use a brief, polite, and standardized tone.

Return only the drafted email response text.""",
    tools=[crm_mcp_toolset],
    model=Gemini(
        model=config.model,
        retry_options=types.HttpRetryOptions(attempts=6),
    ),
)

# Inter-node state sharing tool
def update_crm_state(tool_context: ToolContext, lead_score: float, lead_classification: str, draft_response: str) -> str:
    """Updates the CRM state with evaluation and response draft.
    
    Args:
        tool_context: The context of the current session.
        lead_score: Score of the lead from 0.0 and 1.0.
        lead_classification: Tier of the lead ('High Value', 'Mid Value', or 'Low Value').
        draft_response: The drafted email response.
    """
    tool_context.state["lead_score"] = lead_score
    tool_context.state["lead_classification"] = lead_classification
    tool_context.state["draft_response"] = draft_response
    return "CRM state updated successfully."

# Orchestrator agent
crm_orchestrator = LlmAgent(
    name="crm_orchestrator",
    instruction="""You are the CRM Orchestrator Agent.
Your job is to coordinate the processing of incoming customer inquiries.
The customer inquiry is passed to you as input.

You have access to two specialized sub-agents:
1. `lead_scoring_agent`: Call this tool first with the customer inquiry to evaluate the lead score and classification tier ('High Value', 'Mid Value', or 'Low Value').
2. `email_drafting_agent`: Call this tool second. Provide the customer inquiry along with the lead score and classification, so it can draft a personalized response.

After you receive the draft response and evaluation:
1. Call the `update_crm_state` tool to save `lead_score`, `lead_classification`, and `draft_response` into the system state.
2. Call the `log_interaction` tool from MCP using the customer ID if resolved (or name/details) to record the interaction.

Finally, return a clear summary of your findings and the draft response. Make sure to call `update_crm_state` BEFORE returning your final answer.""",
    tools=[AgentTool(lead_scoring_agent), AgentTool(email_drafting_agent), update_crm_state, crm_mcp_toolset],
    model=Gemini(
        model=config.model,
        retry_options=types.HttpRetryOptions(attempts=6),
    ),
)

# Workflow function nodes
@node
def security_checkpoint(ctx, node_input: str) -> str:
    """Performs security screening, including PII scrubbing, injection detection, and content filtering."""
    # Save the raw query to state
    ctx.state["user_query"] = node_input

    # Prompt injection check
    injection_keywords = ["ignore previous instructions", "system prompt", "bypass", "override", "you are now a"]
    for kw in injection_keywords:
        if kw in node_input.lower():
            logger.warning(json.dumps({
                "severity": "CRITICAL",
                "event": "prompt_injection_detected",
                "keyword": kw,
                "input": node_input
            }))
            ctx.route = "SECURITY_EVENT"
            return "Security violation: potential prompt injection detected."

    # PII scrubbing (Redact credit cards and SSNs)
    cc_regex = r"\b(?:\d[ -]*?){13,16}\b"
    scrubbed = re.sub(cc_regex, "[REDACTED_CREDIT_CARD]", node_input)
    
    ssn_regex = r"\b\d{3}-\d{2}-\d{4}\b"
    scrubbed = re.sub(ssn_regex, "[REDACTED_SSN]", scrubbed)

    # Domain specific rule: content filtering for spam keywords
    spam_keywords = ["spam_scam", "hack_me", "buy_bitcoin_now"]
    for kw in spam_keywords:
        if kw in scrubbed.lower():
            logger.warning(json.dumps({
                "severity": "WARNING",
                "event": "content_filter_triggered",
                "keyword": kw,
                "input": scrubbed
            }))
            ctx.route = "SECURITY_EVENT"
            return "Security violation: spam or offensive content filtered."

    # Log successful check
    logger.info(json.dumps({
        "severity": "INFO",
        "event": "security_checkpoint_passed",
        "message": "Input passed security checks."
    }))

    ctx.route = "DEFAULT"
    return scrubbed

@node(rerun_on_resume=True)
def human_review_node(ctx, lead_classification: str | None = "", draft_response: str | None = "") -> Any:
    """Coordinates the human-in-the-loop review for High Value leads using RequestInput."""
    # Fallback to state if not bound directly
    lead_classification = lead_classification or ctx.state.get("lead_classification", "Mid Value")
    draft_response = draft_response or ctx.state.get("draft_response", "")

    interrupt_id = "crm_human_approval"
    user_response = ctx.resume_inputs.get(interrupt_id)
    
    if user_response is not None:
        approve = user_response.get("approve", False)
        comments = user_response.get("comments", "")
        ctx.state["approval_status"] = "approved" if approve else "rejected"
        ctx.state["approver_comments"] = comments
        
        if approve:
            ctx.route = "APPROVED"
            return f"Approved response: {draft_response}\nComments: {comments}"
        else:
            ctx.route = "REJECTED"
            return f"Rejected response: {draft_response}\nComments: {comments}"

    if lead_classification == "High Value":
        from google.adk.events import RequestInput
        from pydantic import BaseModel, Field

        class ReviewResponse(BaseModel):
            approve: bool = Field(description="True if you approve sending this draft response, False otherwise")
            comments: str = Field(default="", description="Review comments or feedback")

        ctx.route = "NEEDS_APPROVAL"
        return RequestInput(
            interrupt_id=interrupt_id,
            message=f"Please review and approve the draft response for the High Value lead:\n\n{draft_response}",
            response_schema=ReviewResponse,
        )
    else:
        ctx.route = "AUTO_APPROVED"
        return f"Auto-approved response: {draft_response}"

@node
def security_failure(ctx, node_input: str) -> str:
    """Node executed when a security check fails."""
    return f"Failed to process inquiry: {node_input}"

@node
def rejection_node(ctx, approver_comments: str | None = "", draft_response: str | None = "") -> str:
    """Node executed when human review rejects the draft response."""
    approver_comments = approver_comments or ctx.state.get("approver_comments", "")
    draft_response = draft_response or ctx.state.get("draft_response", "")
    return f"Draft response was rejected by reviewer with comments: '{approver_comments}'. A new draft should be created."


@node
def final_output(ctx, node_input: str) -> str:
    """Terminal node displaying the final approved email draft."""
    return f"Final approved email draft:\n\n{node_input}"

# Workflow definition
crm_workflow = Workflow(
    name="crm_workflow",
    state_schema=CRMState,
    edges=[
        (START, security_checkpoint),
        Edge(from_node=security_checkpoint, to_node=crm_orchestrator, route="DEFAULT"),
        Edge(from_node=security_checkpoint, to_node=security_failure, route="SECURITY_EVENT"),
        (crm_orchestrator, human_review_node),
        Edge(from_node=human_review_node, to_node=final_output, route=["APPROVED", "AUTO_APPROVED"]),
        Edge(from_node=human_review_node, to_node=rejection_node, route="REJECTED")
    ]
)

root_agent = crm_workflow

# App exposing workflow
app = App(
    root_agent=crm_workflow,
    name="app",
)

