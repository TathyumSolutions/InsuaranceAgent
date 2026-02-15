"""
Simplified Voice Handler
Direct OpenAI Realtime API integration with embedded eligibility database
All conversation logic and database lookups are handled by OpenAI system prompt
"""
import json
import asyncio
import websockets
import base64
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
        
        # OpenAI connection details
        self.api_url = f"wss://api.openai.com/v1/realtime?model={Config.OPENAI_REALTIME_MODEL}"
        self.headers = {
            "Authorization": f"Bearer {openai_api_key}",
            "OpenAI-Beta": "realtime=v1"
        }
        
        logger.info(f"🎙️  Simplified voice handler initialized for call {call_sid}")

    def handle_audio(self, audio_data: str):
        """Handle incoming audio from Twilio"""
        try:
            if not self.ws or self.ws.closed:
                logger.warning("⚠️ WebSocket closed, cannot send audio")
                return
            
            # Increment counter
            self.audio_chunks_received += 1
            
            if self.audio_chunks_received == 1:
                logger.info("📥 First audio chunk received from Twilio")
            
            # Convert mulaw to PCM16 and send to OpenAI
            mulaw_audio = base64.b64decode(audio_data)
            pcm_audio = self.audio_converter.twilio_to_openai(mulaw_audio)
            pcm_b64 = base64.b64encode(pcm_audio).decode('utf-8')
            
            # Create append message
            append_message = {
                "type": "input_audio_buffer.append",
                "audio": pcm_b64
            }
            
            # Schedule the coroutine in the correct event loop
            if self._event_loop and not self._event_loop.is_closed():
                asyncio.run_coroutine_threadsafe(
                    self.ws.send(json.dumps(append_message)),
                    self._event_loop
                )
            else:
                logger.warning("⚠️ No event loop available for audio processing")
            
        except Exception as e:
            logger.error(f"❌ Error handling audio: {e}")

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
                logger.info(f"✅ Connected to OpenAI for call {self.call_sid}")
                
                # Configure session
                await self._configure_session()
                
                # Process events
                await self._process_events()
                
        except Exception as e:
            logger.error(f"💥 OpenAI connection error for call {self.call_sid}: {e}")
        finally:
            self.running = False
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
                        logger.info("✅ OpenAI session ready - conversation can begin")
                        
                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        transcript = data.get("transcript", "").strip()
                        if transcript:
                            logger.info(f"👤 User said: {transcript}")
                        
                    elif event_type == "conversation.item.input_audio_transcription.failed":
                        logger.warning("⚠️ Audio transcription failed")
                        
                    elif event_type == "input_audio_buffer.speech_started":
                        logger.info("🎤 User started speaking")
                        # Cancel any ongoing response when user starts speaking
                        if self._response_in_progress:
                            await self._cancel_current_response()
                        
                    elif event_type == "input_audio_buffer.speech_stopped":
                        logger.info("🎤 User stopped speaking")
                        # Commit audio buffer for processing
                        if not self._response_in_progress:
                            try:
                                commit_message = {"type": "input_audio_buffer.commit"}
                                await self.ws.send(json.dumps(commit_message))
                                logger.debug("📤 Audio buffer committed for processing")
                            except Exception as e:
                                logger.debug(f"Audio buffer commit error: {e}")
                        
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