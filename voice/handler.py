"""
Unified Voice Handler
Integrates OpenAI Realtime API directly with LangGraph eligibility agent
"""
import asyncio
import json
import base64
import websockets
from typing import Optional, Callable
import uuid

from utils.logger import setup_logger
from utils.audio_utils import AudioConverter
from config import Config
from agent.eligibility_agent import EligibilityAgent
from api.eligibility_api import MockEligibilityAPI

logger = setup_logger(__name__)


class VoiceHandler:
    """
    Unified handler that manages both OpenAI voice and LangGraph agent
    """
    
    def __init__(self, stream_sid: str, call_sid: str, twilio_callback: Callable, openai_api_key: str):
        """
        Initialize voice handler
        
        Args:
            stream_sid: Twilio stream SID
            call_sid: Twilio call SID
            twilio_callback: Callback function to send audio to Twilio
            openai_api_key: OpenAI API key
        """
        self.stream_sid = stream_sid
        self.call_sid = call_sid
        self.twilio_callback = twilio_callback
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.running = True
        self.conversation_id = str(uuid.uuid4())
        
        # Audio metrics
        self.audio_chunks_received = 0
        self.audio_chunks_sent = 0
        
        # Initialize agent
        self.agent = EligibilityAgent(openai_api_key=openai_api_key)
        self.eligibility_api = MockEligibilityAPI()
        
        # OpenAI API configuration
        self.api_url = f"{Config.OPENAI_REALTIME_URL}?model={Config.OPENAI_REALTIME_MODEL}"
        self.headers = {
            "Authorization": f"Bearer {openai_api_key}",
            "OpenAI-Beta": "realtime=v1"
        }
        
        logger.info(f"🎙️  Voice handler initialized for call {call_sid}")
    
    async def connect_and_run(self):
        """Connect to OpenAI and run the event loop"""
        try:
            async with websockets.connect(self.api_url, extra_headers=self.headers) as ws:
                self.ws = ws
                logger.info(f"✓ OpenAI connected for call {self.call_sid}")
                
                # Configure session
                await self._configure_session()
                
                # Listen for events
                await self._event_loop()
                
        except Exception as e:
            logger.error(f"❌ OpenAI connection error: {e}")
        finally:
            self.running = False
            logger.info(f"OpenAI connection closed for call {self.call_sid}")
    
    async def _configure_session(self):
        """Configure OpenAI session with tools and settings"""
        config = Config.get_openai_session_config()
        
        await self.ws.send(json.dumps({
            "type": "session.update",
            "session": config
        }))
        
        logger.info("✓ OpenAI session configured - waiting for caller...")
    
    async def _event_loop(self):
        """Main event loop for processing OpenAI events"""
        async for message in self.ws:
            if not self.running:
                break
            
            try:
                data = json.loads(message)
                event_type = data.get("type")
                
                # Route to appropriate handler
                if event_type == "response.audio.delta":
                    await self._handle_audio_delta(data)
                
                elif event_type == "response.audio_transcript.done":
                    await self._handle_ai_transcript(data)
                
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    await self._handle_user_transcript(data)
                
                elif event_type == "response.function_call_arguments.done":
                    await self._handle_function_call(data)
                
                elif event_type == "input_audio_buffer.speech_started":
                    logger.info(f"🎤 User started speaking")
                
                elif event_type == "input_audio_buffer.speech_stopped":
                    logger.info(f"🎤 User stopped speaking")
                
                elif event_type == "response.created":
                    logger.info(f"🤖 AI generating response...")
                
                elif event_type == "error":
                    logger.error(f"❌ OpenAI error: {data}")
            
            except Exception as e:
                logger.error(f"Error processing event: {e}")
    
    async def _handle_audio_delta(self, data: dict):
        """Handle audio chunk from OpenAI"""
        audio_b64 = data.get("delta")
        if not audio_b64:
            return
        
        self.audio_chunks_sent += 1
        if self.audio_chunks_sent == 1:
            logger.info("📤 Started sending audio to Twilio")
        
        # Decode PCM16 from OpenAI (16kHz)
        pcm_16khz = base64.b64decode(audio_b64)
        
        # Convert to Twilio format (mulaw 8kHz)
        mulaw = AudioConverter.openai_to_twilio(pcm_16khz)
        
        # Send to Twilio via callback
        mulaw_b64 = base64.b64encode(mulaw).decode()
        self.twilio_callback(mulaw_b64)
    
    async def _handle_ai_transcript(self, data: dict):
        """Handle completed AI transcript"""
        transcript = data.get("transcript", "")
        logger.info(f"🤖 AI: {transcript}")
    
    async def _handle_user_transcript(self, data: dict):
        """Handle completed user transcript"""
        transcript = data.get("transcript", "")
        logger.info(f"👤 User: {transcript}")
    
    async def _handle_function_call(self, data: dict):
        """
        Handle function call from OpenAI
        This is where eligibility checks happen using the LangGraph agent
        """
        call_id = data.get("call_id")
        name = data.get("name")
        arguments = json.loads(data.get("arguments", "{}"))
        
        logger.info(f"🔧 Function call: {name} with args: {arguments}")
        
        if name == "check_eligibility":
            # Extract arguments
            member_id = arguments.get("member_id")
            date_of_birth = arguments.get("date_of_birth")
            procedure_name = arguments.get("procedure_name")
            medication_name = arguments.get("medication_name")
            
            # Build eligibility check request
            request = {
                "member_id": member_id,
                "date_of_birth": date_of_birth
            }
            
            # Resolve procedure or medication name to codes
            if procedure_name:
                resolved = self.eligibility_api.resolve_procedure_code(procedure_name)
                if resolved:
                    request["procedure_code"] = resolved["code"]
                    request["service_type"] = "medical"
            
            if medication_name:
                resolved = self.eligibility_api.resolve_ndc_code(medication_name)
                if resolved:
                    request["ndc_code"] = resolved["code"]
                    request["service_type"] = "pharmacy"
            
            # Call eligibility API directly
            try:
                result = self.eligibility_api.check_eligibility(request)
                
                # Format result for natural speech
                formatted_result = self._format_eligibility_for_speech(result)
                
                # Send result back to OpenAI
                await self.ws.send(json.dumps({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps({
                            "success": True,
                            "message": formatted_result,
                            "raw_data": result
                        })
                    }
                }))
                
                # Trigger response generation
                await self.ws.send(json.dumps({
                    "type": "response.create"
                }))
                
                logger.info(f"✓ Eligibility check completed")
            
            except Exception as e:
                logger.error(f"❌ Eligibility check failed: {e}")
                
                # Send error back to OpenAI
                await self.ws.send(json.dumps({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps({
                            "success": False,
                            "message": "I encountered an error checking eligibility. Please try again."
                        })
                    }
                }))
                
                await self.ws.send(json.dumps({
                    "type": "response.create"
                }))
    
    def _format_eligibility_for_speech(self, api_response: dict) -> str:
        """
        Format eligibility API response into natural speech
        
        Args:
            api_response: Raw API response
        
        Returns:
            Formatted string for text-to-speech
        """
        if api_response.get("status") == "error":
            return api_response.get("message", "I encountered an error checking eligibility.")
        
        eligibility_status = api_response.get("eligibility_status", "unknown")
        
        if eligibility_status == "not_eligible":
            term_date = api_response.get("coverage_info", {}).get("termination_date", "an unknown date")
            return f"I'm sorry, but this member's coverage is not active. It was terminated on {term_date}. They should contact their insurance provider for more information."
        
        # Build response for active coverage
        response_parts = []
        
        # Basic eligibility
        member_info = api_response.get("member_info", {})
        response_parts.append(f"Great news! {member_info.get('name', 'The member')} is eligible and their coverage is active.")
        
        # Deductible info
        financial_info = api_response.get("financial_info", {})
        deductible = financial_info.get("deductible", {})
        if deductible:
            met = deductible.get("met", 0)
            total = deductible.get("individual", 0)
            remaining = deductible.get("remaining", 0)
            
            if remaining <= 0:
                response_parts.append("The deductible has been fully met.")
            else:
                response_parts.append(
                    f"The deductible is {met} dollars out of {total} dollars, "
                    f"with {remaining} dollars remaining."
                )
        
        # Service-specific info
        service_specific = api_response.get("service_specific", {})
        pharmacy_specific = api_response.get("pharmacy_specific", {})
        
        if service_specific:
            procedure_name = service_specific.get("procedure_name", "This service")
            covered = service_specific.get("covered", False)
            
            if covered:
                benefit = service_specific.get("benefit_details", {})
                responsibility = benefit.get("patient_responsibility", "")
                response_parts.append(f"{procedure_name} is covered. {responsibility}")
                
                if service_specific.get("requires_prior_authorization"):
                    response_parts.append("However, prior authorization is required before proceeding.")
            else:
                response_parts.append(f"However, {procedure_name} is not covered under this plan.")
        
        if pharmacy_specific:
            med_name = pharmacy_specific.get("medication_name", "This medication")
            covered = pharmacy_specific.get("covered", False)
            
            if covered:
                tier = pharmacy_specific.get("formulary_tier")
                copay = pharmacy_specific.get("copay_amount", 0)
                response_parts.append(
                    f"{med_name} is covered as a tier {tier} medication "
                    f"with a copay of {copay} dollars."
                )
                
                if pharmacy_specific.get("requires_prior_authorization"):
                    response_parts.append("Prior authorization is required for this medication.")
            else:
                response_parts.append(f"However, {med_name} is not covered under the plan's formulary.")
        
        return " ".join(response_parts)
    
    async def send_audio_from_user(self, audio_b64: str):
        """
        Send audio from user (Twilio) to OpenAI
        
        Args:
            audio_b64: Base64 encoded audio from Twilio (mulaw 8kHz)
        """
        if not self.ws or not self.running:
            return
        
        self.audio_chunks_received += 1
        if self.audio_chunks_received == 1:
            logger.info("📥 Started receiving audio from Twilio")
        
        try:
            await self.ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": audio_b64
            }))
        except Exception as e:
            logger.error(f"Error sending audio to OpenAI: {e}")
    
    def stop(self):
        """Stop the handler"""
        self.running = False
        logger.info(f"📊 Call ended - Received {self.audio_chunks_received}, Sent {self.audio_chunks_sent} chunks")
