"""
Conversation State Management
Tracks the state of the eligibility conversation
"""
from typing import TypedDict, List, Optional, Literal
from datetime import datetime


class Message(TypedDict):
    """Message in the conversation"""
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: str


class ConversationState(TypedDict):
    """
    State of the eligibility conversation
    Tracks all information needed for eligibility check
    """
    # Conversation tracking
    messages: List[Message]
    conversation_id: str
    
    # Required information for eligibility check
    member_id: Optional[str]
    date_of_birth: Optional[str]
    policy_number: Optional[str]
    
    # Service details
    service_type: Optional[Literal["medical", "pharmacy", "general"]]
    procedure_code: Optional[str]
    procedure_name: Optional[str]
    ndc_code: Optional[str]
    medication_name: Optional[str]
    service_date: Optional[str]
    
    # Provider information (optional)
    provider_npi: Optional[str]
    provider_name: Optional[str]
    
    # Agent tracking
    missing_fields: List[str]
    api_called: bool
    api_response: Optional[dict]
    eligibility_determined: bool
    
    # Additional context
    user_query: str
    next_action: Literal["gather_info", "call_api", "validate_response", "complete"]


def create_initial_state(conversation_id: str, user_query: str) -> ConversationState:
    """Create initial conversation state"""
    return {
        "messages": [],
        "conversation_id": conversation_id,
        "member_id": None,
        "date_of_birth": None,
        "policy_number": None,
        "service_type": None,
        "procedure_code": None,
        "procedure_name": None,
        "ndc_code": None,
        "medication_name": None,
        "service_date": None,
        "provider_npi": None,
        "provider_name": None,
        "missing_fields": [],
        "api_called": False,
        "api_response": None,
        "eligibility_determined": False,
        "user_query": user_query,
        "next_action": "gather_info"
    }


def get_required_fields(state: ConversationState) -> List[str]:
    """
    Determine which required fields are missing based on user intent.

    Logic:
    - Always need member_id + date_of_birth
    - If service_type is "pharmacy": need medication identified (ndc_code or medication_name)
    - If service_type is "medical": need procedure identified (procedure_code or procedure_name)
    - If service_type is not yet determined but user asked about something specific,
      we need them to clarify what service they're asking about
    """
    required = ["member_id", "date_of_birth"]

    service_type = state.get("service_type")

    if service_type == "pharmacy":
        # For pharmacy: need either ndc_code (resolved) or medication_name (to resolve)
        if not state.get("ndc_code") and not state.get("medication_name"):
            required.append("medication_name")
    elif service_type == "medical":
        # For medical: need either procedure_code (resolved) or procedure_name (to resolve)
        if not state.get("procedure_code") and not state.get("procedure_name"):
            required.append("procedure_name")

    # If no service_type set, only member_id + DOB are required.
    # The system will do a general eligibility check which is still useful.

    missing = []
    for field in required:
        if not state.get(field):
            missing.append(field)

    return missing


def get_field_display_name(field: str) -> str:
    """Convert field name to user-friendly display name"""
    display_names = {
        "member_id": "Member ID or Patient ID",
        "date_of_birth": "Date of Birth",
        "policy_number": "Insurance Policy Number",
        "procedure_code": "Procedure Code (CPT code)",
        "procedure_name": "the name of the procedure or service",
        "ndc_code": "NDC Code (medication code)",
        "medication_name": "the name of the medication",
        "service_date": "Service Date",
        "provider_npi": "Provider NPI Number"
    }
    return display_names.get(field, field.replace("_", " ").title())


def add_message(state: ConversationState, role: str, content: str) -> ConversationState:
    """Add a message to the conversation state"""
    message: Message = {
        "role": role,
        "content": content,
        "timestamp": datetime.now().isoformat()
    }
    state["messages"].append(message)
    return state


def update_state_from_extraction(state: ConversationState, extracted_info: dict) -> ConversationState:
    """Update state with extracted information"""
    for key, value in extracted_info.items():
        if value and key in state:
            state[key] = value
    return state
