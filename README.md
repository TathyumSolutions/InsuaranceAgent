# Standalone Insurance Eligibility Voice Agent

A **complete, self-contained** AI-powered insurance eligibility verification system with voice and text interfaces. This standalone project requires NO external backend - everything runs in one application.

## 🎯 What This Is

A single application that provides:
- **Voice Interface**: Call via phone to check insurance eligibility
- **Text/Chat API**: REST API for programmatic access
- **LangGraph Agent**: Intelligent conversation flow management
- **Mock Insurance API**: Realistic eligibility responses

**No separate backend needed** - this is a complete, ready-to-deploy solution.

## 🌟 Key Features

✅ **Fully Standalone** - All components integrated in one application
✅ **Voice Calling** - Natural phone conversations via Twilio + OpenAI
✅ **Intelligent Agent** - LangGraph-powered conversation management
✅ **Dual Interface** - Both voice calls AND REST API
✅ **Production Ready** - Docker, logging, error handling, health checks
✅ **Complete Testing** - Audio conversion tests and API tests included

## 📐 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Standalone Application                       │
│                        (Port 5000)                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐         ┌──────────────┐                    │
│  │ Voice        │         │  Text/Chat   │                    │
│  │ Interface    │         │  REST API    │                    │
│  │ (Twilio)     │         │              │                    │
│  └──────┬───────┘         └──────┬───────┘                    │
│         │                        │                             │
│         └────────┬───────────────┘                             │
│                  │                                              │
│         ┌────────▼──────────┐                                  │
│         │  LangGraph Agent  │                                  │
│         │  - State Machine  │                                  │
│         │  - Info Extract   │                                  │
│         │  - Conversation   │                                  │
│         └────────┬──────────┘                                  │
│                  │                                              │
│         ┌────────▼──────────┐                                  │
│         │ Eligibility API   │                                  │
│         │  - Member Data    │                                  │
│         │  - Coverage Info  │                                  │
│         │  - Benefits       │                                  │
│         └───────────────────┘                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### Prerequisites

- Python 3.9+
- OpenAI API key (with Realtime API access)
- Twilio account with phone number (for voice calls)
- ngrok (for local testing) or public domain (for production)

### Installation

```bash
# 1. Clone or extract the project
cd standalone-voice-agent

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
nano .env  # Add your OPENAI_API_KEY
```

### Running Locally

```bash
# Start the application
python app.py

# Or use the start script
./scripts/start.sh
```

The server will start on `http://localhost:5000`

### Test Without Phone Calls

You can test the intelligence without making phone calls:

```bash
# Check health
curl http://localhost:5000/health

# Start a conversation
curl -X POST http://localhost:5000/api/conversation/start \
  -H "Content-Type: application/json" \
  -d '{"initial_message": "Check eligibility for MB123456"}'

# Get test members
curl http://localhost:5000/api/test-members
```

### Enable Voice Calls

```bash
# 1. Expose your local server
ngrok http 5000

# 2. Copy the ngrok URL (e.g., https://abc123.ngrok.io)

# 3. Update .env
YOUR_DOMAIN=abc123.ngrok.io

# 4. Restart app
python app.py

# 5. Configure Twilio
# Go to: https://console.twilio.com/
# Phone Numbers → Your Number
# Voice webhook: https://abc123.ngrok.io/voice/incoming
```

Now call your Twilio number! 📞

## 📋 Test Member IDs

```
Active Coverage - Partial Deductible:
Member ID: MB123456
DOB: 1985-03-15 (or "March 15, 1985")
Name: John Doe

Active Coverage - Full Deductible Met:
Member ID: MB789012
DOB: 1990-07-22 (or "July 22, 1990")
Name: Jane Smith

Inactive Coverage:
Member ID: MB345678
DOB: 1975-11-30 (or "November 30, 1975")
Name: Robert Johnson
```

## 🎯 Example Interactions

### Voice Call Example

```
You: [Call your Twilio number]
System: "Thank you for calling... connecting you to our AI assistant"
AI: "Hello! How can I help you check insurance coverage today?"
You: "I need to check coverage for member MB123456"
AI: "I can help with that! What is the member's date of birth?"
You: "March 15, 1985"
AI: "Great news! John Doe is eligible and coverage is active..."
```

### Text API Example

```bash
# Start conversation
curl -X POST http://localhost:5000/api/conversation/start \
  -H "Content-Type: application/json" \
  -d '{
    "initial_message": "Is MB123456 covered for an MRI?"
  }'

# Response
{
  "conversation_id": "uuid-here",
  "response": "I can help with that! What is the patient's date of birth?",
  "eligibility_determined": false
}

# Continue conversation
curl -X POST http://localhost:5000/api/conversation/{uuid}/message \
  -H "Content-Type: application/json" \
  -d '{
    "message": "March 15, 1985"
  }'

# Response
{
  "response": "Great news! The patient is eligible...",
  "eligibility_determined": true,
  "api_response": {...}
}
```

## 📁 Project Structure

```
standalone-voice-agent/
├── app.py                     # Main unified application
├── config.py                  # Unified configuration
├── requirements.txt           # All dependencies
├── .env.example               # Environment template
│
├── agent/                     # LangGraph Agent
│   ├── __init__.py
│   ├── eligibility_agent.py  # Main agent logic
│   ├── state.py              # Conversation state
│   └── prompts.py            # System prompts
│
├── api/                       # Mock Insurance API
│   ├── __init__.py
│   └── eligibility_api.py    # Eligibility checks
│
├── voice/                     # Voice Components
│   ├── __init__.py
│   ├── handler.py            # OpenAI voice handler
│   └── twilio_manager.py     # Twilio WebSocket
│
├── utils/                     # Utilities
│   ├── __init__.py
│   ├── audio_utils.py        # Audio conversion
│   └── logger.py             # Logging setup
│
├── tests/                     # Test suite
│   ├── __init__.py
│   ├── test_audio.py         # Audio tests
│   └── test_api.py           # API tests
│
├── scripts/                   # Helper scripts
│   ├── setup.sh              # Setup script
│   └── start.sh              # Start script
│
└── deployment/                # Production deployment
    ├── Dockerfile            # Container definition
    ├── docker-compose.yml    # Multi-service setup
    └── nginx.conf            # Reverse proxy
```

## 🔧 API Endpoints

### Voice Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/voice/health` | GET | Voice service health check |
| `/voice/incoming` | POST | Twilio webhook (TwiML) |
| `/voice/status` | POST | Call status callback |
| `/voice/stream` | WebSocket | Media stream |

### Text/Chat API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | General health check |
| `/api/conversation/start` | POST | Start new conversation |
| `/api/conversation/<id>/message` | POST | Continue conversation |
| `/api/direct-eligibility-check` | POST | Direct eligibility check |
| `/api/test-members` | GET | Get test member IDs |
| `/test` | GET | Configuration test |

## 🧪 Testing

### Run Tests

```bash
# Audio conversion tests
python tests/test_audio.py

# API integration tests
python tests/test_api.py
```

### Manual Testing

```bash
# 1. Test health
curl http://localhost:5000/health

# 2. Get test members
curl http://localhost:5000/api/test-members

# 3. Direct eligibility check
curl -X POST http://localhost:5000/api/direct-eligibility-check \
  -H "Content-Type: application/json" \
  -d '{
    "member_id": "MB123456",
    "date_of_birth": "1985-03-15"
  }'
```

## 🚀 Production Deployment

### Option 1: Docker

```bash
# Build
docker build -t insurance-voice:latest -f deployment/Dockerfile .

# Run
docker run -d \
  -p 5000:5000 \
  --env-file .env \
  --name insurance-voice \
  insurance-voice:latest
```

### Option 2: Docker Compose

```bash
cd deployment
docker-compose up -d
```

### Option 3: Cloud Platform

**AWS Elastic Beanstalk:**
```bash
eb init -p python-3.9 insurance-voice
eb create insurance-voice-env
eb deploy
```

**Google Cloud Run:**
```bash
gcloud run deploy insurance-voice \
  --source . \
  --platform managed \
  --region us-central1
```

**Heroku:**
```bash
heroku create insurance-voice
git push heroku main
```

## 🔐 Security

### Production Checklist

- [ ] Use HTTPS only (no WS://, only WSS://)
- [ ] Set strong environment variables
- [ ] Enable Twilio signature validation
- [ ] Implement rate limiting
- [ ] Set up firewall rules
- [ ] Enable audit logging
- [ ] Encrypt sensitive data
- [ ] Regular security updates

### Environment Variables

**Never commit:**
- `.env` file
- API keys
- Passwords
- Certificates

## 📊 Monitoring

### Logs

```bash
# Real-time logs
tail -f logs/app.log

# Errors only
grep ERROR logs/app.log

# Call statistics
grep "Call ended" logs/app.log
```

### Metrics to Track

- Total calls per day
- Average call duration
- Eligibility check success rate
- API response time
- Error rate

## 🔧 Configuration

### Environment Variables

See `.env.example` for all options. Key variables:

```env
# Required
OPENAI_API_KEY=sk-...

# For production
YOUR_DOMAIN=voice.yourcompany.com
PORT=5000

# Optional
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
LOG_LEVEL=INFO
```

### Audio Settings

Adjust in `.env` if needed:

```env
VAD_THRESHOLD=0.5          # Voice detection sensitivity
SILENCE_DURATION_MS=700    # Silence before AI responds
AUDIO_SAMPLE_RATE=16000    # Audio quality
```

## 🐛 Troubleshooting

### App Won't Start

**Check Python version:**
```bash
python --version  # Should be 3.9+
```

**Check dependencies:**
```bash
pip install -r requirements.txt --upgrade
```

**Check environment:**
```bash
python -c "from config import Config; Config.validate()"
```

### Voice Calls Not Working

**Check ngrok:**
```bash
# ngrok should show forwarding to port 5000
ngrok http 5000
```

**Check Twilio webhook:**
- Must be HTTPS (ngrok provides this)
- Must end with `/voice/incoming`
- Must be POST method

**Check logs:**
```bash
tail -f logs/app.log | grep -E "Call|ERROR"
```

### Audio Issues

**Test audio conversion:**
```bash
python tests/test_audio.py
```

**Check OpenAI connection:**
- Verify API key is valid
- Check if you have Realtime API access
- Review OpenAI usage limits

## 💰 Cost Estimate

Per call (5 minutes average):
- **Twilio**: ~$0.04
- **OpenAI Realtime**: ~$0.30
- **Infrastructure**: ~$0.01
- **Total**: ~$0.35 per call

Monthly (1000 calls):
- Twilio: $40
- OpenAI: $300
- Infrastructure: $100
- **Total**: ~$440/month

## 📚 How It Works

### Voice Call Flow

1. **Call Received**: Twilio receives call, hits `/voice/incoming`
2. **TwiML Response**: Server returns TwiML to connect to WebSocket
3. **WebSocket Opens**: Twilio streams audio to `/voice/stream`
4. **Audio Processing**: 
   - Twilio sends mulaw 8kHz audio
   - Converted to PCM16 16kHz
   - Sent to OpenAI Realtime API
5. **AI Processing**:
   - OpenAI transcribes speech
   - Generates responses
   - Calls functions when needed
6. **Eligibility Check**:
   - Function call triggers agent
   - Agent calls mock API
   - Results formatted for speech
7. **Response**:
   - OpenAI generates audio
   - Converted back to mulaw 8kHz
   - Sent to Twilio
   - User hears response

### Agent Intelligence

The LangGraph agent:
1. Extracts information from user messages
2. Resolves procedure/medication names to codes
3. Determines what information is still needed
4. Calls eligibility API when ready
5. Validates if query was answered
6. Generates natural language responses

## 🎓 Documentation

- See `PROJECT_OVERVIEW.md` for architecture details
- See `QUICKSTART.md` for setup guide
- See code comments for implementation details

## 📝 License

This is a production-ready POC. Adapt as needed for your use case.

## 🆘 Support

**Having issues?**

1. Check logs: `tail -f logs/app.log`
2. Run tests: `python tests/test_audio.py`
3. Check configuration: `curl http://localhost:5000/test`
4. Review this README

**Common Issues:**
- "OPENAI_API_KEY not set" → Check `.env` file
- "Cannot connect to Twilio" → Check webhook URL
- "No audio" → Run audio tests
- "Port in use" → Change PORT in `.env`

## 🎉 What Makes This Special

✅ **Truly Standalone** - No separate backend needed
✅ **Dual Interface** - Voice AND text API
✅ **Production Ready** - Docker, logging, monitoring
✅ **Complete** - Agent + API + Voice all integrated
✅ **Well Documented** - README, comments, examples
✅ **Tested** - Audio and API tests included

---

**Ready to deploy! 🚀**
