"""
Unified Voice Handler
Integrates OpenAI Realtime API directly with LangGraph eligibility agent
"""
import asyncio
import base64
import json
import time
import uuid
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
        
        self.audio_buffer = []  # Buffer for audio chunks before ws is ready
        logger.info(f"🎙️  Voice handler initialized for call {call_sid}")
    
    async def connect_and_run(self):
        """Connect to OpenAI and run the event loop"""
        try:
            logger.info(f"🔌 Connecting to OpenAI Realtime at {self.api_url} for call {self.call_sid}")
            async with websockets.connect(self.api_url, extra_headers=self.headers) as ws:
                self.ws = ws
                logger.info(f"✓ OpenAI connected for call {self.call_sid}")

                # Flush any audio we buffered before the websocket was ready
                if self.audio_buffer:
                    logger.info(f"Flushing {len(self.audio_buffer)} buffered audio chunks to OpenAI")
                    for chunk in self.audio_buffer:
                        await self.send_audio_from_user(chunk)
                    self.audio_buffer.clear()

                await self._configure_session()
                await self._event_loop()
        except Exception as e:
            logger.error(f"Error in OpenAI voice handler: {e}", exc_info=True)
        finally:
            logger.info(f"🔌 OpenAI connection closed for call {self.call_sid}")
            self.running = False

    async def _configure_session(self):
        """Configure the Realtime session to use G.711 μ-law, matching Twilio."""
        session_update = {
            "type": "session.update",
            "session": {
                "model": Config.OPENAI_REALTIME_MODEL,
                "instructions": getattr(Config, "REALTIME_SYSTEM_PROMPT", ""),
                "voice": "alloy",
                # CRITICAL: match Twilio codec end‑to‑end
                "input_audio_format": "g711_ulaw",
                "output_audio_format": "g711_ulaw",
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": float(getattr(Config, "VAD_THRESHOLD", 0.5)),
                    "silence_duration_ms": int(getattr(Config, "SILENCE_DURATION_MS", 700)),
                },
                "input_audio_transcription": {
                    "model": "gpt-4o-mini-transcribe",
                },
            },
        }
        await self.ws.send(json.dumps(session_update))
        logger.info("✓ OpenAI session configured - waiting for caller...")
    
    async def _event_loop(self):
        """Minimal event loop: just forward audio back to Twilio and log."""
        try:
            async for message in self.ws:
                data = json.loads(message)
                event_type = data.get("type")
                logger.info(f"🔎 OpenAI event type: {event_type}")

                if event_type in ("response.audio.delta", "response.output_audio.delta"):
                    await self._handle_audio_delta(data)
                # keep your other handlers (transcript, errors, etc.) as needed
        except Exception as e:
            logger.error(f"Error in OpenAI event loop: {e}", exc_info=True)

    async def _handle_audio_delta(self, data: dict):
        """
        Handle streamed audio from OpenAI and send to Twilio.

        With output_audio_format=g711_ulaw, `delta` is already base64 μ-law at 8kHz.
        Just pass it through, no conversion.
        """
        mulaw_b64 = data.get("delta")
        if not mulaw_b64:
            return

        self.audio_chunks_sent += 1
        try:
            self.twilio_callback(mulaw_b64)
        except Exception as e:
            logger.error("Failed to send audio to Twilio", exc_info=True)

    async def send_audio_from_user(self, audio_b64: str):
        """
        Send user audio to OpenAI.

        With input_audio_format=g711_ulaw, `audio_b64` is the Twilio payload as-is.
        """
        if not self.ws:
            return

        await self.ws.send(json.dumps({
            "type": "input_audio_buffer.append",
            "audio": audio_b64,
        }))

    def stop(self):
        """Stop the handler"""
        self.running = False
        logger.info(f"📊 Call ended - Received {self.audio_chunks_received}, Sent {self.audio_chunks_sent} chunks")
