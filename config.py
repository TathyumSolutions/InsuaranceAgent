"""
Unified Configuration
Settings for standalone voice-enabled insurance eligibility agent
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Unified configuration for voice and backend"""
    
    # OpenAI Configuration
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-realtime")
    OPENAI_REALTIME_MODEL = "gpt-realtime"
    OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"
    
    # Twilio Configuration
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    
    # Server Configuration
    YOUR_DOMAIN = os.getenv("YOUR_DOMAIN", "localhost")
    PORT = int(os.getenv("PORT", "5000"))
    HOST = os.getenv("HOST", "0.0.0.0")
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"
    
    # Logging Configuration
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "logs/app.log")
    
    # Audio Configuration
    AUDIO_SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
    # More aggressive VAD for faster turn-taking
    VAD_THRESHOLD = float(os.getenv("VAD_THRESHOLD", "0.25"))
    SILENCE_DURATION_MS = int(os.getenv("SILENCE_DURATION_MS", "300"))
    
    # Session Configuration
    SESSION_TIMEOUT_SECONDS = int(os.getenv("SESSION_TIMEOUT_SECONDS", "300"))
    MAX_CONCURRENT_CALLS = int(os.getenv("MAX_CONCURRENT_CALLS", "50"))
    
    # System Instructions for Voice AI
    VOICE_SYSTEM_INSTRUCTIONS = """You are a professional insurance eligibility verification assistant helping people over the phone.

    Your role:
    1. Greet callers warmly when they first speak to you.
    2. Help them check insurance coverage by collecting:
        - Member ID (format: MB followed by 6 digits, e.g., MB123456)
        - Date of Birth (convert to YYYY-MM-DD format internally)
        - Optionally: Procedure name or medication name.

    3. Once you have Member ID and Date of Birth, use the check_eligibility function.

    4. Explain results clearly and naturally:
        - Coverage status (active/inactive)
        - Deductible information
        - Copay amounts
        - Prior authorization requirements if needed.

    Speaking style:
    - Sound like a friendly, confident human agent on the phone.
    - Use contractions and conversational phrasing (for example: "you're", "they're", "let's").
    - Speak at a slightly faster-than-normal pace so the caller never feels you are speaking slowly.
    - Vary your intonation and emphasis so you do not sound flat or robotic.
    - Keep pauses between sentences very short unless the caller sounds confused.
    """

    @classmethod
    def validate(cls):
        """Validate required configuration"""
        errors = []
        
        if not cls.OPENAI_API_KEY:
            errors.append("OPENAI_API_KEY is required")
        
        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")
    
    @classmethod
    def get_websocket_url(cls):
        """Get WebSocket URL for Twilio"""
        return f"wss://{cls.YOUR_DOMAIN}/voice/stream"
    
    @staticmethod
    def get_openai_session_config():
        """Get OpenAI session configuration for voice"""
        return {
            # Model instructions
            "instructions": Config.VOICE_SYSTEM_INSTRUCTIONS,

            # Audio IO
            "modalities": ["text", "audio"],
            "input_audio_format": "pcm16",   # we send PCM16 16kHz, not mulaw
            "output_audio_format": "pcm16",

            # Transcription
            "input_audio_transcription": {
                "model": "gpt-4o-mini-transcribe",
            },

            "voice": "alloy",
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.5,
                "silence_duration_ms": 500,
            },
        }


# Validate configuration on import
try:
    Config.validate()
except ValueError as e:
    print(f"⚠️  Configuration Warning: {e}")
    print("Please check your .env file and ensure all required variables are set.")
