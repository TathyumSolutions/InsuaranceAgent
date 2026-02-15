"""
WebSocket Manager for Twilio Voice Streams
Handles bidirectional audio streaming between Twilio and the voice handler
"""
import json
import base64
import asyncio
from typing import Callable, Optional
from utils.logger import setup_logger

logger = setup_logger(__name__)


class WebSocketManager:
    """Manages WebSocket connection with Twilio for audio streaming"""
    
    def __init__(self, websocket, voice_handler):
        self.websocket = websocket
        self.voice_handler = voice_handler
        self.call_sid = None
        self.stream_sid = None
        self.running = True
        
    async def handle_connection(self):
        """Handle WebSocket connection lifecycle"""
        try:
            logger.info("🔌 WebSocket connection established")
            
            async for message in self.websocket:
                if not self.running:
                    break
                    
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    logger.warning("⚠️ Invalid JSON received from Twilio")
                except Exception as e:
                    logger.error(f"❌ Error processing Twilio message: {e}")
                    
        except Exception as e:
            logger.error(f"❌ WebSocket error: {e}")
        finally:
            await self._cleanup()
    
    async def _handle_message(self, data: dict):
        """Handle incoming Twilio WebSocket messages"""
        event_type = data.get("event")
        
        if event_type == "connected":
            logger.info("📞 Twilio WebSocket connected")
            
        elif event_type == "start":
            # Stream started
            self.call_sid = data.get("start", {}).get("callSid")
            self.stream_sid = data.get("start", {}).get("streamSid")
            logger.info(f"✓ Stream started - Call SID: {self.call_sid}")
            
            # Start the voice handler
            if self.voice_handler:
                asyncio.create_task(self.voice_handler.connect_and_run())
                logger.info("✓ Voice handler started")
            
        elif event_type == "media":
            # Audio data from caller
            media_data = data.get("media", {})
            audio_b64 = media_data.get("payload", "")
            
            if audio_b64 and self.voice_handler:
                # Send audio to voice handler (which will convert and send to OpenAI)
                await self.voice_handler.send_audio_from_user(audio_b64)
                
        elif event_type == "stop":
            # Stream stopped
            logger.info("📞 Call ended - Total media packets: " + str(data.get("sequenceNumber", 0)))
            self.running = False
            
        elif event_type == "mark":
            # Mark event (usually used for synchronization)
            logger.debug("📋 Mark event received")
            
        else:
            logger.debug(f"🔍 Unknown Twilio event: {event_type}")
    
    def send_audio_to_caller(self, audio_b64: str):
        """Send audio to caller via Twilio WebSocket"""
        try:
            if not self.running or not self.websocket:
                return
                
            # Create media message for Twilio
            media_message = {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {
                    "payload": audio_b64
                }
            }
            
            # Send asynchronously
            asyncio.create_task(self._send_message(media_message))
            
        except Exception as e:
            logger.error(f"❌ Error sending audio to Twilio: {e}")
    
    async def _send_message(self, message: dict):
        """Send message to Twilio WebSocket"""
        try:
            if self.websocket and not self.websocket.closed:
                await self.websocket.send(json.dumps(message))
        except Exception as e:
            logger.error(f"❌ Error sending message to Twilio: {e}")
    
    async def _cleanup(self):
        """Cleanup WebSocket connection"""
        try:
            self.running = False
            if self.voice_handler:
                self.voice_handler.stop()
            logger.info("✓ Twilio WebSocket manager cleaned up")
        except Exception as e:
            logger.error(f"❌ Cleanup error: {e}")