"""
Unified Voice Handler
Integrates OpenAI Realtime API directly with LangGraph eligibility agent
"""
import json
import asyncio
import websockets
import base64
from typing import Callable, Optional
import re

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
        
        # Enhanced state tracking
        self.ws = None
        self.audio_buffer = []
        self.audio_chunks_received = 0
        self.audio_chunks_sent = 0
        self.first_audio_sent = False
        self._response_in_progress = False
        self._current_response_id = None
        self.running = True
        self._handler_event_loop = None  # Store the async event loop reference
        
        # Conversation state - Fixed workflow tracking
        self.member_id = None
        self.date_of_birth = None
        self.full_name = None
        self.eligibility_data = None
        self.verification_step = "member_id"  # member_id -> verification -> complete
        self._verification_attempts = 0
        self._max_verification_attempts = 3
        
        # OpenAI connection details
        self.api_url = f"wss://api.openai.com/v1/realtime?model={Config.OPENAI_REALTIME_MODEL}"
        self.headers = {
            "Authorization": f"Bearer {openai_api_key}",
            "OpenAI-Beta": "realtime=v1"
        }
        
        logger.info(f"🎙️  Voice handler initialized for call {call_sid}")

    def handle_audio(self, audio_data: str):
        """Handle incoming audio from Twilio"""
        try:
            if not self.ws or self.ws.closed:
                logger.warning("⚠️ WebSocket closed, cannot send audio")
                return
                
            # Decode incoming Twilio audio (μLaw 8kHz)
            mulaw_audio = base64.b64decode(audio_data)
            
            # Convert to OpenAI format (PCM16 24kHz)
            pcm_audio = self.audio_converter.twilio_to_openai(mulaw_audio)
            
            # Encode for OpenAI
            pcm_b64 = base64.b64encode(pcm_audio).decode('utf-8')
            
            # Send to OpenAI - use the event loop from the handler
            audio_message = {
                "type": "input_audio_buffer.append",
                "audio": pcm_b64
            }
            
            # Schedule the coroutine in the handler's event loop
            if self._handler_event_loop and not self._handler_event_loop.is_closed():
                asyncio.run_coroutine_threadsafe(
                    self.ws.send(json.dumps(audio_message)), 
                    self._handler_event_loop
                )
                self.audio_chunks_received += 1
                
                # if self.audio_chunks_received % 5000 == 0:
                #     logger.info(f"📥 Processed {self.audio_chunks_received} audio chunks from Twilio")
            else:
                logger.warning("⚠️ No event loop available for audio processing")
                
        except Exception as e:
            logger.error(f"❌ Error handling audio: {e}")

    async def _configure_session(self):
        """Configure the Realtime session with improved VAD settings"""
        
        eligibility_instructions = """You are an insurance eligibility verification agent.

CRITICAL WORKFLOW - Follow this EXACT sequence:
1. FIRST: Say exactly "Hello! I can help check your insurance eligibility. What's your member ID?" and WAIT
2. AFTER getting member ID: Say exactly the message provided by the system and WAIT  
3. AFTER getting verification info: Follow system instructions exactly

IMPORTANT RULES:
- Speak ONLY in English
- When given a specific message to say, read it WORD FOR WORD - never paraphrase, summarize, or change the wording
- If instructed to read a message exactly, you MUST speak every word as written
- Keep natural pauses and intonation but use the exact words provided
- WAIT for complete user responses - don't interrupt
- Stay focused on the eligibility verification task only

You must follow instructions to read messages exactly as written without any modification."""
        
        session_update = {
            "type": "session.update", 
            "session": {
                "model": Config.OPENAI_REALTIME_MODEL,
                "instructions": eligibility_instructions,
                "voice": "alloy",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1",
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.3,              # Lowered from 0.5 for better sensitivity
                    "silence_duration_ms": 500,    # Reduced from 800ms for faster detection
                    "prefix_padding_ms": 300,
                    "create_response": True
                },
                "temperature": 0.6,
                "max_response_output_tokens": 250,
                "modalities": ["text", "audio"],
                "tools": []
            },
        }
        await self.ws.send(json.dumps(session_update))
        logger.info("✓ OpenAI session configured with more sensitive VAD settings")
        
    async def _cancel_current_response(self):
        """Cancel current OpenAI response with retry logic"""
        try:
            if self._response_in_progress and self._current_response_id:
                cancel_message = {"type": "response.cancel"}
                await self.ws.send(json.dumps(cancel_message))
                logger.info("🛑 Response cancellation sent")
                self._response_in_progress = False
                # Give it time to cancel
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.debug(f"Response cancellation error (often expected): {e}")

    async def _send_assistant_message(self, message: str):
        """Send assistant message with improved error handling"""
        try:
            if not self.ws or self.ws.closed:
                logger.warning("⚠️ WebSocket closed, cannot send message")
                return
                
            # Cancel any ongoing response first
            if self._response_in_progress:
                logger.info("🛑 Canceling ongoing response to send message")
                await self._cancel_current_response()
                await asyncio.sleep(0.3)
                
            # Create a conversation item with the exact message we want
            conversation_item = {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "assistant", 
                    "content": [{"type": "text", "text": message}]
                }
            }
            await self.ws.send(json.dumps(conversation_item))
            
            # Wait before creating response
            await asyncio.sleep(0.2)
            
            # Create response with specific instruction to read exactly as written
            response_create = {
                "type": "response.create",
                "response": {
                    "modalities": ["text", "audio"],
                    "instructions": f"Read this message exactly as written, word for word: '{message}'. Do not paraphrase, change, or add anything."
                }
            }
            await self.ws.send(json.dumps(response_create))
            
            logger.info(f"🤖 Sent message: {message}")
            
        except Exception as e:
            logger.error(f"❌ Error sending assistant message: {e}")

    def _is_user_checking_connection(self, transcript: str) -> bool:
        """Check if user is asking if we're there or similar"""
        check_phrases = [
            "are you there", "hello", "can you hear me", "are you listening",
            "did you get that", "are you still there", "hello?", "hey",
            "can you hear", "are you working"
        ]
        
        transcript_lower = transcript.lower().strip()
        return any(phrase in transcript_lower for phrase in check_phrases)
    
    async def _trigger_initial_greeting(self):
        """Trigger the initial greeting response with correct format"""
        try:
            response_create = {
                "type": "response.create"
            }
            await self.ws.send(json.dumps(response_create))
            
            logger.info("🎙️ Triggered initial greeting response")
            
        except Exception as e:
            logger.error(f"❌ Error triggering initial greeting: {e}")

    async def connect_and_run(self):
        """Connect to OpenAI and run the voice handler"""
        try:
            # Store reference to the current event loop
            self._handler_event_loop = asyncio.get_event_loop()
            
            logger.info(f"🔌 Connecting to OpenAI Realtime at {self.api_url} for call {self.call_sid}")
            
            self.ws = await websockets.connect(
                self.api_url,
                extra_headers=self.headers,
                ping_interval=None,
                ping_timeout=None
            )
            
            logger.info(f"✓ OpenAI connected for call {self.call_sid}")
            
            # Configure session and send greeting
            await self._configure_session()
            
            # Start event processing
            await self._process_events()
            
        except Exception as e:
            logger.error(f"❌ OpenAI connection error: {e}")
        finally:
            self.running = False
            if self.ws and not self.ws.closed:
                await self.ws.close()
                logger.info(f"🔌 OpenAI connection closed for call {self.call_sid}")

    async def _process_events(self):
        """Process OpenAI events with better VAD handling"""
        session_ready = False
        last_speech_start = None
        
        try:
            async for message in self.ws:
                if not self.running:
                    break
                    
                try:
                    data = json.loads(message)
                    event_type = data.get("type")
                    
                    if event_type == "session.created":
                        logger.info("✅ OpenAI session event: session.created")
                        
                    elif event_type == "session.updated":
                        logger.info("✅ OpenAI session event: session.updated")
                        if not session_ready:
                            session_ready = True
                            # Trigger the initial greeting after session is ready
                            await asyncio.sleep(0.3)
                            await self._trigger_initial_greeting()
                            
                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        transcript = data.get("transcript", "").strip()
                        last_speech_start = None  # Reset timeout
                        if transcript:
                            logger.info(f"👤 User said: {transcript}")
                            
                            if self._is_english(transcript):
                                logger.info("✅ English detected - processing normally")
                                await self._process_user_input_background(transcript)
                            else:
                                logger.warning(f"⚠️ Non-English detected: {transcript}")
                                await self._send_english_only_message()
                        else:
                            logger.debug("👤 User spoke but no transcript captured")
                                
                    elif event_type == "conversation.item.input_audio_transcription.failed":
                        logger.warning("⚠️ Audio transcription failed")
                            
                    elif event_type == "input_audio_buffer.speech_started":
                        logger.info("🎤 User started speaking")
                        last_speech_start = asyncio.get_event_loop().time()
                        # Cancel any ongoing response when user starts speaking
                        if self._response_in_progress:
                            await self._cancel_current_response()
                            
                    elif event_type == "input_audio_buffer.speech_stopped":
                        logger.info("🎤 User stopped speaking")
                        last_speech_start = None
                        # Only commit if we're not in the middle of processing a response
                        if not self._response_in_progress:
                            try:
                                commit_message = {"type": "input_audio_buffer.commit"}
                                await self.ws.send(json.dumps(commit_message))
                                logger.debug("📤 Audio buffer committed for processing")
                            except Exception as e:
                                logger.debug(f"Audio buffer commit error (often expected): {e}")
                        
                    elif event_type == "input_audio_buffer.committed":
                        logger.debug("✅ Audio buffer committed - transcript should follow")
                        
                    elif event_type == "response.created":
                        self._response_in_progress = True
                        response_data = data.get("response", {})
                        self._current_response_id = response_data.get("id")
                        logger.info(f"🤖 OpenAI response started: {self._current_response_id}")
                        
                    elif event_type == "response.done":
                        self._response_in_progress = False
                        response = data.get("response", {})
                        if response:
                            status = response.get("status", "unknown")
                            usage = response.get("usage", {})
                            tokens_used = usage.get("output_tokens", 0)
                            logger.info(f"🤖 Response completed - Status: {status}, Tokens: {tokens_used}")
                        self._current_response_id = None
                        
                    elif event_type == "response.audio.delta":
                        await self._handle_audio_delta(data)
                        
                    elif event_type == "response.audio.done":
                        logger.info("🔊 OpenAI finished sending audio")
                        
                    elif event_type == "response.audio_transcript.done":
                        transcript = data.get("transcript", "")
                        if transcript:
                            logger.info(f"🤖 AI said: '{transcript}'")
                            
                    elif event_type == "error":
                        error_details = data.get("error", {})
                        error_type = error_details.get("type", "unknown")
                        error_message = error_details.get("message", "No message")
                        
                        # Don't log audio buffer errors and cancellation errors as they're expected
                        if ("buffer too small" in error_message.lower() or 
                            "cancellation failed" in error_message.lower()):
                            logger.debug(f"Expected error: {error_message}")
                        else:
                            logger.error(f"❌ OpenAI error ({error_type}): {error_message}")
                            
                    elif event_type == "rate_limits.updated":
                        logger.debug("🔄 Rate limits updated")
                        
                    else:
                        logger.debug(f"🔍 Unhandled event: {event_type}")
                        
                except (json.JSONDecodeError, KeyError, AttributeError) as e:
                    logger.warning(f"⚠️ Error processing OpenAI event: {e}")
                except Exception as e:
                    logger.error(f"💥 Event processing error: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info("🔌 OpenAI connection closed")
        except Exception as e:
            logger.error(f"💥 Event loop error: {e}")

    async def _handle_audio_delta(self, data):
        """Handle audio response from OpenAI"""
        try:
            delta = data.get("delta", "")
            if not delta:
                return
            
            # Convert OpenAI PCM16 to Twilio mulaw
            pcm_audio = base64.b64decode(delta)
            mulaw_audio = self.audio_converter.openai_to_twilio(pcm_audio)
            mulaw_b64 = base64.b64encode(mulaw_audio).decode('utf-8')
            
            # Send to Twilio
            if self.twilio_callback:
                self.twilio_callback(mulaw_b64)
            
            self.audio_chunks_sent += 1
            if not self.first_audio_sent:
                self.first_audio_sent = True
                logger.info("📤 First audio chunk received from OpenAI")
                
        except Exception as e:
            logger.error(f"❌ Error handling audio delta: {e}")

    def _is_english(self, text: str) -> bool:
        """Check if text is primarily English"""
        # Simple heuristic: check for common English words and characters
        english_indicators = ['the', 'and', 'is', 'a', 'to', 'my', 'it', 'of', 'in']
        text_lower = text.lower()
        
        # Check for English indicators
        english_score = sum(1 for word in english_indicators if word in text_lower)
        
        # Check character composition (basic Latin characters)
        latin_chars = sum(1 for c in text if c.isascii() and (c.isalpha() or c.isspace()))
        total_chars = len([c for c in text if c.isalpha() or c.isspace()])
        
        if total_chars == 0:
            return True  # Assume English for non-text input
            
        latin_ratio = latin_chars / total_chars if total_chars > 0 else 0
        
        # Consider it English if it has English indicators or high Latin character ratio
        return english_score > 0 or latin_ratio > 0.8

    async def _process_user_input_background(self, transcript: str):
        """Enhanced processing with better context awareness"""
        try:
            logger.info(f"🔍 Processing transcript in step '{self.verification_step}': '{transcript}'")
            
            # Check if user is asking unrelated questions
            if self._is_unrelated_question(transcript) and self.verification_step == "member_id":
                await self._redirect_to_member_id()
                return
            
            if self.verification_step == "member_id":
                await self._handle_member_id_step(transcript)
            elif self.verification_step == "verification":
                await self._handle_verification_step(transcript)
            elif self.verification_step == "complete":
                logger.info("📋 Eligibility already provided - handling follow-up questions")
                # Handle follow-up questions about coverage
                await self._handle_follow_up_questions(transcript)
                
        except Exception as e:
            logger.error(f"❌ Error in background processing: {e}")
            import traceback
            logger.error(f"Stack trace: {traceback.format_exc()}")

    async def _handle_follow_up_questions(self, transcript: str):
        """Handle follow-up questions after eligibility is provided"""
        try:
            # Simple follow-up handling
            if any(word in transcript.lower() for word in ["something", "result", "details", "info", "information"]):
                # User is asking if we have results - but we already verified successfully
                message = "I've already verified your eligibility. Your coverage is active. Do you have any specific questions about your benefits?"
                await self._send_assistant_message(message)
            else:
                # General follow-up
                message = "I can help with questions about your coverage, copays, deductible, or benefits. What would you like to know?"
                await self._send_assistant_message(message)
                
        except Exception as e:
            logger.error(f"❌ Error handling follow-up questions: {e}")

    def _is_unrelated_question(self, transcript: str) -> bool:
        """Check if the transcript contains unrelated questions"""
        unrelated_keywords = [
            "student", "students", "school", "university", "college",
            "weather", "time", "date", "news", "sports",
            "help", "what can you do", "who are you"
        ]
        
        transcript_lower = transcript.lower()
        question_words = ["do you", "can you", "what", "when", "where", "why", "how", "ground"]
        
        # Check if it's a question about unrelated topics
        has_question_word = any(qw in transcript_lower for qw in question_words)
        has_unrelated_keyword = any(kw in transcript_lower for kw in unrelated_keywords)
        
        return has_question_word and has_unrelated_keyword

    async def _redirect_to_member_id(self):
        """Redirect user back to providing member ID"""
        message = "I can help with insurance eligibility. First, I need your member ID please."
        await self._send_assistant_message(message)

    async def _handle_member_id_step(self, transcript: str):
        """Fixed member ID handling with better logging"""
        try:
            logger.info(f"🎯 Handle member ID step - input: '{transcript}'")
            
            member_id = self._extract_member_id(transcript)
            
            if member_id:
                logger.info(f"📋 Successfully extracted member ID: {member_id}")
                self.member_id = member_id
                
                # Check database for member
                request_data = {"member_id": member_id, "service_type": "general"}
                eligibility_result = self.eligibility_api.check_eligibility(request_data)
                
                if eligibility_result.get("status") == "success":
                    self.eligibility_data = eligibility_result
                    member_info = eligibility_result.get("member_info", {})
                    
                    logger.info(f"✅ Member {member_id} found in database")
                    logger.info(f"   Name: {member_info.get('name')}")
                    logger.info(f"   DOB: {member_info.get('dob')}")
                    
                    # Move to verification step
                    self.verification_step = "verification"
                    logger.info("🔄 Moving to verification step")
                    
                    # Send confirmation message
                    await self._send_verification_request()
                    
                else:
                    logger.warning(f"❌ Member ID {member_id} not found in database")
                    await self._send_member_not_found_message(member_id)
                    
            else:
                logger.warning(f"⚠️ Could not extract member ID from: '{transcript}'")
                await self._ask_for_member_id_clarification()
                
        except Exception as e:
            logger.error(f"❌ Error in member ID step: {e}")
            import traceback
            logger.error(f"Stack trace: {traceback.format_exc()}")

    def _extract_member_id(self, text: str) -> Optional[str]:
        """Improved member ID extraction with better pattern matching"""
        import re
        
        logger.info(f"🔍 Attempting to extract member ID from: '{text}'")
        
        # Clean up the text but preserve structure
        text_upper = text.upper().strip()
        
        # More comprehensive patterns - prioritize complete member IDs
        patterns = [
            # Complete member ID patterns (letters + numbers together or with space)
            r'\b([A-Z]{2}\s*\d{6})\b',        # MB123456 or MB 123456
            r'\b(MB\s*\d{6})\b',              # MB123456 or MB 123456 specifically
            r'\b([A-Z]\s*\d{7})\b',           # Single letter + 7 digits
            # Speech variations
            r'(?:member\s+id\s+is\s*|id\s+is\s*|it\'s\s+)([A-Z]{1,2}\s*\d{6,8})',
            r'(?:the\s+)?(?:member\s+)?(?:id\s+)?(?:is\s+)?([A-Z]{2}\s*\d{6})',
            # Fallback patterns
            r'([A-Z]{1,3}\s*\d{6,8})',
            # Numbers only as last resort (6-8 digits) - but only if no letters present
            r'\b(\d{6,8})\b',
        ]
        
        for i, pattern in enumerate(patterns):
            matches = re.findall(pattern, text_upper)
            for match in matches:
                # Clean the match (remove spaces)
                candidate = re.sub(r'\s+', '', match.strip())
                
                # Validate the candidate
                if len(candidate) >= 6 and len(candidate) <= 10:
                    # Must have at least some digits
                    if any(c.isdigit() for c in candidate):
                        # For the last pattern (numbers only), be more restrictive
                        if i == len(patterns) - 1:  # Numbers only pattern
                            # Only accept if no letters were mentioned in the text
                            if not re.search(r'[A-Z]{2,}', text_upper):
                                logger.info(f"✅ Found member ID '{candidate}' using pattern {i+1}")
                                return candidate
                        else:
                            logger.info(f"✅ Found member ID '{candidate}' using pattern {i+1}")
                            return candidate
        
        logger.warning(f"❌ No member ID found in: '{text}'")
        return None

    async def _send_verification_request(self):
        """Send request for verification information using exact speech"""
        message = "Thank you. For verification, please confirm your full name and date of birth."
        
        # Try the exact speech method
        await self._send_exact_speech(message)

    async def _send_exact_speech(self, message: str):
        """Alternative method to force exact speech using correct OpenAI format"""
        try:
            if not self.ws or self.ws.closed:
                logger.warning("⚠️ WebSocket closed, cannot send message")
                return
                
            # Cancel any ongoing response first
            if self._response_in_progress:
                logger.info("🛑 Canceling ongoing response to send exact speech")
                await self._cancel_current_response()
                await asyncio.sleep(0.5)
                
            # Add the assistant message with correct format
            conversation_item = {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "assistant", 
                    "content": [{"type": "text", "text": message}]
                }
            }
            await self.ws.send(json.dumps(conversation_item))
            
            await asyncio.sleep(0.2)
            
            # Create response with correct modalities and stronger instructions
            response_create = {
                "type": "response.create", 
                "response": {
                    "modalities": ["text", "audio"],
                    "instructions": f"You must say exactly this message word for word: '{message}'. Do not change, add, or remove any words. Read it exactly as written."
                }
            }
            await self.ws.send(json.dumps(response_create))
            
            logger.info(f"🤖 Sent exact speech command: {message}")
            
        except Exception as e:
            logger.error(f"❌ Error sending exact speech: {e}")

    async def _ask_for_missing_verification_info(self):
        """Ask for missing verification information using exact speech"""
        if not self.full_name and not self.date_of_birth:
            message = "I'm here! I still need both your full name and your date of birth to verify your identity. Please go ahead."
        elif not self.full_name:
            message = "I need your full name please. What's your complete name?"
        else:
            message = "I need your date of birth please. What's your birth date?"
        
        await self._send_assistant_message(message)

    async def _ask_for_member_id_clarification(self):
        """Ask user to repeat member ID using exact speech"""
        message = "I didn't catch your member ID. Could you please repeat it? It's usually letters and numbers like MB123456."
        await self._send_exact_speech(message)

    async def _send_member_not_found_message(self, member_id: str):
        """Send message when member ID is not found using exact speech"""
        message = f"I'm sorry, I couldn't find a member with ID {member_id} in our system. Please check your member ID and try again."
        await self._send_exact_speech(message)

    async def _redirect_to_member_id(self):
        """Redirect user back to providing member ID using exact speech"""
        message = "I can help with insurance eligibility. First, I need your member ID please."
        await self._send_exact_speech(message)

    async def _handle_verification_step(self, transcript: str):
        """Enhanced verification step with better name/DOB extraction"""
        try:
            logger.info(f"🔍 Verification step - analyzing: '{transcript}'")
            
            # Extract name if not already captured
            if not self.full_name:
                extracted_name = self._extract_name(transcript)
                if extracted_name:
                    self.full_name = extracted_name.lower().strip()
                    logger.info(f"📝 Extracted name: '{self.full_name}'")
            
            # Extract DOB if not already captured  
            if not self.date_of_birth:
                extracted_dob = self._extract_date_of_birth(transcript)
                if extracted_dob:
                    self.date_of_birth = extracted_dob
                    logger.info(f"📅 Extracted DOB: '{self.date_of_birth}'")
            
            # Check verification status
            logger.info(f"Current verification state - Name: {bool(self.full_name)}, DOB: {bool(self.date_of_birth)}")
            
            # If we have both pieces of information, verify
            if self.full_name and self.date_of_birth and self.eligibility_data:
                logger.info("🔍 Have both name and DOB - starting verification")
                await self._verify_member_details()
            else:
                logger.info("⚠️ Still missing verification information")
                await self._ask_for_missing_verification_info()
                
        except Exception as e:
            logger.error(f"❌ Error in verification step: {e}")

    def _extract_name(self, text: str) -> Optional[str]:
        """Enhanced name extraction"""
        import re
        
        logger.info(f"📝 Trying to extract name from: '{text}'")
        
        # Don't extract names from questions or connection checks
        question_words = {'do', 'you', 'have', 'any', 'what', 'where', 'when', 'how', 'why', 'can', 'could', 'would', 'should', 'are', 'is', 'okay'}
        words_lower = set(word.lower().strip('.,!?') for word in text.split())
        
        # If it's clearly a question or acknowledgment, don't extract names
        if len(words_lower.intersection(question_words)) > 0:
            logger.info("❌ Detected question/acknowledgment - not extracting name")
            return None
        
        # Common name patterns - more comprehensive and specific
        patterns = [
            # Direct statements with clear name indicators
            r"(?:my name is|i am|name is|i'm|call me|it's|this is)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)",
            r"(?:full name is|name)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)",
            # Name at beginning of sentence (two proper nouns)
            r"^([A-Z][a-z]{2,}\s+[A-Z][a-z]{2,})\b",
            # Name with common connectors, but stop at common non-name words
            r"(?:name|called)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)(?:\s+(?:and|the|is|was|on|of|at|in|for))",
            # Simple two-word names anywhere, but exclude if followed by common non-name words
            r"\b([A-Z][a-z]{2,}\s+[A-Z][a-z]{2,})(?=\s+(?:and|the|is|was|on|of|at|in|for|date|birth|$))",
        ]
        
        text_clean = text.strip()
        
        for i, pattern in enumerate(patterns):
            match = re.search(pattern, text_clean, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                
                # Clean up the name (remove extra words and validate)
                name_parts = []
                for part in name.split():
                    # Only include actual name parts (alphabetic, reasonable length)
                    # Exclude common non-name words that might be captured
                    if (part.isalpha() and 
                        len(part) > 1 and 
                        part.lower() not in ['and', 'the', 'a', 'an', 'is', 'was', 'my', 'me', 'it', 'this', 'date', 'birth', 'of']):
                        name_parts.append(part.title())  # Proper case
                        
                if len(name_parts) >= 2:
                    result = ' '.join(name_parts[:2])  # Only take first 2 name parts
                    logger.info(f"✅ Extracted name using pattern {i+1}: '{result}'")
                    return result
        
        logger.warning(f"❌ No valid name found in: '{text}'")
        return None

    def _extract_date_of_birth(self, text: str) -> Optional[str]:
        """Enhanced DOB extraction with better patterns"""
        import re
        
        logger.info(f"📅 Trying to extract DOB from: '{text}'")
        
        # Common date patterns
        patterns = [
            # March 1985, March 15 1985, 15th March 1985
            r'(\d{1,2})(?:st|nd|rd|th)?\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s*,?\s*(\d{4})',
            r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})',
            r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})',  # Month Year only
            # MM/DD/YYYY, DD/MM/YYYY
            r'(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})',
            # MM/DD/YY
            r'(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2})',
            # YYYY-MM-DD
            r'(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})',
        ]
        
        text_lower = text.lower().replace(',', ' ')
        
        # Month name mappings
        month_map = {
            'january': '01', 'february': '02', 'march': '03', 'april': '04',
            'may': '05', 'june': '06', 'july': '07', 'august': '08',
            'september': '09', 'october': '10', 'november': '11', 'december': '12'
        }
        
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                try:
                    groups = match.groups()
                    
                    if len(groups) == 2 and groups[0] in month_map:
                        # Month Year only (like "March 1985")
                        month_name, year = groups
                        month = month_map[month_name]
                        result = f"{year}-{month}-01"  # Default to 1st of the month
                        logger.info(f"✅ Extracted DOB (month/year): {result}")
                        return result
                        
                    elif len(groups) == 3:
                        if groups[0].isdigit() and groups[1] in month_map:
                            # Day Month Year
                            day, month_name, year = groups
                            month = month_map[month_name]
                            result = f"{year}-{month:0>2}-{day:0>2}"
                            logger.info(f"✅ Extracted DOB: {result}")
                            return result
                        elif groups[1].isdigit() and groups[0] in month_map:
                            # Month Day Year  
                            month_name, day, year = groups
                            month = month_map[month_name]
                            result = f"{year}-{month:0>2}-{day:0>2}"
                            logger.info(f"✅ Extracted DOB: {result}")
                            return result
                        elif all(g.isdigit() for g in groups):
                            # All numeric
                            part1, part2, part3 = groups
                            if len(part1) == 4:  # YYYY-MM-DD
                                result = f"{part1}-{part2:0>2}-{part3:0>2}"
                            elif len(part3) == 4:  # MM/DD/YYYY
                                result = f"{part3}-{part1:0>2}-{part2:0>2}"
                            elif len(part3) == 2:  # MM/DD/YY
                                year = int(part3)
                                if year < 50:
                                    year += 2000
                                else:
                                    year += 1900
                                result = f"{year}-{part1:0>2}-{part2:0>2}"
                            else:
                                continue
                            
                            logger.info(f"✅ Extracted DOB: {result}")
                            return result
                            
                except Exception as e:
                    logger.debug(f"Date parsing error: {e}")
                    continue
        
        logger.warning(f"❌ No DOB found in: '{text}'")
        return None

    async def _verify_member_details(self):
        """Verify member details with better success messaging"""
        try:
            if not self.eligibility_data:
                logger.error("❌ No eligibility data to verify against")
                return
                
            member_info = self.eligibility_data.get("member_info", {})
            expected_name = member_info.get("name", "").lower().strip()
            expected_dob = member_info.get("dob", "")
            
            # Name matching - more flexible
            name_match = self._names_match(self.full_name, expected_name)
            dob_match = self.date_of_birth == expected_dob
            
            logger.info(f"🔍 Verification results:")
            logger.info(f"   Name match: {name_match} ('{self.full_name}' vs '{expected_name}')")
            logger.info(f"   DOB match: {dob_match} ('{self.date_of_birth}' vs '{expected_dob}')")
            
            if name_match and dob_match:
                logger.info("✅ Verification successful - sending eligibility info")
                self.verification_step = "complete"
                
                # Send verification success message first
                success_message = "Perfect! Your identity has been verified. Here are your eligibility details."
                await self._send_assistant_message(success_message)
                
                # Wait a moment, then send the detailed eligibility info
                await asyncio.sleep(2.0)
                eligibility_response = self._format_eligibility_response(self.eligibility_data)
                await self._send_assistant_message(eligibility_response)
                
            else:
                self._verification_attempts += 1
                logger.warning(f"❌ Verification failed (attempt {self._verification_attempts})")
                
                if self._verification_attempts >= self._max_verification_attempts:
                    logger.warning("❌ Max verification attempts reached")
                    await self._send_max_attempts_message()
                else:
                    # Reset failed fields for retry
                    if not name_match:
                        self.full_name = None
                    if not dob_match:
                        self.date_of_birth = None
                    
                    await self._send_verification_failed_message(name_match, dob_match)
                
        except Exception as e:
            logger.error(f"❌ Error in verification: {e}")
            import traceback
            logger.error(f"Stack trace: {traceback.format_exc()}")

    def _names_match(self, provided_name: str, expected_name: str) -> bool:
        """Flexible name matching"""
        if not provided_name or not expected_name:
            return False
            
        # Simple approach: check if all words in provided name are in expected name
        provided_words = set(provided_name.lower().split())
        expected_words = set(expected_name.lower().split())
        
        # At least 80% of provided words should match expected words
        if len(provided_words) == 0:
            return False
            
        matching_words = provided_words.intersection(expected_words)
        match_ratio = len(matching_words) / len(provided_words)
        
        logger.info(f"Name match analysis: {match_ratio:.2f} ratio ({len(matching_words)}/{len(provided_words)} words)")
        return match_ratio >= 0.8

    def _format_eligibility_response(self, eligibility_result: dict) -> str:
        """Format a clear, concise eligibility response"""
        member_info = eligibility_result.get("member_info", {})
        coverage_info = eligibility_result.get("coverage_info", {})
        financial_info = eligibility_result.get("financial_info", {})
        
        # Start with key information
        response = f"Your coverage is active. "
        response += f"You have {coverage_info.get('plan_type', 'health insurance')} coverage. "
        
        # Add financial details if available
        if financial_info:
            deductible = financial_info.get('deductible', {})
            copays = financial_info.get('copays', {})
            
            if deductible:
                remaining = deductible.get('remaining', 0)
                individual = deductible.get('individual', 0)
                response += f"Your deductible has ${remaining:.0f} remaining out of ${individual:.0f}. "
            
            if copays:
                primary = copays.get('primary_care', 0)
                specialist = copays.get('specialist', 0)
                response += f"Copays are ${primary:.0f} for primary care and ${specialist:.0f} for specialists. "
        
        response += "Do you have any questions about your coverage?"
        
        return response

    async def _ask_for_missing_verification_info(self):
        """Ask for missing verification information"""
        if not self.full_name and not self.date_of_birth:
            message = "I'm here! I still need both your full name and your date of birth to verify your identity. Please go ahead."
        elif not self.full_name:
            message = "I need your full name please. What's your complete name?"
        else:
            message = "I need your date of birth please. What's your birth date?"
        
        await self._send_assistant_message(message)

    async def _send_verification_failed_message(self, name_match: bool, dob_match: bool):
        """Send verification failed message"""
        if not name_match and not dob_match:
            message = "The name and date of birth don't match our records. Please provide your full name and date of birth again."
        elif not name_match:
            message = "The name doesn't match our records for this member ID. Please provide your full name again."
        else:
            message = "The date of birth doesn't match our records. Please provide your date of birth again in MM/DD/YYYY format."
        
        await self._send_assistant_message(message)

    async def _send_max_attempts_message(self):
        """Send max attempts reached message"""
        message = "I've had trouble verifying your information after several attempts. Please contact customer service at the number on your insurance card for assistance."
        await self._send_assistant_message(message)

    async def _send_english_only_message(self):
        """Send message requesting English only"""
        message = "I can only help in English. Could you please ask in English?"
        await self._send_assistant_message(message)

    async def stop(self):
        """Stop the voice handler"""
        logger.info(f"🛑 Stopping voice handler for call {self.call_sid}")
        self.running = False
        
        if self.ws and not self.ws.closed:
            try:
                await self.ws.close()
                logger.info(f"🔌 WebSocket closed for call {self.call_sid}")
            except Exception as e:
                logger.warning(f"⚠️ Error closing WebSocket: {e}")
        
        # Clean up event loop reference
        self._handler_event_loop = None

    # Add synchronous stop method for twilio_manager
    def stop_sync(self):
        """Synchronous stop method for external calls"""
        logger.info(f"🛑 Stop requested for voice handler {self.call_sid}")
        self.running = False
        # The async cleanup will happen in the event loop