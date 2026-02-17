"""
Standalone Insurance Eligibility Voice Agent
Unified application combining voice interface and LangGraph agent
"""
from flask import Flask, request, jsonify
from flask_sock import Sock
from flask_cors import CORS
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream
import os
import uuid
from typing import Dict

from config import Config
from utils.logger import setup_logger
from voice.twilio_manager import create_twilio_manager

# Note: Non-voice API endpoints still use EligibilityAgent
# Only the voice interface now uses embedded database
try:
    from agent.eligibility_agent import EligibilityAgent
    from agent.state import ConversationState
    from api.eligibility_api import MockEligibilityAPI
    
    # Initialize agent (for non-voice API endpoints only)
    agent = EligibilityAgent(openai_api_key=Config.OPENAI_API_KEY)
except ImportError:
    logger.warning("⚠️ Agent components not available - only voice interface will work")
    agent = None

# Setup logging
logger = setup_logger(__name__, Config.LOG_FILE, Config.LOG_LEVEL)

# Initialize Flask app
app = Flask(__name__)
CORS(app)
sock = Sock(app)

# Initialize agent (for non-voice API endpoints)
agent = EligibilityAgent(openai_api_key=Config.OPENAI_API_KEY)

# Store conversation states (in production, use Redis or database)
conversation_states: Dict[str, ConversationState] = {}

# Banner
logger.info("=" * 80)
logger.info("  🎙️  SIMPLIFIED INSURANCE ELIGIBILITY VOICE AGENT (POC)")
logger.info("  📊  EMBEDDED DATABASE - NO API CALLS")
logger.info("=" * 80)
logger.info(f"  OpenAI Model (Voice): {Config.OPENAI_REALTIME_MODEL}")
logger.info(f"  Your Domain: {Config.YOUR_DOMAIN}")
logger.info(f"  Port: {Config.PORT}")
logger.info("=" * 80)


# ============================================================================
# VOICE ENDPOINTS
# ============================================================================

@app.route("/voice/health", methods=["GET"])
def voice_health_check():
    """Health check for voice service"""
    return {
        "status": "healthy",
        "service": "Voice Integration",
        "openai_configured": bool(Config.OPENAI_API_KEY)
    }, 200


@app.route("/voice/incoming", methods=["POST"])
def incoming_call():
    """
    Handle incoming call from Twilio
    
    Returns:
        TwiML response to connect to WebSocket
    """
    caller = request.values.get("From", "Unknown")
    called = request.values.get("To", "Unknown")
    call_sid = request.values.get("CallSid", "Unknown")
    
    logger.info(f"📞 Incoming call from {caller} to {called} (SID: {call_sid})")
    
    # Create TwiML response
    response = VoiceResponse()
    
    # Add greeting before connecting to AI
    response.say(
        "Welcome to On-Shore Health Services. Please wait while I connect you to our Insurance Assistant.",
        voice="Polly.Joanna"
    )
    
    # Connect to WebSocket stream
    connect = Connect()
    stream = Stream(url=Config.get_websocket_url())
    connect.append(stream)
    response.append(connect)
    
    twiml = str(response)
    logger.info(f"✓ Returning TwiML for call {call_sid}")
    
    return twiml, 200, {'Content-Type': 'text/xml'}


@app.route("/voice/status", methods=["POST"])
def call_status():
    """Handle call status callbacks from Twilio"""
    call_sid = request.values.get("CallSid", "Unknown")
    call_status = request.values.get("CallStatus", "Unknown")
    
    logger.info(f"📊 Call {call_sid} status: {call_status}")
    
    return "", 200


@sock.route('/voice/stream')
def voice_stream(ws):
    """
    WebSocket endpoint for Twilio Media Stream
    
    This is where the actual voice data flows
    """
    logger.info("🔌 WebSocket connection established")
    
    try:
        # Create and run Twilio manager with OpenAI API key
        create_twilio_manager(ws, Config.OPENAI_API_KEY)
    except Exception as e:
        logger.error(f"❌ Error in WebSocket handler: {e}")
    finally:
        logger.info("🔌 WebSocket connection closed")


# ============================================================================
# TEXT/CHAT API ENDPOINTS (Non-voice)
# ============================================================================

@app.route("/health", methods=["GET"])
def health_check():
    """General health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "Insurance Eligibility Agent",
        "voice_enabled": bool(Config.OPENAI_API_KEY)
    }), 200


@app.route("/api/conversation/start", methods=["POST"])
def start_conversation():
    """
    Start a new conversation (non-voice)
    
    Request body:
    {
        "initial_message": "User's first message"
    }
    """
    try:
        data = request.get_json()
        initial_message = data.get("initial_message", "")
        
        if not initial_message:
            return jsonify({"error": "initial_message is required"}), 400
        
        # Generate conversation ID
        conversation_id = str(uuid.uuid4())
        
        # Process the initial message
        result = agent.process_message(
            conversation_id=conversation_id,
            user_message=initial_message
        )
        
        # Store state
        conversation_states[conversation_id] = result["state"]
        
        return jsonify({
            "conversation_id": conversation_id,
            "response": result["response"],
            "eligibility_determined": result.get("eligibility_determined", False),
            "api_response": result.get("api_response")
        }), 200
        
    except Exception as e:
        logger.error(f"Error starting conversation: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/conversation/<conversation_id>/message", methods=["POST"])
def send_message(conversation_id: str):
    """
    Continue an existing conversation
    
    Request body:
    {
        "message": "User's message"
    }
    """
    try:
        # Check if conversation exists
        if conversation_id not in conversation_states:
            return jsonify({"error": "Conversation not found"}), 404
        
        data = request.get_json()
        message = data.get("message", "")
        
        if not message:
            return jsonify({"error": "message is required"}), 400
        
        # Get current state
        current_state = conversation_states[conversation_id]
        
        # Process the message
        result = agent.process_message(
            conversation_id=conversation_id,
            user_message=message,
            current_state=current_state
        )
        
        # Update state
        conversation_states[conversation_id] = result["state"]
        
        return jsonify({
            "response": result["response"],
            "eligibility_determined": result.get("eligibility_determined", False),
            "api_response": result.get("api_response"),
            "state_info": {
                "member_id": result["state"].get("member_id"),
                "procedure_name": result["state"].get("procedure_name"),
                "medication_name": result["state"].get("medication_name"),
                "missing_fields": result["state"].get("missing_fields", [])
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/direct-eligibility-check", methods=["POST"])
def direct_eligibility_check():
    """
    Direct eligibility check (bypassing conversation)
    
    Request body:
    {
        "member_id": "MB123456",
        "date_of_birth": "1985-03-15",
        "procedure_code": "99213" (optional),
        "ndc_code": "00002-7510-01" (optional)
    }
    """
    try:
        data = request.get_json()
        
        mock_api = MockEligibilityAPI()
        result = mock_api.check_eligibility(data)
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error in direct eligibility check: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/test-members", methods=["GET"])
def get_test_members():
    """Get list of test member IDs for testing"""
    try:
        mock_api = MockEligibilityAPI()
        members = mock_api.get_available_members()
        
        return jsonify({
            "test_members": members,
            "note": "These are test member IDs you can use for testing"
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting test members: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/test", methods=["GET"])
def test_endpoint():
    """
    Test endpoint to verify server configuration
    """
    return {
        "server": "Standalone Voice-Enabled Insurance Eligibility Agent",
        "status": "running",
        "configuration": {
            "openai_configured": bool(Config.OPENAI_API_KEY),
            "domain_set": bool(Config.YOUR_DOMAIN and Config.YOUR_DOMAIN != "localhost"),
            "websocket_url": Config.get_websocket_url(),
            "voice_enabled": True,
            "text_api_enabled": True
        },
        "endpoints": {
            "voice": {
                "webhook": f"https://{Config.YOUR_DOMAIN}/voice/incoming",
                "websocket": Config.get_websocket_url(),
                "health": "/voice/health"
            },
            "api": {
                "start_conversation": "/api/conversation/start",
                "send_message": "/api/conversation/<id>/message",
                "direct_check": "/api/direct-eligibility-check",
                "test_members": "/api/test-members"
            }
        },
        "test_members": [
            {"id": "MB123456", "name": "John Doe", "dob": "1985-03-15", "status": "active"},
            {"id": "MB789012", "name": "Jane Smith", "dob": "1990-07-22", "status": "active"},
            {"id": "MB345678", "name": "Robert Johnson", "dob": "1975-11-30", "status": "inactive"}
        ]
    }, 200


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return {"error": "Endpoint not found"}, 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    logger.error(f"Internal server error: {error}")
    return {"error": "Internal server error"}, 500


def validate_environment():
    """Validate environment configuration before starting"""
    errors = []
    warnings = []
    
    # Check required variables
    if not Config.OPENAI_API_KEY:
        errors.append("OPENAI_API_KEY is not set")
    else:
        logger.info(f"✓ OpenAI API key configured")
    
    if not Config.YOUR_DOMAIN or Config.YOUR_DOMAIN == "localhost":
        warnings.append("YOUR_DOMAIN is not set - WebSocket URL will not work with Twilio")
    else:
        logger.info(f"✓ Domain configured: {Config.YOUR_DOMAIN}")
    
    logger.info(f"✓ Port: {Config.PORT}")
    logger.info(f"✓ WebSocket URL: {Config.get_websocket_url()}")
    
    # Print results
    if errors:
        logger.error("❌ Configuration errors:")
        for error in errors:
            logger.error(f"   - {error}")
        return False
    
    if warnings:
        logger.warning("⚠️  Configuration warnings:")
        for warning in warnings:
            logger.warning(f"   - {warning}")
    
    logger.info("✅ Configuration validated successfully")
    return True


if __name__ == "__main__":
    # Validate environment
    if not validate_environment():
        logger.error("Cannot start server due to configuration errors")
        exit(1)
    
    # Create logs directory
    if Config.LOG_FILE:
        log_dir = os.path.dirname(Config.LOG_FILE)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
    
    # Start server
    logger.info(f"🚀 Starting server on {Config.HOST}:{Config.PORT}")
    logger.info(f"🔗 WebSocket URL: {Config.get_websocket_url()}")
    logger.info(f"📝 Configure Twilio webhook to: https://{Config.YOUR_DOMAIN}/voice/incoming")
    logger.info("=" * 80)
    logger.info("📞 Voice calls: Call your Twilio number")
    logger.info("💬 Text API: Use /api/conversation/start endpoint")
    logger.info("=" * 80)
    
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG
    )
