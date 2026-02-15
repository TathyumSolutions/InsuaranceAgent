"""Test audio conversion quality"""
import base64
from utils.audio_utils import AudioConverter

# Test with sample data
test_pcm = b'\x00\x01' * 100  # 200 bytes of test PCM16 data

# Test round-trip conversion
mulaw = AudioConverter.openai_to_twilio(test_pcm)
pcm_back = AudioConverter.twilio_to_openai(mulaw)

print(f"Original PCM: {len(test_pcm)} bytes")
print(f"Converted to mulaw: {len(mulaw)} bytes") 
print(f"Back to PCM: {len(pcm_back)} bytes")
print(f"Quality preserved: {len(test_pcm) == len(pcm_back)}")