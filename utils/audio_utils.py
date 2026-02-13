"""
Audio Utilities
Handle audio format conversions between Twilio (mulaw) and OpenAI (PCM16)
"""
import audioop
import struct
from typing import bytes as Bytes


def ulaw_to_pcm16(ulaw_data: Bytes, width: int = 2) -> Bytes:
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


def pcm16_to_ulaw(pcm_data: Bytes, width: int = 2) -> Bytes:
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


def resample_8khz_to_16khz(pcm_8khz: Bytes) -> Bytes:
    """
    Resample PCM16 audio from 8kHz to 16kHz
    
    Twilio uses 8kHz, OpenAI expects 16kHz
    
    Args:
        pcm_8khz: PCM16 audio at 8kHz
    
    Returns:
        PCM16 audio at 16kHz
    """
    # audioop.ratecv(fragment, width, nchannels, inrate, outrate, state)
    return audioop.ratecv(pcm_8khz, 2, 1, 8000, 16000, None)[0]


def resample_16khz_to_8khz(pcm_16khz: Bytes) -> Bytes:
    """
    Resample PCM16 audio from 16kHz to 8kHz
    
    For sending OpenAI audio back to Twilio
    
    Args:
        pcm_16khz: PCM16 audio at 16kHz
    
    Returns:
        PCM16 audio at 8kHz
    """
    return audioop.ratecv(pcm_16khz, 2, 1, 16000, 8000, None)[0]


def resample_24khz_to_8khz(pcm_24khz: Bytes) -> Bytes:
    """
    Resample PCM16 audio from 24kHz to 8kHz

    OpenAI sometimes sends 24kHz audio by default

    Args:
        pcm_24khz: PCM16 audio at 24kHz

    Returns:
        PCM16 audio at 8kHz
    """
    return audioop.ratecv(pcm_24khz, 2, 1, 24000, 8000, None)[0]


def resample_8khz_to_24khz(pcm_8khz: Bytes) -> Bytes:
    """
    Resample PCM16 audio from 8kHz to 24kHz

    Twilio uses 8kHz, OpenAI Realtime API expects 24kHz

    Args:
        pcm_8khz: PCM16 audio at 8kHz

    Returns:
        PCM16 audio at 24kHz
    """
    return audioop.ratecv(pcm_8khz, 2, 1, 8000, 24000, None)[0]


def downsample_by_factor(pcm_data: Bytes, factor: int) -> Bytes:
    """
    Downsample PCM16 audio by taking every Nth sample
    
    Alternative method for downsampling (less accurate but faster)
    
    Args:
        pcm_data: PCM16 audio bytes
        factor: Downsampling factor (e.g., 3 for 24kHz -> 8kHz)
    
    Returns:
        Downsampled PCM16 audio
    """
    # Decode all samples
    samples = [
        struct.unpack('<h', pcm_data[i:i+2])[0] 
        for i in range(0, len(pcm_data), 2)
    ]
    
    # Take every Nth sample
    downsampled = samples[::factor]
    
    # Re-encode
    return b''.join(struct.pack('<h', s) for s in downsampled)


def get_audio_duration(pcm_data: Bytes, sample_rate: int = 8000) -> float:
    """
    Calculate duration of PCM16 audio in seconds
    
    Args:
        pcm_data: PCM16 audio bytes
        sample_rate: Sample rate in Hz (default: 8000)
    
    Returns:
        Duration in seconds
    """
    num_samples = len(pcm_data) // 2  # 2 bytes per sample (16-bit)
    return num_samples / sample_rate


def validate_audio_data(audio_data: Bytes) -> bool:
    """
    Validate that audio data is valid PCM16
    
    Args:
        audio_data: Audio data to validate
    
    Returns:
        True if valid, False otherwise
    """
    # Check if length is even (required for 16-bit samples)
    if len(audio_data) % 2 != 0:
        return False
    
    # Check if we can decode at least one sample
    try:
        struct.unpack('<h', audio_data[:2])
        return True
    except:
        return False


class AudioConverter:
    """
    Comprehensive audio conversion class
    Handles all conversions needed for Twilio <-> OpenAI integration
    """
    
    @staticmethod
    def twilio_to_openai(mulaw_data: Bytes) -> Bytes:
        """
        Convert Twilio audio to OpenAI Realtime API format

        mulaw 8kHz -> PCM16 8kHz -> PCM16 24kHz

        Args:
            mulaw_data: Audio from Twilio

        Returns:
            PCM16 audio at 24kHz for OpenAI Realtime API
        """
        # Step 1: mulaw -> PCM16 (8kHz)
        pcm_8khz = ulaw_to_pcm16(mulaw_data)

        # Step 2: Resample 8kHz -> 24kHz (OpenAI Realtime API expects 24kHz)
        pcm_24khz = resample_8khz_to_24khz(pcm_8khz)

        return pcm_24khz
    
    @staticmethod
    def openai_to_twilio(pcm_16khz: Bytes) -> Bytes:
        """
        Convert OpenAI audio to Twilio format
        
        PCM16 16kHz -> PCM16 8kHz -> mulaw 8kHz
        
        Args:
            pcm_16khz: Audio from OpenAI
        
        Returns:
            mulaw audio at 8kHz for Twilio
        """
        # Step 1: Resample 16kHz -> 8kHz
        pcm_8khz = resample_16khz_to_8khz(pcm_16khz)
        
        # Step 2: PCM16 -> mulaw
        mulaw = pcm16_to_ulaw(pcm_8khz)
        
        return mulaw
    
    @staticmethod
    def openai_24k_to_twilio(pcm_24khz: Bytes) -> Bytes:
        """
        Convert OpenAI 24kHz audio to Twilio format
        
        Some OpenAI models output 24kHz by default
        
        Args:
            pcm_24khz: Audio from OpenAI at 24kHz
        
        Returns:
            mulaw audio at 8kHz for Twilio
        """
        # Step 1: Resample 24kHz -> 8kHz
        pcm_8khz = resample_24khz_to_8khz(pcm_24khz)
        
        # Step 2: PCM16 -> mulaw
        mulaw = pcm16_to_ulaw(pcm_8khz)
        
        return mulaw
