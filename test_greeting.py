"""
Test script to verify the initial greeting functionality
This script tests the voice handler's greeting trigger mechanism
"""
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock
from voice.handler import VoiceHandler
from config import Config


async def test_greeting_trigger():
    """Test that the greeting trigger is properly sent when session is updated"""
    
    print("🧪 Testing Initial Greeting Trigger...")
    
    # Create a mock voice handler
    handler = VoiceHandler(
        call_sid="test_call_123",
        conversation_id="test_conv_456", 
        twilio_callback=MagicMock(),
        openai_api_key="test_key"
    )
    
    # Mock the websocket
    mock_ws = AsyncMock()
    handler.ws = mock_ws
    handler.openai_connected = True
    
    # Test the greeting trigger method
    try:
        await handler._trigger_initial_greeting()
        
        # Verify that two messages were sent (greeting trigger + response create)
        assert mock_ws.send.call_count == 2, f"Expected 2 calls to ws.send, got {mock_ws.send.call_count}"
        
        # Get the sent messages
        calls = mock_ws.send.call_args_list
        
        # Check first message (conversation.item.create)
        first_msg = json.loads(calls[0][0][0])
        assert first_msg["type"] == "conversation.item.create", "First message should be conversation.item.create"
        assert "Call connected" in first_msg["item"]["content"][0]["text"], "Should contain greeting trigger text"
        
        # Check second message (response.create)
        second_msg = json.loads(calls[1][0][0]) 
        assert second_msg["type"] == "response.create", "Second message should be response.create"
        assert second_msg["response"]["modalities"] == ["audio"], "Should request audio response"
        
        print("✅ Greeting trigger test passed!")
        print(f"📤 First message (trigger): {first_msg['type']}")
        print(f"🎤 Second message (response): {second_msg['type']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Greeting trigger test failed: {e}")
        return False


def test_system_instructions():
    """Test that system instructions emphasize immediate greeting"""
    
    print("\n🧪 Testing System Instructions...")
    
    instructions = Config.VOICE_SYSTEM_INSTRUCTIONS
    
    # Check for key phrases that ensure immediate greeting
    checks = [
        ("IMMEDIATELY start speaking", "Instructions should emphasize immediate start"),
        ("Do NOT wait for the user", "Should explicitly tell not to wait"),
        ("START IMMEDIATELY WHEN CALL CONNECTS", "Should have clear start trigger"),
        ("within 1-2 seconds", "Should specify timing")
    ]
    
    all_passed = True
    for check_text, description in checks:
        if check_text in instructions:
            print(f"✅ {description}")
        else:
            print(f"❌ Missing: {description}")
            all_passed = False
    
    return all_passed


async def main():
    """Run all tests"""
    print("🧪 Testing Voice Agent Greeting Improvements\n")
    
    # Test 1: System instructions 
    instructions_ok = test_system_instructions()
    
    # Test 2: Greeting trigger mechanism
    trigger_ok = await test_greeting_trigger()
    
    # Summary
    print(f"\n📊 Test Results:")
    print(f"   System Instructions: {'✅ PASS' if instructions_ok else '❌ FAIL'}")
    print(f"   Greeting Trigger: {'✅ PASS' if trigger_ok else '❌ FAIL'}")
    
    if instructions_ok and trigger_ok:
        print("\n🎉 All tests passed! The voice agent should now greet users immediately when calls connect.")
        print("\n📋 Expected behavior:")
        print("   1. Call connects to Twilio")
        print("   2. WebSocket connects to OpenAI")
        print("   3. Session configuration is sent")
        print("   4. Greeting trigger is automatically sent")
        print("   5. AI starts speaking greeting within 1-2 seconds")
        print("   6. AI asks for member ID")
    else:
        print("\n⚠️ Some tests failed. Please check the implementation.")


if __name__ == "__main__":
    asyncio.run(main())