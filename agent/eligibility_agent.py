"""
Insurance Eligibility Agent
Implements conversational agent using LangGraph for state management
"""
from typing import Dict, Any
import json
import re
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END

from .state import (
    ConversationState, 
    create_initial_state,
    get_required_fields,
    add_message,
    update_state_from_extraction,
    get_field_display_name
)
from .prompts import (
    SYSTEM_PROMPT,
    INFORMATION_EXTRACTION_PROMPT,
    RESPONSE_VALIDATION_PROMPT,
    CONVERSATIONAL_RESPONSE_TEMPLATE
)
from api.eligibility_api import MockEligibilityAPI
import time
from utils.logger import setup_logger

logger = setup_logger(__name__)


class EligibilityAgent:
    """
    Agentic AI for insurance eligibility verification
    Uses LangGraph for conversation flow management
    """
    
    def __init__(self, openai_api_key: str = None):
        """Initialize the eligibility agent with OpenAI API key"""
        
        # Use provided key or fallback to config
        api_key = openai_api_key or Config.OPENAI_API_KEY
        
        if not api_key:
            raise ValueError("OpenAI API key is required")
            
        # Initialize OpenAI client
        self.llm = ChatOpenAI(
            api_key=api_key,
            model="gpt-4o-mini", 
            temperature=0.1
        )
        
        # Initialize eligibility API
        self.eligibility_api = MockEligibilityAPI()
        
        # Build the workflow graph
        self.workflow = self._build_workflow()
        
        logger.info("🤖 Eligibility agent initialized")
    
    def _build_workflow(self) -> StateGraph:
        """Build the LangGraph state machine"""
        workflow = StateGraph(ConversationState)

        # Define nodes
        workflow.add_node("extract_information", self._extract_information_node)
        workflow.add_node("resolve_codes", self._resolve_codes_node)
        workflow.add_node("determine_next_action", self._determine_next_action_node)
        workflow.add_node("gather_more_info", self._gather_more_info_node)
        workflow.add_node("call_api", self._call_api_node)
        workflow.add_node("validate_response", self._validate_response_node)
        workflow.add_node("generate_final_response", self._generate_final_response_node)

        # Set entry point
        workflow.set_entry_point("extract_information")

        # Define edges — resolve codes after extraction, before deciding next action
        workflow.add_edge("extract_information", "resolve_codes")
        workflow.add_edge("resolve_codes", "determine_next_action")
        
        # Conditional routing from determine_next_action
        workflow.add_conditional_edges(
            "determine_next_action",
            self._route_next_action,
            {
                "gather_info": "gather_more_info",
                "call_api": "call_api",
                "complete": "generate_final_response"
            }
        )

        workflow.add_edge("gather_more_info", END)
        workflow.add_edge("call_api", "validate_response")

        # Conditional routing from validate_response
        workflow.add_conditional_edges(
            "validate_response",
            self._route_after_validation,
            {
                "gather_more": "gather_more_info",
                "complete": "generate_final_response"
            }
        )

        workflow.add_edge("generate_final_response", END)

        return workflow.compile()
    
    def process_message(self, conversation_id: str, user_message: str, 
                       current_state: ConversationState = None) -> Dict[str, Any]:
        """
        Process a user message and return agent response
        
        Args:
            conversation_id: Unique conversation identifier
            user_message: User's message
            current_state: Current conversation state (if continuing conversation)
            
        Returns:
            Dictionary with agent response and updated state
        """
        # Initialize or update state
        if current_state is None:
            state = create_initial_state(conversation_id, user_message)
        else:
            state = current_state
        
        # Add user message to state
        state = add_message(state, "user", user_message)
        
        # Run the graph
        result = self.graph.invoke(state)
        
        # Extract the assistant's response from messages
        assistant_messages = [m for m in result["messages"] if m["role"] == "assistant"]
        assistant_response = assistant_messages[-1]["content"] if assistant_messages else "I'm processing your request..."
        
        return {
            "response": assistant_response,
            "state": result,
            "eligibility_determined": result.get("eligibility_determined", False),
            "api_response": result.get("api_response")
        }
    
    def _extract_information_node(self, state: ConversationState) -> ConversationState:
        """Extract information from the latest user message"""
        start = time.perf_counter()
        logger.debug(f"[extract_information] INPUT state: {state}")
        user_messages = [m for m in state["messages"] if m["role"] == "user"]
        if not user_messages:
            return state
        
        latest_message = user_messages[-1]["content"]
        
        # Build extraction prompt
        current_info = {
            k: v for k, v in state.items() 
            if k in ["member_id", "date_of_birth", "procedure_code", "ndc_code", "service_type"]
        }
        
        extraction_prompt = INFORMATION_EXTRACTION_PROMPT.format(
            user_message=latest_message,
            current_state=json.dumps(current_info, indent=2)
        )
        
        # Call LLM for extraction
        messages = [
            SystemMessage(content="You are an information extraction expert. Extract data from messages and return valid JSON only."),
            HumanMessage(content=extraction_prompt)
        ]
        
        try:
            response = self.llm.invoke(messages)
            extracted_text = response.content.strip()
            
            # Clean up response to get JSON
            json_match = re.search(r'\{.*\}', extracted_text, re.DOTALL)
            if json_match:
                extracted_info = json.loads(json_match.group())
                state = update_state_from_extraction(state, extracted_info)
        except Exception as e:
            print(f"Extraction error: {e}")
        
        elapsed = time.perf_counter() - start
        logger.debug(f"[extract_information] OUTPUT state: {state} (took {elapsed:.2f}s)")
        return state
    
    def _resolve_codes_node(self, state: ConversationState) -> ConversationState:
        """
        Deterministic step: resolve procedure/medication names to API codes.
        Uses the mock API's own data so lookups are always consistent.
        """
        # Resolve procedure name → CPT code
        if state.get("procedure_name") and not state.get("procedure_code"):
            result = self.eligibility_api.resolve_procedure_code(state["procedure_name"])
            if result:
                state["procedure_code"] = result["code"]
                state["procedure_name"] = result["name"]  # normalise to canonical name
                if not state.get("service_type"):
                    state["service_type"] = "medical"

        # Resolve medication name → NDC code
        if state.get("medication_name") and not state.get("ndc_code"):
            result = self.eligibility_api.resolve_ndc_code(state["medication_name"])
            if result:
                state["ndc_code"] = result["code"]
                state["medication_name"] = result["name"]  # normalise
                if not state.get("service_type"):
                    state["service_type"] = "pharmacy"

        # Infer service_type from what we have, if still not set
        if not state.get("service_type"):
            if state.get("procedure_code") or state.get("procedure_name"):
                state["service_type"] = "medical"
            elif state.get("ndc_code") or state.get("medication_name"):
                state["service_type"] = "pharmacy"

        return state

    def _determine_next_action_node(self, state: ConversationState) -> ConversationState:
        """Determine what action to take next"""
        missing_fields = get_required_fields(state)
        state["missing_fields"] = missing_fields
        
        if state.get("api_called") and state.get("api_response"):
            # API already called, need to validate
            state["next_action"] = "complete"
        elif missing_fields:
            # Still missing required information
            state["next_action"] = "gather_info"
        else:
            # Have all required info, ready to call API
            state["next_action"] = "call_api"
        
        return state
    
    def _gather_more_info_node(self, state: ConversationState) -> ConversationState:
        """Generate a response asking for missing information"""
        missing = state.get("missing_fields", [])
        
        if not missing:
            return state
        
        # Build context for response generation
        context = {
            "missing_fields": missing,
            "user_query": state.get("user_query", ""),
            "collected_info": {k: v for k, v in state.items() if v and k in ["member_id", "date_of_birth", "procedure_name", "medication_name"]}
        }
        
        # Generate conversational prompt
        prompt = f"""You are helping a user check insurance eligibility.

User's original question: {state.get('user_query', 'insurance eligibility')}

Information you've collected so far:
{json.dumps(context['collected_info'], indent=2)}

You still need:
{', '.join([get_field_display_name(f) for f in missing[:2]])}

Generate a friendly, natural response asking for this information. 
- Don't ask for all missing fields at once
- Ask for 1-2 pieces of information at a time
- Be conversational and helpful
- If you've collected some info, acknowledge it briefly

Your response:"""
        
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]
        
        response = self.llm.invoke(messages)
        state = add_message(state, "assistant", response.content)
        
        return state
    
    def _call_api_node(self, state: ConversationState) -> ConversationState:
        """Call the eligibility API with a properly constructed payload."""
        start = time.perf_counter()
        logger.info(f"[call_api] Calling eligibility API with: {state.collected_fields}")
        # Last-chance code resolution (in case resolve_codes_node didn't run on a resumed state)
        if state.get("procedure_name") and not state.get("procedure_code"):
            result = self.eligibility_api.resolve_procedure_code(state["procedure_name"])
            if result:
                state["procedure_code"] = result["code"]
        if state.get("medication_name") and not state.get("ndc_code"):
            result = self.eligibility_api.resolve_ndc_code(state["medication_name"])
            if result:
                state["ndc_code"] = result["code"]

        # Determine effective service type for the API
        service_type = state.get("service_type", "general")
        if state.get("ndc_code"):
            service_type = "pharmacy"
        elif state.get("procedure_code"):
            service_type = "medical"

        # Build API request
        api_request = {
            "member_id": state.get("member_id"),
            "date_of_birth": state.get("date_of_birth"),
            "service_type": service_type,
            "service_date": state.get("service_date", datetime.now().strftime("%Y-%m-%d"))
        }

        # Add service-specific fields
        if state.get("procedure_code"):
            api_request["procedure_code"] = state["procedure_code"]
        if state.get("ndc_code"):
            api_request["ndc_code"] = state["ndc_code"]

        # Call the mock API
        try:
            api_response = self.eligibility_api.check_eligibility(api_request)
            state["api_response"] = api_response
            state["api_called"] = True
        except Exception as e:
            state["api_response"] = {
                "status": "error",
                "message": f"API call failed: {str(e)}"
            }
            state["api_called"] = True

        elapsed = time.perf_counter() - start
        logger.info(f"[call_api] API finished in {elapsed:.2f}s, response: {state.api_response}")
        return state
    
    def _validate_response_node(self, state: ConversationState) -> ConversationState:
        """Validate if API response answers the user's query"""
        api_response = state.get("api_response", {})
        
        validation_prompt = RESPONSE_VALIDATION_PROMPT.format(
            user_query=state.get("user_query", ""),
            api_response=json.dumps(api_response, indent=2),
            current_state=json.dumps({k: state.get(k) for k in ["member_id", "procedure_name", "medication_name"]}, indent=2)
        )
        
        messages = [
            SystemMessage(content="You are an expert at analyzing insurance eligibility responses."),
            HumanMessage(content=validation_prompt)
        ]
        
        try:
            response = self.llm.invoke(messages)
            validation_result = json.loads(re.search(r'\{.*\}', response.content, re.DOTALL).group())
            
            if validation_result.get("answers_query"):
                state["eligibility_determined"] = True
                state["next_action"] = "complete"
            else:
                state["eligibility_determined"] = False
                state["next_action"] = "gather_info"
                # Add follow-up question to messages
                if validation_result.get("follow_up_question"):
                    state = add_message(state, "assistant", validation_result["follow_up_question"])
        except Exception as e:
            print(f"Validation error: {e}")
            state["eligibility_determined"] = True
            state["next_action"] = "complete"
        
        return state
    
    def _generate_final_response_node(self, state: ConversationState) -> ConversationState:
        """Generate final response explaining eligibility result"""
        start = time.perf_counter()
        logger.info("[generate_final_response] Generating final message for caller")
        api_response = state.get("api_response", {})
        
        if not api_response:
            response_text = "I apologize, but I wasn't able to complete the eligibility check. Please try again."
        else:
            # Generate human-friendly explanation
            prompt = f"""Based on this insurance eligibility API response, create a clear, conversational explanation for the user.

API Response:
{json.dumps(api_response, indent=2)}

Original query: {state.get('user_query', '')}

Create a response that:
1. Clearly states if the patient is eligible or not
2. Explains any important conditions (copay, deductible, prior authorization)
3. Mentions specific cost information if available
4. Is friendly and easy to understand
5. Suggests next steps if applicable

Your response:"""
            
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt)
            ]
            
            response = self.llm.invoke(messages)
            response_text = response.content
        
        state = add_message(state, "assistant", response_text)
        elapsed = time.perf_counter() - start
        logger.info(f"[generate_final_response] Done in {elapsed:.2f}s; reply length={len(state.last_ai_message or '')}")
        return state
    
    def _route_next_action(self, state: ConversationState) -> str:
        """Route based on next_action"""
        return state.get("next_action", "gather_info")
    
    def _route_after_validation(self, state: ConversationState) -> str:
        """Route after API response validation"""
        if state.get("eligibility_determined"):
            return "complete"
        else:
            return "gather_more"

    async def process_user_input(self, transcript: str) -> dict:
        """
        Process user input and determine if ready for API call
        Returns dict with agent state and readiness for eligibility check
        """
        try:
            # Use the existing process_message method
            result = self.process_message(
                conversation_id="voice_call",
                user_message=transcript,
                current_state=getattr(self, '_current_state', None)
            )
            
            # Store state for next call
            self._current_state = result["state"]
            
            # Check if we have the minimum required fields for API
            state = result["state"]
            member_id = state.get("member_id")
            dob = state.get("date_of_birth")
            
            # According to MockEligibilityAPI, only member_id is truly required
            # DOB is optional for validation
            has_required = bool(member_id)
            
            collected_data = {
                "member_id": member_id,
                "date_of_birth": dob,
                "service_type": state.get("service_type", "general"),
                "procedure_code": state.get("procedure_code"),
                "ndc_code": state.get("ndc_code")
            }
            
            return {
                "ready_for_api_call": has_required and state.get("eligibility_determined", False),
                "collected_data": collected_data,
                "missing_fields": [] if has_required else ["member_id"],
                "agent_response": result["response"],
                "eligibility_determined": state.get("eligibility_determined", False)
            }
            
        except Exception as e:
            logger.error(f"❌ Error in process_user_input: {e}")
            return {
                "ready_for_api_call": False,
                "collected_data": {},
                "missing_fields": ["member_id"],
                "agent_response": "I'm sorry, could you please provide your member ID?",
                "eligibility_determined": False
            }
