"""
Simplified Voice Handler
Direct OpenAI Realtime API integration with embedded eligibility database
All conversation logic and database lookups are handled by OpenAI system prompt
"""
import json
import asyncio
import websockets
import base64
import time
from typing import Callable, Optional

from utils.logger import setup_logger
from utils.audio_utils import AudioConverter
from config import Config

logger = setup_logger(__name__)


class VoiceHandler:
    """
    Simplified handler that manages OpenAI Realtime API with embedded eligibility database
    All conversation and verification logic is handled by OpenAI through system prompt
    """
    
    def __init__(self, call_sid: str, conversation_id: str, twilio_callback: Callable, openai_api_key: str):
        """Initialize the voice handler"""
        
        self.call_sid = call_sid
        self.conversation_id = conversation_id
        self.twilio_callback = twilio_callback
        self.openai_api_key = openai_api_key
        
        # Initialize audio converter
        self.audio_converter = AudioConverter()
        
        # Basic state tracking
        self.ws = None
        self.audio_buffer = []
        self.audio_chunks_received = 0
        self.audio_chunks_sent = 0
        self.first_audio_sent = False
        self._response_in_progress = False
        self._current_response_id = None
        self.running = True
        self._event_loop = None  # Store the event loop reference
        
        # Audio buffer management for timing fix
        self.pending_audio_buffer = []  # Queue audio while connecting
        self.total_audio_sent_to_openai = 0
        self.current_speech_audio_bytes = 0  # Track audio per speech session
        self.min_audio_bytes_for_commit = 3200  # 100ms at 16kHz = 16000 samples/sec * 2 bytes * 0.1sec
        self.openai_connected = False
        
        # Speech detection fallback
        self.speech_start_time = None
        self.last_audio_time = None
        self.speech_timeout_task = None
        self.max_speech_duration = 30.0  # 30 seconds max speech
        self.silence_detection_timeout = 3.0  # 3 seconds of no new audio = silence
        
        # OpenAI connection details
        self.api_url = f"wss://api.openai.com/v1/realtime?model={Config.OPENAI_REALTIME_MODEL}"
        self.headers = {
            "Authorization": f"Bearer {openai_api_key}",
            "OpenAI-Beta": "realtime=v1"
        }
        
        logger.info(f"🎙️  Simplified voice handler initialized for call {call_sid}")

    def handle_audio(self, audio_data: str):
        """Handle incoming audio from Twilio - buffer if not connected"""
        try:
            # Update timing
            self.last_audio_time = time.time()
            
            # Increment counter
            self.audio_chunks_received += 1
            
            if self.audio_chunks_received == 1:
                logger.info("📥 First audio chunk received from Twilio")
            
            # Convert mulaw to PCM16
            mulaw_audio = base64.b64decode(audio_data)
            pcm_audio = self.audio_converter.twilio_to_openai(mulaw_audio)
            
            # If OpenAI not connected yet, buffer the audio
            if not self.openai_connected or not self.ws or self.ws.closed:
                self.pending_audio_buffer.append(pcm_audio)
                if self.audio_chunks_received <= 5:  # Don't spam logs
                    logger.debug(f"📦 Buffering audio chunk (total: {len(self.pending_audio_buffer)})")
                return
            
            # Send to OpenAI immediately if connected
            pcm_b64 = base64.b64encode(pcm_audio).decode('utf-8')
            
            # Create append message
            append_message = {
                "type": "input_audio_buffer.append",
                "audio": pcm_b64
            }
            
            # Schedule the coroutine in the correct event loop
            if self._event_loop and not self._event_loop.is_closed():
                asyncio.run_coroutine_threadsafe(
                    self._send_audio_to_openai_sync(append_message, len(pcm_audio)),
                    self._event_loop
                )
            else:
                logger.warning("⚠️ No event loop available for audio processing")
            
        except Exception as e:
            logger.error(f"❌ Error handling audio: {e}")

    async def _send_audio_to_openai_sync(self, append_message, audio_size):
        """Send audio message to OpenAI and track bytes"""
        try:
            await self.ws.send(json.dumps(append_message))
            self.total_audio_sent_to_openai += audio_size
            self.current_speech_audio_bytes += audio_size
            
            # Add periodic logging for debugging
            if self.total_audio_sent_to_openai % 10000 == 0:  # Every ~10KB
                logger.debug(f"📤 Audio progress: {self.total_audio_sent_to_openai} total bytes sent")
                
        except Exception as e:
            logger.error(f"❌ Error sending audio to OpenAI: {e}")

    async def _start_speech_timeout_timer(self):
        """Start fallback timer for speech detection"""
        if self.speech_timeout_task:
            self.speech_timeout_task.cancel()
            
        async def timeout_check():
            try:
                # Wait for max speech duration
                await asyncio.sleep(self.max_speech_duration)
                logger.warning(f"⏰ Speech timeout reached ({self.max_speech_duration}s) - forcing speech_stopped")
                await self._force_speech_stopped("timeout")
            except asyncio.CancelledError:
                pass
                
        self.speech_timeout_task = asyncio.create_task(timeout_check())

    async def _start_silence_detection(self):
        """Start fallback silence detection"""
        async def silence_check():
            try:
                while self.speech_start_time and self.running:
                    await asyncio.sleep(0.5)  # Check every 500ms
                    
                    if self.last_audio_time and self.running:
                        silence_duration = time.time() - self.last_audio_time
                        if silence_duration >= self.silence_detection_timeout:
                            logger.info(f"🔇 Detected {silence_duration:.1f}s silence - forcing speech_stopped")
                            await self._force_speech_stopped("silence")
                            break
            except asyncio.CancelledError:
                pass
                
        asyncio.create_task(silence_check())

    async def _force_speech_stopped(self, reason: str):
        """Force speech stopped event when OpenAI doesn't detect it"""
        if not self.speech_start_time:
            return  # No active speech
            
        logger.info(f"🎤 User stopped speaking (detected by {reason})")
        
        # Reset speech tracking
        self.speech_start_time = None
        if self.speech_timeout_task:
            self.speech_timeout_task.cancel()
            self.speech_timeout_task = None
        
        # Wait a moment for any final audio chunks
        await asyncio.sleep(0.2)
        
        # Only commit if we have enough audio and no response in progress
        if self.current_speech_audio_bytes >= self.min_audio_bytes_for_commit:
            if not self._response_in_progress:
                try:
                    commit_message = {"type": "input_audio_buffer.commit"}
                    await self.ws.send(json.dumps(commit_message))
                    logger.info(f"📤 Audio buffer committed ({self.current_speech_audio_bytes} bytes)")
                except Exception as e:
                    logger.error(f"❌ Audio buffer commit error: {e}")
        else:
            logger.warning(f"⚠️ Skipping commit - insufficient audio ({self.current_speech_audio_bytes} bytes < {self.min_audio_bytes_for_commit} required)")

    async def _flush_pending_audio(self):
        """Send all buffered audio to OpenAI when connection is established"""
        if not self.pending_audio_buffer:
            return
            
        logger.info(f"📤 Flushing {len(self.pending_audio_buffer)} buffered audio chunks to OpenAI")
        
        for pcm_audio in self.pending_audio_buffer:
            try:
                pcm_b64 = base64.b64encode(pcm_audio).decode('utf-8')
                append_message = {
                    "type": "input_audio_buffer.append", 
                    "audio": pcm_b64
                }
                await self.ws.send(json.dumps(append_message))
                self.total_audio_sent_to_openai += len(pcm_audio)
                self.current_speech_audio_bytes += len(pcm_audio)
            except Exception as e:
                logger.error(f"❌ Error flushing audio: {e}")
                break
        
        # Clear buffer after flushing
        buffer_size = len(self.pending_audio_buffer)
        self.pending_audio_buffer.clear() 
        logger.info(f"✅ Flushed {buffer_size} audio chunks ({self.total_audio_sent_to_openai} total bytes)")

    async def _trigger_initial_greeting(self):
        """Trigger the AI to start with initial greeting immediately when call connects"""
        try:
            # Create a system message that prompts the agent to start greeting
            greeting_trigger = {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Call connected. Please start with your opening greeting now in English only. Use the exact greeting from your instructions."
                        }
                    ]
                }
            }
            
            # Send the trigger message
            await self.ws.send(json.dumps(greeting_trigger))
            logger.info("📤 Sent greeting trigger to OpenAI")
            
            # Small delay to ensure the item is created
            await asyncio.sleep(0.1)
            
            # Request a response to make the AI start speaking - FIXED: using correct modalities
            response_request = {
                "type": "response.create",
                "response": {
                    "modalities": ["text", "audio"],  # Fixed: must match session modalities
                    "instructions": "Start the conversation with the opening greeting as per your instructions. Speak ONLY in English. Begin speaking immediately with the exact English greeting provided."
                }
            }
            
            await self.ws.send(json.dumps(response_request))
            logger.info("🎤 Requested AI to start speaking greeting")
            
        except Exception as e:
            logger.error(f"❌ Error triggering initial greeting: {e}")
            # If greeting trigger fails, log but don't break the connection
            logger.warning("⚠️ Initial greeting trigger failed - user will need to speak first")

    async def _configure_session(self):
        """Configure the Realtime session with OpenAI"""
        session_config = {
            "type": "session.update",
            "session": Config.get_openai_session_config()
        }
        
        try:
            await self.ws.send(json.dumps(session_config))
            logger.info("✅ Session configuration sent to OpenAI")
        except Exception as e:
            logger.error(f"❌ Error configuring session: {e}")
            raise

    async def _cancel_current_response(self):
        """Cancel current response when user starts speaking"""
        if self._current_response_id:
            try:
                cancel_message = {
                    "type": "response.cancel"
                }
                await self.ws.send(json.dumps(cancel_message))
                logger.debug(f"🛑 Cancelled response: {self._current_response_id}")
            except Exception as e:
                logger.debug(f"Response cancel error: {e}")

    async def connect_and_run(self):
        """Main connection method"""
        logger.info(f"🔌 Connecting to OpenAI Realtime API for call {self.call_sid}")
        
        # Store the current event loop
        self._event_loop = asyncio.get_event_loop()
        
        try:
            async with websockets.connect(
                self.api_url,
                extra_headers=self.headers,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=10
            ) as websocket:
                self.ws = websocket
                self.openai_connected = True  # Mark as connected
                logger.info(f"✅ Connected to OpenAI for call {self.call_sid}")
                
                # Configure session
                await self._configure_session()
                
                # Flush any buffered audio immediately after connection
                await self._flush_pending_audio()
                
                # Process events
                await self._process_events()
                
        except Exception as e:
            logger.error(f"💥 OpenAI connection error for call {self.call_sid}: {e}")
        finally:
            self.running = False
            self.openai_connected = False
            self._event_loop = None
            logger.info(f"🔌 OpenAI connection closed for call {self.call_sid}")

    async def _process_events(self):
        """Simplified event processing - OpenAI handles all conversation logic"""
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
                        logger.info("✅ OpenAI session ready - triggering initial greeting")
                        # Small delay to ensure session is fully configured
                        await asyncio.sleep(0.2)
                        # Trigger the AI to start speaking with the greeting
                        await self._trigger_initial_greeting()
                        
                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        transcript = data.get("transcript", "").strip()
                        if transcript:
                            logger.info(f"👤 User said: {transcript}")
                        
                    elif event_type == "conversation.item.input_audio_transcription.failed":
                        error_details = data.get("error", {})
                        content_index = data.get("content_index", "unknown")
                        logger.warning(f"⚠️ Audio transcription failed - Content index: {content_index}, Error: {error_details}")
                        logger.info(f"📊 Audio stats - Bytes sent: {self.current_speech_audio_bytes}, Total sent: {self.total_audio_sent_to_openai}")
                        
                    elif event_type == "input_audio_buffer.speech_started":
                        logger.info("🎤 User started speaking")
                        # Track speech timing
                        self.speech_start_time = time.time()
                        # Reset counter for new speech session
                        self.current_speech_audio_bytes = 0
                        # Cancel any ongoing response when user starts speaking
                        if self._response_in_progress:
                            await self._cancel_current_response()
                        
                        # Start fallback timers
                        await self._start_speech_timeout_timer()
                        await self._start_silence_detection()
                        
                    elif event_type == "input_audio_buffer.speech_stopped":
                        logger.info("🎤 User stopped speaking (OpenAI detected)")
                        
                        # Cancel fallback timers since OpenAI detected it
                        self.speech_start_time = None
                        if self.speech_timeout_task:
                            self.speech_timeout_task.cancel()
                            self.speech_timeout_task = None
                        
                        # Wait a moment for any final audio chunks to arrive
                        await asyncio.sleep(0.9)
                        
                        # Only commit if we have enough audio (minimum 100ms)
                        if self.current_speech_audio_bytes >= self.min_audio_bytes_for_commit:
                            if not self._response_in_progress:
                                try:
                                    commit_message = {"type": "input_audio_buffer.commit"}
                                    await self.ws.send(json.dumps(commit_message))
                                    logger.info(f"📤 Audio buffer committed ({self.current_speech_audio_bytes} bytes)")
                                except Exception as e:
                                    error_msg = str(e)
                                    if "buffer_commit_empty" in error_msg or "buffer too small" in error_msg:
                                        logger.error(f"❌ Buffer commit timing issue - OpenAI hasn't processed audio chunks yet")
                                        logger.info("💡 Try speaking more clearly or for longer duration")
                                    else:
                                        logger.error(f"❌ Audio buffer commit error: {e}")
                        else:
                            logger.warning(f"⚠️ Skipping commit - insufficient audio ({self.current_speech_audio_bytes} bytes < {self.min_audio_bytes_for_commit} required)")
                        
                    elif event_type == "input_audio_buffer.committed":
                        logger.info("✅ Audio buffer committed - transcript should follow")
                        # Reset counter after successful commit
                        self.current_speech_audio_bytes = 0
                        
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
                        
                    elif event_type == "error":
                        error_info = data.get("error", {})
                        logger.error(f"❌ OpenAI API error: {error_info}")
                        
                    # Log other events for debugging
                    else:
                        logger.debug(f"📨 OpenAI event: {event_type}")
                        
                except json.JSONDecodeError:
                    logger.warning("⚠️ Invalid JSON from OpenAI")
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
                logger.info("📤 First audio chunk sent to Twilio")
                
        except Exception as e:
            logger.error(f"❌ Error handling audio delta: {e}")

    async def stop(self):
        """Stop the voice handler"""
        logger.info(f"🛑 Stopping voice handler for call {self.call_sid}")
        self.running = False
        self.openai_connected = False
        
        # Cancel any running timers
        if self.speech_timeout_task:
            self.speech_timeout_task.cancel()
            self.speech_timeout_task = None
        self.speech_start_time = None
        
        if self.ws and not self.ws.closed:
            try:
                await self.ws.close()
                logger.info(f"🔌 WebSocket closed for call {self.call_sid}")
            except Exception as e:
                logger.warning(f"⚠️ Error closing WebSocket: {e}")

    def stop_sync(self):
        """Synchronous stop method for external calls"""
        logger.info(f"🛑 Stop requested for voice handler {self.call_sid}")
        # In a real implementation, you'd signal the async loop to stop
        self.running = False
        self.openai_connected = False
        self.speech_start_time = None
        if self.speech_timeout_task:
            self.speech_timeout_task.cancel()
            self.speech_timeout_task = None