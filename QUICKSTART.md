# Quick Start Guide
Get your standalone voice agent running in 5 minutes!

## 🚀 Setup (One Time)

```bash
# 1. Run setup script
./scripts/setup.sh

# 2. Edit .env file
nano .env

# Add your OPENAI_API_KEY
OPENAI_API_KEY=sk-your-key-here
```

## 🏃 Start Server

```bash
# Development mode
python app.py

# Or use start script
./scripts/start.sh

# Production mode
./scripts/start.sh prod
```

Server runs on: `http://localhost:5000`

## 🧪 Test Without Voice

```bash
# Health check
curl http://localhost:5000/health

# Get test members
curl http://localhost:5000/api/test-members

# Direct eligibility check
curl -X POST http://localhost:5000/api/direct-eligibility-check \
  -H "Content-Type: application/json" \
  -d '{
    "member_id": "MB123456",
    "date_of_birth": "1985-03-15"
  }'

# Start conversation
curl -X POST http://localhost:5000/api/conversation/start \
  -H "Content-Type: application/json" \
  -d '{
    "initial_message": "Check eligibility for MB123456"
  }'
```

## 📞 Enable Voice Calls

```bash
# 1. In a new terminal, start ngrok
ngrok http 5000

# 2. Copy the HTTPS URL (e.g., https://abc123.ngrok.io)

# 3. Update .env
YOUR_DOMAIN=abc123.ngrok.io  # Without https://

# 4. Restart server
python app.py
```

## 🔧 Configure Twilio

1. Go to: https://console.twilio.com/
2. Navigate to: Phone Numbers → Active Numbers
3. Click your phone number
4. Under "Voice Configuration":
   - **A call comes in:** `https://your-ngrok-url.ngrok.io/voice/incoming`
   - **Method:** POST
5. Save

## 📞 Test Voice Call

Call your Twilio phone number! Expected flow:

```
System: "Thank you for calling... connecting you"
AI: "Hello! How can I help you today?"
You: "Check coverage for MB123456"
AI: "What is the date of birth?"
You: "March 15, 1985"
AI: "Great news! The member is eligible..."
```

## 📝 Test Member IDs

```
Active Coverage:
- MB123456, DOB: 1985-03-15 (March 15, 1985)
- MB789012, DOB: 1990-07-22 (July 22, 1990)

Inactive Coverage:
- MB345678, DOB: 1975-11-30 (November 30, 1975)
```

## 🐛 Troubleshooting

### Server won't start
```bash
# Check environment
python -c "from config import Config; Config.validate()"

# Check dependencies
pip install -r requirements.txt --upgrade
```

### Voice not working
```bash
# Check logs
tail -f logs/app.log

# Verify ngrok is running
# Verify Twilio webhook is set correctly
# Verify YOUR_DOMAIN in .env matches ngrok
```

### No audio
```bash
# Test audio conversion
python tests/test_audio.py
```

## 🎯 What's Next?

- Add more test members in `api/eligibility_api.py`
- Customize voice in `config.py`
- Deploy to production (see README.md)
- Add authentication
- Integrate with real insurance API

## 📚 More Info

- Full documentation: `README.md`
- Architecture details: `PROJECT_OVERVIEW.md`
- Code is well-commented - read through it!

---

**That's it! You're ready to go! 🎉**
