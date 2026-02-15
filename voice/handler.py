"""
Unified Voice Handler
Integrates OpenAI Realtime API directly with LangGraph eligibility agent
"""
import json
import uuid
import asyncio
import websockets
from typing import Callable, Optional

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
    
    def __init__(self, call_sid: str, conversation_id: str, twilio_callback: Callable, openai_api_key: str):
        """Initialize the voice handler"""
        
        self.call_sid = call_sid
        self.conversation_id = conversation_id
        self.twilio_callback = twilio_callback
        self.openai_api_key = openai_api_key
        
        # Initialize components
        self.agent = EligibilityAgent(openai_api_key=openai_api_key)
        self.eligibility_api = MockEligibilityAPI()
        self.audio_converter = AudioConverter()
        
        # State tracking
        self.ws = None
        self.audio_buffer = []
        self.audio_chunks_received = 0
        self.audio_chunks_sent = 0
        self.first_audio_sent = False
        self._response_in_progress = False
        self._current_response_id = None
        self.running = True
        
        # OpenAI connection details
        self.api_url = f"wss://api.openai.com/v1/realtime?model={Config.OPENAI_REALTIME_MODEL}"
        self.headers = {
            "Authorization": f"Bearer {openai_api_key}",
            "OpenAI-Beta": "realtime=v1"
        }
        
        logger.info(f"🎙️  Voice handler initialized for call {call_sid}")
    
    async def connect_and_run(self):
        """Connect to OpenAI and start the event loop"""
        try:
            logger.info(f"🔌 Connecting to OpenAI Realtime at {self.api_url} for call {self.call_sid}")
            
            # Connect to OpenAI WebSocket with correct header parameter
            self.ws = await websockets.connect(
                self.api_url,
                extra_headers=self.headers,  # Changed from additional_headers to extra_headers
                ping_interval=20,
                ping_timeout=10
            )
            
            logger.info(f"✓ OpenAI connected for call {self.call_sid}")
            
            # Flush buffered audio
            if self.audio_buffer:
                logger.info(f"Flushing {len(self.audio_buffer)} buffered audio chunks to OpenAI")
                for audio_b64 in self.audio_buffer:
                    await self.send_audio_from_user(audio_b64)
                self.audio_buffer.clear()
            
            # Configure the session
            await self._configure_session()
            
            # Start event loop
            await self._event_loop()
            
        except Exception as e:
            logger.error(f"❌ Error in voice handler: {e}")
        finally:
            logger.info(f"🔌 OpenAI connection closed for call {self.call_sid}")

    async def _configure_session(self):
        """Configure the Realtime session with English-only and natural conversation"""
        
        eligibility_instructions = """
        You are a professional insurance eligibility verification agent. You MUST follow these rules:

        LANGUAGE REQUIREMENTS:
        - Speak ONLY in English - never respond in any other language
        - If a user speaks in another language, politely ask them to speak in English
        - Keep your English request short: "I can only help in English. Please speak English."

        CONVERSATION BEHAVIOR:
        - Use natural conversation flow - don't interrupt users
        - Wait for users to finish speaking completely before responding
        - Keep responses conversational but concise
        - If interrupted, stop speaking immediately and listen

        YOUR TASK:
        - Help verify insurance eligibility
        - Ask for member ID: "Hello! I can help check your insurance eligibility. What's your member ID?"
        - Be polite but efficient

        IMPORTANT: Always speak in English only, regardless of what language the user uses.
        """
        
        session_update = {
            "type": "session.update", 
            "session": {
                "model": Config.OPENAI_REALTIME_MODEL,
                "instructions": eligibility_instructions,
                "voice": "alloy",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.2,
                    "silence_duration_ms": 300,
                    "prefix_padding_ms": 200,
                    "create_response": True
                },
                "input_audio_transcription": {
                    "model": "gpt-4o-mini-transcribe",
                },
                "temperature": 0.6,
                "max_response_output_tokens": 300,  # Increased from 100 to allow complete responses
                "modalities": ["text", "audio"],
                "tools": []
            },
        }
        await self.ws.send(json.dumps(session_update))
        logger.info("✓ OpenAI session configured for English-only natural conversation")

    async def _event_loop(self):
        """Enhanced event loop with transcript logging"""
        try:
            async for message in self.ws:
                data = json.loads(message)
                event_type = data.get("type")
                
                # Log all events except audio buffer appends
                if event_type not in ["input_audio_buffer.append"]:
                    logger.debug(f"🔄 OpenAI event: {event_type}")
                
                if event_type == "input_audio_buffer.speech_started":
                    logger.info("🎤 User started speaking - canceling AI response")
                    if self._response_in_progress:
                        await self._cancel_current_response()
                
                elif event_type == "input_audio_buffer.speech_stopped":
                    logger.info("🎤 User stopped speaking")
                    
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    transcript = data.get("transcript", "")
                    logger.info(f"👤 User said: {transcript}")
                    
                    if self._is_non_english(transcript):
                        logger.info("🌐 Non-English detected - requesting English")
                        await self._request_english()
                    else:
                        logger.info("✅ English detected - processing normally")
                        await self._process_user_input_background(transcript)
                
                elif event_type == "response.created":
                    self._response_in_progress = True
                    response_data = data.get("response", {})
                    self._current_response_id = response_data.get("id")
                    max_tokens = response_data.get("max_output_tokens", "unknown")
                    logger.info(f"🤖 OpenAI response started: {self._current_response_id} (max_tokens: {max_tokens})")
                
                elif event_type == "response.done":
                    self._response_in_progress = False
                    response_data = data.get("response", {})
                    status = response_data.get("status")
                    status_details = response_data.get("status_details", {})
                    
                    # Log the actual transcript that was generated
                    output = response_data.get("output", [])
                    if output and len(output) > 0:
                        content = output[0].get("content", [])
                        if content and len(content) > 0:
                            transcript = content[0].get("transcript", "")
                            logger.info(f"🤖 Generated transcript: '{transcript}'")
                    
                    if status == "incomplete":
                        reason = status_details.get("reason", "unknown")
                        logger.warning(f"⚠️ Response incomplete due to: {reason}")
                    
                    usage = response_data.get("usage", {})
                    output_tokens = usage.get("output_tokens", 0)
                    logger.info(f"🤖 Response completed - Status: {status}, Tokens used: {output_tokens}")
                    self._current_response_id = None
                    
                    if hasattr(self, '_pending_eligibility_result'):
                        await self._deliver_pending_result()
                
                elif event_type == "response.audio.delta":
                    logger.debug("🔊 Received audio delta from OpenAI")
                    await self._handle_audio_delta(data)
                
                elif event_type == "response.audio.done":
                    logger.info("🔊 OpenAI finished sending audio")
                
                elif event_type == "error":
                    logger.error(f"❌ OpenAI error: {data}")
                    self._response_in_progress = False
                    
                elif event_type in ["session.created", "session.updated"]:
                    logger.info(f"✅ OpenAI session event: {event_type}")
                
                else:
                    logger.debug(f"🔄 Unhandled OpenAI event: {event_type}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info("🔌 OpenAI connection closed normally")
        except Exception as e:
            logger.error(f"💥 Event loop error: {e}")

    async def _process_user_input_background(self, transcript: str):
        """Process user input in background without interrupting conversation"""
        try:
            member_id = self._extract_member_id(transcript)
            
            if member_id:
                logger.info(f"📋 Extracted member ID: {member_id} - checking eligibility in background")
                await self._check_eligibility_and_store(member_id)
            
        except Exception as e:
            logger.error(f"❌ Error in background processing: {e}")

    async def _check_eligibility_and_store(self, member_id: str):
        """Check eligibility and store result without interrupting conversation"""
        try:
            request_data = {
                "member_id": member_id,
                "service_type": "general"
            }
            
            eligibility_result = self.eligibility_api.check_eligibility(request_data)
            logger.info(f"🏥 Eligibility API result: {eligibility_result}")
            
            if eligibility_result is None:
                eligibility_result = {
                    "status": "error",
                    "eligibility_status": "not_eligible",
                    "message": "Unable to verify insurance at this time"
                }
            
            is_eligible = eligibility_result.get("eligibility_status") == "eligible"
            
            self._pending_eligibility_result = {
                "member_id": member_id,
                "result": eligibility_result,
                "is_eligible": is_eligible
            }
            
            logger.info(f"📋 Stored eligibility result for {member_id}: {is_eligible}")
            
        except Exception as e:
            logger.error(f"❌ Error checking eligibility: {e}")

    async def _deliver_pending_result(self):
        """Deliver the pending eligibility result to the user"""
        try:
            if not hasattr(self, '_pending_eligibility_result'):
                return
                
            pending = self._pending_eligibility_result
            del self._pending_eligibility_result
            
            response_message = self._format_eligibility_response(pending["result"])
            logger.info(f"📤 Delivering eligibility result for {pending['member_id']}: {pending['is_eligible']}")
            
            await self._send_assistant_message(response_message)
            
        except Exception as e:
            logger.error(f"❌ Error delivering pending result: {e}")

    def _format_eligibility_response(self, eligibility_result: dict) -> str:
        """Format eligibility API response for user"""
        
        status = eligibility_result.get("eligibility_status")
        is_eligible = status == "eligible"
        
        if is_eligible:
            financial_info = eligibility_result.get("financial_info", {})
            copays = financial_info.get("copays", {})
            
            response = "Good news! Your insurance is active and eligible."
            
            if copays:
                primary_copay = copays.get("primary_care", 0)
                specialist_copay = copays.get("specialist", 0)
                if primary_copay or specialist_copay:
                    response += f" Your copays are ${primary_copay} for primary care and ${specialist_copay} for specialists."
            
            deductible_info = financial_info.get("deductible", {})
            if deductible_info:
                remaining = deductible_info.get("remaining", 0)
                if remaining > 0:
                    response += f" You have ${remaining} remaining on your deductible."
                else:
                    response += " Your deductible has been met."
                    
            response += " Is there anything else you'd like to know about your coverage?"
            
        else:
            reason = eligibility_result.get("message", "unknown reason")
            response = f"I'm sorry, but your insurance appears to be inactive or not eligible. {reason} I recommend contacting your insurance provider for more information."
            
        return response

    def _is_non_english(self, text: str) -> bool:
        """Detect if text is likely non-English with improved accuracy"""
        if not text or len(text.strip()) == 0:
            return False
            
        text_lower = text.lower().strip()
        
        spanish_indicators = [
            '¿', '¡',
            'hola', 'puedes', 'ver', 'allí', 'con', 'el', 'la', 'los', 'las',
            'es', 'está', 'están', 'anime', 'sí', 'no', 'que'
        ]
        
        english_words = [
            'hello', 'hi', 'is', 'there', 'anyone', 'online', 'help', 'me',
            'can', 'you', 'please', 'member', 'id', 'insurance', 'eligibility',
            'my', 'the', 'a', 'an', 'and', 'or', 'but', 'yes', 'no', 'side', 'that'
        ]
        
        spanish_count = sum(1 for indicator in spanish_indicators if indicator in text_lower)
        words = text_lower.split()
        english_count = sum(1 for word in words if word in english_words)
        
        if '¿' in text or '¡' in text:
            return True
            
        if spanish_count > 0 and spanish_count >= english_count:
            return True
            
        if len(words) > 0 and english_count >= len(words) * 0.5:
            return False
            
        return False

    def _extract_member_id(self, text: str) -> str:
        """Extract member ID from user text using regex patterns"""
        import re
        
        patterns = [
            r'\b[A-Z]{2,3}\d{6,12}\b',
            r'\b\d{8,15}\b',
            r'\b[A-Z]\d{7,12}\b',
            r'\b\d{2,4}[-\s]?\d{3,6}[-\s]?\d{3,6}\b'
        ]
        
        text_upper = text.upper()
        for pattern in patterns:
            match = re.search(pattern, text_upper)
            if match:
                member_id = re.sub(r'[-\s]', '', match.group())
                return member_id
        
        return None

    async def _request_english(self):
        """Send a shorter polite request for English with audio response"""
        try:
            if self._response_in_progress:
                logger.info("⏳ Waiting for current response to finish before requesting English")
                return
                
            # Shorter message to stay within token limits
            english_request = {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "I can only help in English. Please speak English."}]
                }
            }
            await self.ws.send(json.dumps(english_request))
            
            response_create = {"type": "response.create", "response": {"modalities": ["text", "audio"]}}
            await self.ws.send(json.dumps(response_create))
            
            logger.info("🌐 Requested user to speak in English with shorter response")
            
        except Exception as e:
            logger.error(f"❌ Error requesting English: {e}")

    async def _cancel_current_response(self):
        """Cancel the current AI response when user interrupts"""
        try:
            if self._current_response_id:
                cancel_message = {"type": "response.cancel"}
                await self.ws.send(json.dumps(cancel_message))
                logger.debug("🛑 Cancelled current response due to user interruption")
                
        except Exception as e:
            logger.error(f"❌ Error cancelling response: {e}")

    async def _send_assistant_message(self, message: str):
        """Send a message from assistant to user via OpenAI"""
        try:
            if not self.ws or self.ws.closed:
                logger.warning("⚠️ WebSocket closed, cannot send message")
                return
            
            if hasattr(self, '_response_in_progress') and self._response_in_progress:
                logger.info("⏳ Response in progress, queuing message for later")
                self._queued_message = message
                return
                
            conversation_item = {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "assistant", 
                    "content": [{"type": "text", "text": message}]
                }
            }
            await self.ws.send(json.dumps(conversation_item))
            
            response_create = {"type": "response.create"}
            await self.ws.send(json.dumps(response_create))
            
            logger.info(f"🤖 Sent eligibility response: {message[:100]}...")
            
        except Exception as e:
            logger.error(f"❌ Error sending assistant message: {e}")

    async def _handle_audio_delta(self, data: dict):
        """Handle audio delta from OpenAI and send to Twilio"""
        try:
            audio_b64 = data.get("delta", "")
            if audio_b64:
                if not self.twilio_callback:
                    logger.warning("⚠️ Twilio callback is None, cannot send audio")
                    return
                
                import base64
                pcm16_bytes = base64.b64decode(audio_b64)
                mulaw_bytes = AudioConverter.openai_to_twilio(pcm16_bytes)
                mulaw_b64 = base64.b64encode(mulaw_bytes).decode('utf-8')
                
                self.twilio_callback(mulaw_b64)
                
                self.audio_chunks_sent += 1
                
                if not self.first_audio_sent:
                    self.first_audio_sent = True
                    logger.info("📤 First audio chunk sent to Twilio")
                        
        except Exception as e:
            logger.error(f"❌ Error handling audio delta: {e}")

    async def send_audio_from_user(self, audio_b64: str):
        """Send user audio to OpenAI after converting from mulaw to PCM16."""
        if not self.ws or self.ws.closed:
            logger.debug("⚠️ WebSocket not ready, buffering audio")
            self.audio_buffer.append(audio_b64)
            return

        try:
            import base64
            mulaw_bytes = base64.b64decode(audio_b64)
            pcm16_bytes = AudioConverter.twilio_to_openai(mulaw_bytes)
            
            if len(pcm16_bytes) == 0:
                logger.warning("⚠️ Audio conversion returned empty bytes")
                return
                
            pcm16_b64 = base64.b64encode(pcm16_bytes).decode('utf-8')
            
            await self.ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": pcm16_b64,
            }))
            
            self.audio_chunks_received += 1
            
            if self.audio_chunks_received % 50 == 0:
                logger.info(f"📥 Sent {self.audio_chunks_received} audio chunks to OpenAI")
            
        except websockets.exceptions.ConnectionClosed:
            logger.warning("🔌 OpenAI connection closed while sending audio")
        except Exception as e:
            logger.error(f"❌ Error sending audio to OpenAI: {e}")

    def stop(self):
        """Stop the voice handler and close connections"""
        try:
            self.running = False
            if self.ws and not self.ws.closed:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.ws.close())
                else:
                    loop.run_until_complete(self.ws.close())
        except Exception as e:
            logger.error(f"Error stopping voice handler: {e}")
        
        logger.info(f"🔌 Voice handler stopped for call {self.call_sid}")
