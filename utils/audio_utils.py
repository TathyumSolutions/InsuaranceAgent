"""
Audio Utilities
Handle audio format conversions between Twilio (mulaw) and OpenAI (PCM16)
"""
import audioop
import struct
import base64


def ulaw_to_pcm16(ulaw_data: bytes, width: int = 2) -> bytes:
    """
    Convert mulaw audio to PCM16
    
    Twilio sends audio in mulaw format at 8kHz
    
    Args:
        ulaw_data: mulaw encoded audio bytes
        width: Sample width in bytes (default: 2 for 16-bit)
    
    Returns:
        PCM16 encoded audio bytes
    """
    return audioop.ulaw2lin(ulaw_data, width)


def pcm16_to_ulaw(pcm_data: bytes, width: int = 2) -> bytes:
    """
    Convert PCM16 audio to mulaw
    
    For sending audio back to Twilio
    
    Args:
        pcm_data: PCM16 encoded audio bytes
        width: Sample width in bytes (default: 2 for 16-bit)
    
    Returns:
        mulaw encoded audio bytes
    """
    return audioop.lin2ulaw(pcm_data, width)


def resample_8khz_to_24khz(pcm_8khz: bytes) -> bytes:
    """
    Resample PCM16 audio from 8kHz to 24kHz
    
    Args:
        pcm_8khz: PCM16 audio at 8kHz
    
    Returns:
        PCM16 audio at 24kHz
    """
    return audioop.ratecv(pcm_8khz, 2, 1, 8000, 24000, None)[0]


def resample_24khz_to_8khz(pcm_24khz: bytes) -> bytes:
    """
    Resample PCM16 audio from 24kHz to 8kHz
    
    OpenAI sends 24kHz audio by default
    
    Args:
        pcm_24khz: PCM16 audio at 24kHz
    
    Returns:
        PCM16 audio at 8kHz
    """
    return audioop.ratecv(pcm_24khz, 2, 1, 24000, 8000, None)[0]


class AudioConverter:
    """Audio conversion utilities for voice processing"""
    
    def twilio_to_openai(self, mulaw_data: bytes) -> bytes:
        """Convert Twilio μLaw 8kHz to OpenAI PCM16 24kHz format"""
        try:
            if not mulaw_data:
                return b''
            
            # Step 1: Convert μLaw to PCM16 (still 8kHz)
            pcm_8khz = ulaw_to_pcm16(mulaw_data)
            
            # Step 2: Resample from 8kHz to 24kHz for OpenAI
            pcm_24khz = resample_8khz_to_24khz(pcm_8khz)
            
            return pcm_24khz
            
        except Exception as e:
            print(f"Audio conversion error (Twilio->OpenAI): {e}")
            return b''
    
    def openai_to_twilio(self, pcm16_data: bytes) -> bytes:
        """Convert OpenAI PCM16 24kHz to Twilio μLaw 8kHz format"""
        try:
            if not pcm16_data:
                return b''
                
            # Step 1: Resample from 24kHz to 8kHz
            pcm_8khz = resample_24khz_to_8khz(pcm16_data)
            
            # Step 2: Convert PCM16 to μLaw
            mulaw_data = pcm16_to_ulaw(pcm_8khz)
            
            return mulaw_data
            
        except Exception as e:
            print(f"Audio conversion error (OpenAI->Twilio): {e}")
            return b''

    def pcm16_to_ulaw(self, pcm_data: bytes) -> bytes:
        """Direct PCM16 to μLaw conversion"""
        try:
            return pcm16_to_ulaw(pcm_data)
        except Exception as e:
            print(f"PCM16 to μLaw conversion error: {e}")
            return b''

    def ulaw_to_pcm16(self, ulaw_data: bytes) -> bytes:
        """Direct μLaw to PCM16 conversion"""
        try:
            return ulaw_to_pcm16(ulaw_data)
        except Exception as e:
            print(f"μLaw to PCM16 conversion error: {e}")
            return b''
