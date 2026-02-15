"""
Twilio WebSocket Manager
Manages WebSocket connection from Twilio and coordinates with voice handler
"""
import json
import base64
import asyncio
import threading
import time
from typing import Optional

from utils.logger import setup_logger
from utils.audio_utils import AudioConverter
from voice.handler import VoiceHandler
from config import Config

logger = setup_logger(__name__)


class TwilioWebSocketManager:
    """
    Manages Twilio WebSocket connection and coordinates with OpenAI voice handler
    """
    
    def __init__(self, websocket, openai_api_key: str):
        """
        Initialize Twilio WebSocket manager
        
        Args:
            websocket: Flask-Sock WebSocket connection
            openai_api_key: OpenAI API key
        """
        self.ws = websocket
        self.openai_api_key = openai_api_key
        self.voice_handler: Optional[VoiceHandler] = None
        self.event_loop: Optional[asyncio.AbstractEventLoop] = None
        self.stream_sid: Optional[str] = None
        self.call_sid: Optional[str] = None
        self.media_count = 0
        self.audio_chunks_sent = 0
    
    def handle_connection(self):
        """
        Main handler for Twilio WebSocket connection
        Receives messages from Twilio and routes them appropriately
        """
        logger.info("📞 Twilio WebSocket connected")
        
        try:
            while True:
                # Receive message from Twilio
                message = self.ws.receive(timeout=None)
                if not message:
                    break
                
                data = json.loads(message)
                event_type = data.get("event")
                
                # Route to appropriate handler
                if event_type == "start":
                    self._handle_start(data)
                
                elif event_type == "media":
                    self._handle_media(data)
                
                elif event_type == "stop":
                    self._handle_stop(data)
                    break
                
                elif event_type == "mark":
                    # Mark events for synchronization
                    pass
        
        except Exception as e:
            logger.error(f"Error in Twilio handler: {e}")
        
        finally:
            self._cleanup()
    
    def _handle_start(self, data: dict):
        """
        Handle stream start event from Twilio
        
        Args:
            data: Start event data
        """
        start_data = data.get("start", {})
        self.stream_sid = start_data.get("streamSid")
        self.call_sid = start_data.get("callSid")
        
        logger.info(f"✓ Stream started - Call SID: {self.call_sid}")
        
        # Initialize voice handler with correct parameter names
        self.voice_handler = VoiceHandler(
            call_sid=self.call_sid,  # Matches VoiceHandler.__init__
            conversation_id=self.stream_sid,  # Use stream_sid as conversation_id
            twilio_callback=self._send_audio_to_twilio,
            openai_api_key=self.openai_api_key,
        )
        
        # Start voice handler in separate thread with its own event loop
        self.event_loop = asyncio.new_event_loop()

        def run_voice_handler():
            asyncio.set_event_loop(self.event_loop)
            self.event_loop.run_until_complete(self.voice_handler.connect_and_run())

        thread = threading.Thread(target=run_voice_handler, daemon=True)
        thread.start()

        time.sleep(0.5)
        logger.info("✓ Voice handler started")
    
    def _handle_media(self, data: dict):
        """
        Handle media (audio) event from Twilio
        """
        self.media_count += 1
        
        if self.media_count == 1:
            logger.info("📥 Started receiving media from Twilio")
        
        if self.media_count % 100 == 0:
            logger.debug(f"📥 Received {self.media_count} media packets")
        
        media_data = data.get("media", {})
        mulaw_b64 = media_data.get("payload")
        
        if not mulaw_b64 or not self.voice_handler:
            return
        
        try:
            # Fixed: Use handle_audio instead of send_audio_from_user
            self.voice_handler.handle_audio(mulaw_b64)
        except Exception as e:
            logger.error(f"Error processing media: {e}")
    
    def _handle_stop(self, data: dict):
        """
        Handle stream stop event from Twilio
        
        Args:
            data: Stop event data
        """
        logger.info(f"📞 Call ended - Total media packets: {self.media_count}")
    
    def _send_audio_to_twilio(self, mulaw_b64: str):
        """
        Send mulaw audio back to Twilio over the WebSocket
        """
        if not self.ws or not self.stream_sid:
            logger.warning("Cannot send audio to Twilio: websocket or stream_sid missing")
            return

        msg = {
        
            "event": "media",
            "streamSid": self.stream_sid,
            "media": {"payload": mulaw_b64},
        }

        try:
            self.ws.send(json.dumps(msg))  # flask_sock ws is synchronous
            self.audio_chunks_sent += 1
            if self.audio_chunks_sent == 1:
                logger.info("📤 First audio chunk sent to Twilio")
        except Exception as e:
            logger.error(f"Error sending audio to Twilio: {e}", exc_info=True)
    
    def _cleanup(self):
        """
        Clean up resources when connection ends
        """
        logger.info("🧹 Cleaning up Twilio WebSocket manager")
        
        try:
            if self.voice_handler:
                # Use the sync stop method
                self.voice_handler.stop_sync()
                logger.info("✓ Voice handler stopped")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        finally:
            self.voice_handler = None
            logger.info("✓ Twilio WebSocket manager cleaned up")


def create_twilio_manager(websocket, openai_api_key: str):
    """
    Factory function to create and run Twilio manager
    
    Args:
        websocket: Flask-Sock WebSocket connection
        openai_api_key: OpenAI API key
    """
    manager = TwilioWebSocketManager(websocket, openai_api_key)
    manager.handle_connection()
