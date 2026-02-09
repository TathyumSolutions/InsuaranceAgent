"""
Test Audio Utilities
Verify audio conversion functions work correctly
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.audio_utils import AudioConverter, validate_audio_data
import struct


def test_audio_conversions():
    """Test audio format conversions"""
    print("Testing audio conversions...")
    
    # Create test PCM16 audio (16kHz, 1 second)
    sample_rate = 16000
    duration = 1.0
    num_samples = int(sample_rate * duration)
    
    # Generate simple sine wave
    import math
    frequency = 440  # A4 note
    samples = [
        int(32767 * 0.5 * math.sin(2 * math.pi * frequency * i / sample_rate))
        for i in range(num_samples)
    ]
    
    # Encode as PCM16
    pcm_16khz = b''.join(struct.pack('<h', s) for s in samples)
    print(f"✓ Created test audio: {len(pcm_16khz)} bytes at 16kHz")
    
    # Test OpenAI to Twilio conversion
    mulaw = AudioConverter.openai_to_twilio(pcm_16khz)
    print(f"✓ Converted to mulaw: {len(mulaw)} bytes")
    
    # Test Twilio to OpenAI conversion
    pcm_back = AudioConverter.twilio_to_openai(mulaw)
    print(f"✓ Converted back to PCM16: {len(pcm_back)} bytes")
    
    # Validate
    assert validate_audio_data(pcm_16khz), "Original PCM16 validation failed"
    assert validate_audio_data(pcm_back), "Converted PCM16 validation failed"
    print("✓ Audio validation passed")
    
    print("\n✅ All audio conversion tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Audio Utilities Test Suite")
    print("=" * 60)
    print()
    
    try:
        test_audio_conversions()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
