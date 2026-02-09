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
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4-turbo-preview")
    OPENAI_REALTIME_MODEL = "gpt-4o-realtime-preview-2024-10-01"
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
    VAD_THRESHOLD = float(os.getenv("VAD_THRESHOLD", "0.5"))
    SILENCE_DURATION_MS = int(os.getenv("SILENCE_DURATION_MS", "700"))
    
    # Session Configuration
    SESSION_TIMEOUT_SECONDS = int(os.getenv("SESSION_TIMEOUT_SECONDS", "300"))
    MAX_CONCURRENT_CALLS = int(os.getenv("MAX_CONCURRENT_CALLS", "50"))
    
    # System Instructions for Voice AI
    VOICE_SYSTEM_INSTRUCTIONS = """You are a professional insurance eligibility verification assistant helping people over the phone.

Your role:
1. Greet callers warmly when they first speak to you
2. Help them check insurance coverage by collecting:
   - Member ID (format: MB followed by 6 digits, e.g., MB123456)
   - Date of Birth (convert to YYYY-MM-DD format internally)
   - Optionally: Procedure name or medication name

3. Once you have Member ID and Date of Birth, use the check_eligibility function

4. Explain results clearly and naturally:
   - Coverage status (active/inactive)
   - Deductible information
   - Copay amounts
   - Prior authorization requirements if needed

Guidelines:
- Be patient, warm, and empathetic
- Speak clearly at a moderate pace
- Confirm information before checking eligibility
- Use simple, non-technical language
- If the caller provides partial info, ask for what's missing
- Always maintain HIPAA compliance

Remember: You're helping people understand their insurance, which can be confusing and stressful. Be reassuring and helpful."""

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
    
    @classmethod
    def get_openai_session_config(cls):
        """Get OpenAI session configuration for voice"""
        return {
            "modalities": ["text", "audio"],
            "instructions": cls.VOICE_SYSTEM_INSTRUCTIONS,
            "voice": "alloy",
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "turn_detection": {
                "type": "server_vad",
                "threshold": cls.VAD_THRESHOLD,
                "prefix_padding_ms": 300,
                "silence_duration_ms": cls.SILENCE_DURATION_MS
            },
            "input_audio_transcription": {
                "model": "whisper-1"
            },
            "tools": [
                {
                    "type": "function",
                    "name": "check_eligibility",
                    "description": "Check insurance eligibility for a member",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "member_id": {
                                "type": "string",
                                "description": "Member ID (e.g., MB123456)"
                            },
                            "date_of_birth": {
                                "type": "string",
                                "description": "Date of birth in YYYY-MM-DD format"
                            },
                            "procedure_name": {
                                "type": "string",
                                "description": "Optional name of medical procedure (e.g., 'MRI', 'knee replacement')"
                            },
                            "medication_name": {
                                "type": "string",
                                "description": "Optional name of medication (e.g., 'Humira', 'Metformin')"
                            }
                        },
                        "required": ["member_id", "date_of_birth"]
                    }
                }
            ]
        }


# Validate configuration on import
try:
    Config.validate()
except ValueError as e:
    print(f"⚠️  Configuration Warning: {e}")
    print("Please check your .env file and ensure all required variables are set.")
