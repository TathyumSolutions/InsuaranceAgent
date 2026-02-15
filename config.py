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
    OPENAI_REALTIME_MODEL = "gpt-4o-realtime-preview"  # Updated model name
    
    # Audio Configuration for natural conversation
    VAD_THRESHOLD = 0.3  # More sensitive to detect speech (was 0.2)
    SILENCE_DURATION_MS = 500  # Faster response time (was 300)
    RESPONSE_TIMEOUT_MS = 5000  # Cancel if no response in 5 seconds
    
    # Voice settings for better conversation flow  
    VOICE_INTERRUPTION_ENABLED = True
    ENGLISH_ONLY_MODE = True
    MAX_RESPONSE_TOKENS = 300  # Increased from 100
    TEMPERATURE = 0.6  # Minimum allowed for Realtime API (0.6-2.0)
    
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
    
    # Session Configuration
    SESSION_TIMEOUT_SECONDS = int(os.getenv("SESSION_TIMEOUT_SECONDS", "300"))
    MAX_CONCURRENT_CALLS = int(os.getenv("MAX_CONCURRENT_CALLS", "50"))
    
    # System Instructions for Voice AI
    VOICE_SYSTEM_INSTRUCTIONS = """You are a professional insurance eligibility verification assistant helping people over the phone.

    Your role:
    1. Greet callers warmly: "Hello! I can help check your insurance eligibility. What's your member ID?"

    2. WORKFLOW:
       - FIRST: Ask for Member ID
       - SECOND: Ask for full name and date of birth for verification
       - THIRD: Wait for system verification, then provide eligibility details

    3. Verification process:
       - After getting member ID, say: "Thank you. For verification, I'll need your full name and date of birth."
       - Be patient while collecting both pieces of information
       - The system will verify the details in the background

    4. Handle verification results:
       - If member not found: Ask them to double-check the member ID
       - If verification fails: Ask them to verify their name and date of birth
       - If successful: Provide comprehensive eligibility information

    Speaking style:
    - Sound like a friendly, confident human agent on the phone
    - Use contractions and conversational phrasing
    - Speak at a normal pace
    - Be professional but warm
    - Wait for complete responses before proceeding
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
