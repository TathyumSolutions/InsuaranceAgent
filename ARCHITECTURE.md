# Technical Architecture - Insurance Eligibility Voice Agent

## 1. System Overview

A standalone, AI-powered insurance eligibility verification system that provides two interfaces:

- **Voice** - Phone calls via Twilio + OpenAI Realtime API
- **Text/Chat** - REST API powered by a LangGraph conversation agent

All components (web server, AI agent, mock eligibility API, audio processing) run within a single Flask process. No external backend services are required beyond OpenAI and Twilio.

```
+---------------------------------------------------------------------+
|                         Flask Application                           |
|                          (Port 5000)                                |
|                                                                     |
|  +------------------+    +-------------------+    +---------------+ |
|  |  Voice Endpoints |    |  Text/Chat API    |    |  Utility      | |
|  |  /voice/*        |    |  /api/*           |    |  /health      | |
|  +--------+---------+    +---------+---------+    |  /test        | |
|           |                        |              +---------------+ |
|           v                        v                                |
|  +------------------+    +-------------------+                      |
|  | TwilioWSManager  |    | EligibilityAgent  |                      |
|  |  (voice/)        |    |  (agent/)         |                      |
|  +--------+---------+    +---------+---------+                      |
|           |                        |                                |
|           v                        |                                |
|  +------------------+              |                                |
|  |  VoiceHandler    |              |                                |
|  |  (voice/)        |              |                                |
|  +--------+---------+              |                                |
|           |                        |                                |
|           v                        v                                |
|  +------------------------------------------------+                |
|  |           MockEligibilityAPI (api/)             |                |
|  |   Members | Procedures (CPT) | Drugs (NDC)     |                |
|  +------------------------------------------------+                |
+---------------------------------------------------------------------+
          |                    |
          v                    v
   +-----------+        +-------------+
   |  Twilio   |        |   OpenAI    |
   |  (Phone)  |        | GPT-4 / RT  |
   +-----------+        +-------------+
```

---

## 2. Technology Stack

| Layer              | Technology                         | Version  |
|--------------------|------------------------------------|----------|
| Web Framework      | Flask + Flask-Sock + Flask-CORS    | 3.1.0    |
| AI (Text/Chat)     | OpenAI GPT-4 Turbo via LangChain  | 0.3.7    |
| AI (Voice)         | OpenAI Realtime API (gpt-4o)       | 1.57.4   |
| Agent Framework    | LangGraph (state machine)          | 0.2.53   |
| Telephony          | Twilio (voice + WebSocket media)   | 9.3.6    |
| WebSocket Client   | websockets                         | 14.1     |
| Audio Processing   | audioop (stdlib)                   | built-in |
| Configuration      | python-dotenv                      | 1.0.1    |
| Production Server  | Gunicorn                           | 23.0.0   |
| Containerization   | Docker (Python 3.11-slim)          | -        |
| Testing            | pytest + pytest-asyncio            | 8.3.4    |

---

## 3. Directory Structure

```
InsuaranceAgent/
|
+-- app.py                          # Flask application entry point
+-- config.py                       # Centralized configuration
+-- requirements.txt                # Python dependencies
+-- .env.example                    # Environment variable template
|
+-- agent/                          # LangGraph Conversation Agent
|   +-- eligibility_agent.py        #   7-node state machine
|   +-- state.py                    #   ConversationState TypedDict
|   +-- prompts.py                  #   LLM prompt templates
|
+-- api/                            # Mock Insurance API
|   +-- eligibility_api.py          #   Eligibility verification + code resolution
|
+-- voice/                          # Voice / Telephony
|   +-- handler.py                  #   OpenAI Realtime API handler
|   +-- twilio_manager.py           #   Twilio WebSocket manager
|
+-- utils/                          # Shared Utilities
|   +-- audio_utils.py              #   Audio format conversion (mulaw/PCM16)
|   +-- logger.py                   #   Colored + rotating file logger
|
+-- tests/                          # Test Suite
|   +-- test_api.py                 #   API + agent tests
|   +-- test_audio.py               #   Audio conversion tests
|
+-- deployment/                     # Deployment
|   +-- Dockerfile                  #   Production container
|
+-- scripts/                        # Helper Scripts
    +-- setup.sh                    #   Initial setup
    +-- start.sh                    #   Server startup
```

---

## 4. Component Architecture

### 4.1 Flask Application (`app.py`)

The single entry point that initializes all components and exposes all endpoints on port 5000.

**Responsibilities:**
- HTTP endpoint routing
- WebSocket connection handling via Flask-Sock
- Conversation state storage (in-memory dictionary)
- TwiML response generation for Twilio
- Environment validation on startup

**Endpoint Map:**

```
Port 5000
|
+-- Voice Endpoints
|   +-- POST   /voice/incoming       Twilio webhook (returns TwiML)
|   +-- WS     /voice/stream         Twilio media stream (WebSocket)
|   +-- POST   /voice/status         Call status callbacks
|   +-- GET    /voice/health         Voice service health check
|
+-- Text/Chat API
|   +-- POST   /api/conversation/start            Start new conversation
|   +-- POST   /api/conversation/<id>/message      Continue conversation
|   +-- POST   /api/direct-eligibility-check       Direct API check (no agent)
|   +-- GET    /api/test-members                   List test members
|
+-- Utility
    +-- GET    /health               General health check
    +-- GET    /test                  Server configuration + test data
```

### 4.2 LangGraph Agent (`agent/`)

A 7-node state machine that manages multi-turn text conversations. Uses GPT-4 Turbo for NLU.

**State Machine Graph:**

```
                    +---------------------+
                    |  extract_information |
                    |  (LLM: extract data |
                    |   from user message)|
                    +---------+-----------+
                              |
                              v
                    +---------------------+
                    |   resolve_codes     |
                    | (deterministic:     |
                    |  name -> CPT/NDC)   |
                    +---------+-----------+
                              |
                              v
                    +---------------------+
                    | determine_next_action|
                    |  (check missing     |
                    |   fields, route)    |
                    +---------+-----------+
                              |
               +--------------+--------------+
               |              |              |
               v              v              v
      +--------+---+  +------+------+  +----+--------+
      |gather_more |  |  call_api   |  | generate_   |
      |  _info     |  |  (Mock API) |  | final_resp  |
      |(ask user)  |  +------+------+  | (LLM format)|
      +-----+------+         |         +------+------+
            |                v                 |
            |        +------+------+           |
            |        |  validate   |           |
            |        |  _response  |           |
            |        | (LLM check) |           |
            |        +------+------+           |
            |               |                  |
            v               v                  v
          [END]           [END]              [END]
```

**Node Details:**

| Node | Type | Function |
|------|------|----------|
| `extract_information` | LLM | Parse member_id, DOB, procedure/medication names from user text |
| `resolve_codes` | Deterministic | Fuzzy-match procedure/medication names to CPT/NDC codes |
| `determine_next_action` | Logic | Route to gather_info, call_api, or complete |
| `gather_more_info` | LLM | Generate conversational prompt asking for missing fields |
| `call_api` | API Call | Call MockEligibilityAPI with collected data |
| `validate_response` | LLM | Check if API response answers the user's query |
| `generate_final_response` | LLM | Format API response into natural language |

**ConversationState (TypedDict):**

```
ConversationState
+-- messages[]              List of {role, content, timestamp}
+-- conversation_id         UUID
+-- member_id               "MB123456"
+-- date_of_birth           "1985-03-15"
+-- policy_number           Optional
+-- service_type            "medical" | "pharmacy" | "general"
+-- procedure_code          CPT code (e.g., "70553")
+-- procedure_name          Human name (e.g., "MRI")
+-- ndc_code                NDC code (e.g., "50090-3568-00")
+-- medication_name         Human name (e.g., "Humira")
+-- service_date            "YYYY-MM-DD"
+-- provider_npi            Optional
+-- provider_name           Optional
+-- missing_fields[]        Fields still needed
+-- api_called              Boolean
+-- api_response            Raw API response dict
+-- eligibility_determined  Boolean
+-- next_action             "gather_info" | "call_api" | "validate_response" | "complete"
```

### 4.3 Voice Pipeline (`voice/`)

Bridges Twilio phone calls with OpenAI's Realtime API for real-time speech-to-speech interaction.

**Threading Model:**

```
+-------------------+          +--------------------+
|   Main Thread     |          |   Voice Thread     |
|   (Flask/Sync)    |          |   (asyncio loop)   |
|                   |          |                    |
| TwilioWSManager   |  ------> |   VoiceHandler     |
|  .handle_conn()   | audio    |  .connect_and_run()|
|  receives Twilio  | chunks   |  sends/receives    |
|  WebSocket msgs   |          |  OpenAI WebSocket  |
|                   | <------  |                    |
|  sends audio back | callback |  processes events  |
|  to Twilio        |          |  + function calls  |
+-------------------+          +--------------------+
```

**Audio Format Pipeline:**

```
Caller's Phone
    |  (analog voice)
    v
Twilio
    |  mulaw 8kHz (base64 JSON over WebSocket)
    v
TwilioWebSocketManager._handle_media()
    |  AudioConverter.twilio_to_openai()
    |  mulaw 8kHz -> PCM16 8kHz -> PCM16 24kHz
    v
VoiceHandler.send_audio_from_user()
    |  base64 PCM16 24kHz (JSON over WebSocket)
    v
OpenAI Realtime API
    |  (speech recognition + LLM + TTS)
    |  PCM16 24kHz response audio
    v
VoiceHandler._handle_audio_delta()
    |  AudioConverter.openai_24k_to_twilio()
    |  PCM16 24kHz -> PCM16 8kHz -> mulaw 8kHz
    v
TwilioWebSocketManager._send_audio_to_twilio()
    |  mulaw 8kHz (base64 JSON over WebSocket)
    v
Twilio -> Caller's Phone
```

**OpenAI Session Configuration:**

```
Session Config
+-- modalities: ["text", "audio"]
+-- voice: "alloy"
+-- input_audio_format: "pcm16"
+-- output_audio_format: "pcm16"
+-- turn_detection: server_vad (threshold: 0.5, silence: 700ms)
+-- transcription: whisper-1
+-- tools: [check_eligibility function]
```

**Voice Function Calling Flow:**

```
1. Caller says: "Check eligibility for MB123456, born March 15 1985, for an MRI"
                            |
2. OpenAI transcribes speech + triggers function call:
   check_eligibility(member_id="MB123456", date_of_birth="1985-03-15", procedure_name="MRI")
                            |
3. VoiceHandler._handle_function_call()
   +-- resolve_procedure_code("MRI")  ->  CPT "70553"
   +-- check_eligibility({member_id, dob, procedure_code})
   +-- _format_eligibility_for_speech(result)
                            |
4. Result sent back to OpenAI as function_call_output
                            |
5. OpenAI generates speech response -> streamed back to caller
```

### 4.4 Mock Eligibility API (`api/eligibility_api.py`)

In-memory mock simulating real X12 270/271 insurance eligibility responses.

**Data Model:**

```
MockEligibilityAPI
|
+-- mock_database (3 members)
|   +-- MB123456: John Doe   (Active, PPO, partial deductible)
|   +-- MB789012: Jane Smith  (Active, HMO, full deductible met)
|   +-- MB345678: Robert Johnson (Inactive)
|
+-- procedure_coverage (11 CPT codes)
|   +-- 99213: Office Visit              (covered, no auth)
|   +-- 99214: Office Visit Detailed     (covered, no auth)
|   +-- 99285: Emergency Dept Visit      (covered, no auth)
|   +-- 80053: Metabolic Panel           (covered, no auth)
|   +-- 71045: Chest X-Ray              (covered, no auth)
|   +-- 70450: CT Head                   (covered, auth required)
|   +-- 70553: MRI Brain                (covered, auth required)
|   +-- 27447: Total Knee Replacement   (covered, auth required)
|   +-- J1745: Infliximab Injection     (covered, auth required)
|   +-- J9035: Bevacizumab Injection    (NOT covered)
|   +-- G0438: Annual Wellness Visit    (covered, no auth)
|
+-- drug_coverage (6 NDC codes)
    +-- 00002-7510-01: Atorvastatin 20mg   (Tier 1, $10)
    +-- 00069-0950-68: Metformin 500mg     (Tier 1, $10)
    +-- 00069-1530-01: Lisinopril 10mg     (Tier 1, $10)
    +-- 50090-3568-00: Humira 40mg         (Tier 3, $150, auth)
    +-- 00052-0602-02: Eliquis 5mg         (Tier 2, $45)
    +-- 12345-6789-00: Experimental Drug   (NOT covered)
```

**Code Resolution (Fuzzy Matching):**

```
User says "MRI"
    |
    v
resolve_procedure_code("MRI")
    |  iterates procedure_coverage
    |  checks: "mri" in "mri brain".lower()  ->  match
    v
Returns: {code: "70553", name: "MRI Brain"}
```

**API Response Structure:**

```
check_eligibility() Response
+-- status: "success" | "error"
+-- eligibility_status: "eligible" | "not_eligible" | "eligible_with_conditions" | "not_covered"
+-- response_code: "200" | "201" | "400"
+-- member_info: {member_id, name, dob, policy_number}
+-- coverage_info: {status, plan_type, effective_date, termination_date}
+-- financial_info:
|   +-- deductible: {individual, met, remaining}
|   +-- out_of_pocket: {max, met, remaining}
|   +-- copays: {primary_care, specialist}
+-- service_specific:           (if procedure_code provided)
|   +-- {procedure_code, procedure_name, covered, requires_prior_authorization, benefit_details}
+-- pharmacy_specific:          (if ndc_code provided)
    +-- {ndc_code, medication_name, covered, formulary_tier, copay_amount, requires_prior_authorization}
```

### 4.5 Audio Utilities (`utils/audio_utils.py`)

Handles all audio format conversions between Twilio (mulaw 8kHz) and OpenAI (PCM16 24kHz).

```
AudioConverter (static methods)
|
+-- twilio_to_openai()       mulaw 8kHz  ->  PCM16 24kHz
+-- openai_24k_to_twilio()   PCM16 24kHz ->  mulaw 8kHz
+-- openai_to_twilio()       PCM16 16kHz ->  mulaw 8kHz  (legacy)

Helper Functions:
+-- ulaw_to_pcm16()              mulaw -> PCM16
+-- pcm16_to_ulaw()              PCM16 -> mulaw
+-- resample_8khz_to_24khz()     8kHz  -> 24kHz
+-- resample_24khz_to_8khz()     24kHz -> 8kHz
+-- resample_8khz_to_16khz()     8kHz  -> 16kHz
+-- resample_16khz_to_8khz()     16kHz -> 8kHz
+-- validate_audio_data()        Check PCM16 validity
+-- get_audio_duration()         Calculate duration in seconds
```

### 4.6 Configuration (`config.py`)

Centralized environment-driven configuration loaded from `.env`.

```
Config
+-- OpenAI
|   +-- OPENAI_API_KEY              (required)
|   +-- OPENAI_MODEL                "gpt-4-turbo-preview"
|   +-- OPENAI_REALTIME_MODEL       "gpt-4o-realtime-preview-2024-10-01"
|   +-- OPENAI_REALTIME_URL         "wss://api.openai.com/v1/realtime"
|
+-- Twilio
|   +-- TWILIO_ACCOUNT_SID          (for voice calls)
|   +-- TWILIO_AUTH_TOKEN            (for voice calls)
|
+-- Server
|   +-- YOUR_DOMAIN                 Public domain for Twilio webhooks
|   +-- PORT                        5000
|   +-- HOST                        0.0.0.0
|   +-- DEBUG                       false
|
+-- Audio
|   +-- AUDIO_SAMPLE_RATE           24000
|   +-- VAD_THRESHOLD               0.5
|   +-- SILENCE_DURATION_MS         700
|
+-- Session
|   +-- SESSION_TIMEOUT_SECONDS     300
|   +-- MAX_CONCURRENT_CALLS        50
|
+-- Logging
    +-- LOG_LEVEL                   INFO
    +-- LOG_FILE                    logs/app.log
```

---

## 5. Data Flow Diagrams

### 5.1 Voice Call - End to End

```
Caller                Twilio               Flask App            OpenAI Realtime
  |                     |                     |                       |
  |--- Dials number --->|                     |                       |
  |                     |--- POST /voice/ --->|                       |
  |                     |    incoming          |                       |
  |                     |<--- TwiML (Say +    |                       |
  |                     |     Connect/Stream) |                       |
  |<-- "Thank you..." --|                     |                       |
  |                     |--- WS /voice/ ----->|                       |
  |                     |    stream           |                       |
  |                     |                     |--- WSS connect ------>|
  |                     |                     |<-- session.created ---|
  |                     |                     |--- session.update --->|
  |                     |                     |    (tools, voice,    |
  |                     |                     |     VAD config)      |
  |                     |                     |                       |
  |=== Speaking =======>|=== mulaw 8kHz ====>|=== PCM16 24kHz ====>|
  |                     |                     |                       |
  |                     |                     |    [If function call] |
  |                     |                     |<-- check_eligibility -|
  |                     |                     |    {member_id, dob}   |
  |                     |                     |                       |
  |                     |                     |--- MockEligibilityAPI |
  |                     |                     |    .check_eligibility()|
  |                     |                     |                       |
  |                     |                     |--- function_call  --->|
  |                     |                     |    output (result)    |
  |                     |                     |                       |
  |<== AI speaks =======|<== mulaw 8kHz =====|<== PCM16 24kHz ======|
  |                     |                     |                       |
  |--- Hangs up ------->|--- stop event ----->|--- close WS -------->|
```

### 5.2 Text/Chat API - End to End

```
Client                          Flask App                    OpenAI (GPT-4)
  |                                |                              |
  |-- POST /api/conversation/ ---->|                              |
  |   start                        |                              |
  |   {initial_message}            |                              |
  |                                |-- EligibilityAgent           |
  |                                |   .process_message()         |
  |                                |                              |
  |                                |   [extract_information] ---->|
  |                                |   <-- extracted fields ------|
  |                                |                              |
  |                                |   [resolve_codes]            |
  |                                |   (fuzzy match, no LLM)     |
  |                                |                              |
  |                                |   [determine_next_action]    |
  |                                |   -> "call_api" or           |
  |                                |      "gather_info"           |
  |                                |                              |
  |                                |   [call_api]                 |
  |                                |   MockEligibilityAPI         |
  |                                |   .check_eligibility()       |
  |                                |                              |
  |                                |   [validate_response] ------>|
  |                                |   <-- answers_query: true ---|
  |                                |                              |
  |                                |   [generate_final_response]->|
  |                                |   <-- natural language ------|
  |                                |                              |
  |<-- {conversation_id,       ----|                              |
  |     response,                  |                              |
  |     eligibility_determined,    |                              |
  |     api_response}              |                              |
  |                                |                              |
  |-- POST /api/conversation/ ---->|  (continues with state)      |
  |   <id>/message                 |                              |
```

---

## 6. Deployment Architecture

### 6.1 Docker

```
+----------------------------------+
|  Docker Container                |
|  python:3.11-slim                |
|                                  |
|  +----------------------------+  |
|  | Gunicorn (4 workers)       |  |
|  | --bind 0.0.0.0:5000        |  |
|  | --timeout 300              |  |
|  |                            |  |
|  |  +----------------------+  |  |
|  |  | Flask App (app:app)  |  |  |
|  |  +----------------------+  |  |
|  +----------------------------+  |
|                                  |
|  HEALTHCHECK: /health            |
|  EXPOSE: 5000                    |
+----------------------------------+
         |
    Outbound connections:
    +-- wss://api.openai.com (Realtime API)
    +-- https://api.openai.com (Chat API)
    +-- Twilio WebSocket (inbound from Twilio)
```

### 6.2 Network Topology (Production)

```
                Internet
                   |
            +------+------+
            |   Twilio    |
            | (Phone #)   |
            +------+------+
                   |
     HTTPS webhook | WSS media stream
                   |
            +------+------+
            |  Reverse    |
            |  Proxy      |
            |  (nginx)    |
            +------+------+
                   |
            +------+------+
            |  Flask App  |
            |  Port 5000  |
            +------+------+
              |         |
     +--------+    +----+--------+
     | OpenAI |    | OpenAI      |
     | Chat   |    | Realtime    |
     | API    |    | API (WSS)   |
     +--------+    +-------------+
```

---

## 7. State Management

### 7.1 Conversation State (Text API)

```
In-Memory Dictionary (app.py)
conversation_states: Dict[str, ConversationState]

  "uuid-1" -> {member_id: "MB123456", dob: "1985-03-15", ...}
  "uuid-2" -> {member_id: None, missing_fields: ["member_id", "dob"], ...}
  "uuid-3" -> {eligibility_determined: True, api_response: {...}, ...}
```

> **Note:** State is lost on server restart. Production deployments should use Redis or a database.

### 7.2 Voice Call State

Each voice call is self-contained within the `VoiceHandler` instance. State lives for the duration of the WebSocket connection and is discarded when the call ends.

---

## 8. Security Considerations

| Area | Current State | Recommendation |
|------|--------------|----------------|
| API Authentication | None | Add API key or JWT middleware |
| Rate Limiting | None | Add Flask-Limiter |
| CORS | Allow all origins | Restrict to known domains |
| Input Validation | Basic (DOB format, member ID) | Add request schema validation |
| Secrets Management | .env file | Use vault or cloud secrets manager |
| HTTPS | Not enforced in app | Handled by reverse proxy |
| HIPAA Compliance | Mentioned in prompts only | Add audit logging, encryption at rest |

---

## 9. External Dependencies

```
+---------------------------------------------------+
|              Application Runtime                   |
+---------------------------------------------------+
         |                          |
         v                          v
+------------------+     +---------------------+
| OpenAI API       |     | Twilio              |
| (REQUIRED)       |     | (VOICE ONLY)        |
|                  |     |                     |
| - GPT-4 Turbo   |     | - Phone number      |
|   (text/chat)    |     | - Webhook URL       |
| - GPT-4o RT     |     | - Media Streams     |
|   (voice)        |     |   (WebSocket)       |
| - Whisper-1     |     |                     |
|   (transcription)|     |                     |
+------------------+     +---------------------+
```

**Without Twilio:** Text/Chat API works fully. Voice calls are unavailable.
**Without OpenAI:** Nothing works. Both text and voice require OpenAI.

---

## 10. Logging Architecture

```
Logger (colorlog + RotatingFileHandler)
|
+-- Console: Colored output (green=INFO, red=ERROR, yellow=WARN)
+-- File: logs/app.log (10MB max, 5 rotated backups)
|
+-- Per-call logger: get_call_logger(call_sid)
    Adds call SID context to all log entries for that call
```
