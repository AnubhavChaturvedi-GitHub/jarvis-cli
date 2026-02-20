import os
import threading
import warnings

if os.getenv("JARVIS_ALLOW_TTS_DOWNLOAD", "0") != "1":
    os.environ["HF_HUB_OFFLINE"] = "1"

import simpleaudio as sa
from kokoro import KPipeline
from huggingface_hub import try_to_load_from_cache

# Suppress known non-fatal torch warnings that clutter startup output.
warnings.filterwarnings(
    "ignore",
    message="dropout option adds dropout after all but last recurrent layer.*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message="`torch.nn.utils.weight_norm` is deprecated.*",
    category=FutureWarning,
)

class JarvisVoice:
    """
    Jarvis Voice - Text-to-Speech using Kokoro-82M
    
    Features:
    - Ultra-fast local TTS (82M model)
    - High-quality voice synthesis
    - Real-time audio playback
    - Optimized for Mac (MPS/CPU)
    """
    
    def __init__(self, voice='am_adam', speed=1.1):
        """
        Initialize Jarvis Voice with Kokoro TTS.
        
        Args:
            voice (str): Voice preset (am_adam, am_michael, af_bella, af_sarah, etc.)
            speed (float): Speech speed multiplier (1.0 = normal, 1.1 = slightly faster)
        """
        try:
            # If required artifacts are already cached, force offline mode to skip
            # network metadata checks and reduce startup latency.
            required_files = [
                "config.json",
                "kokoro-v1_0.pth",
                f"voices/{voice}.pt",
            ]
            def _cached_file(filename):
                cached_path = try_to_load_from_cache("hexgrad/Kokoro-82M", filename)
                if not cached_path:
                    return False
                try:
                    return os.path.isfile(os.fspath(cached_path))
                except Exception:
                    return False

            cached = all(_cached_file(f) for f in required_files)
            allow_download = os.getenv("JARVIS_ALLOW_TTS_DOWNLOAD", "0") == "1"

            if not allow_download:
                os.environ["HF_HUB_OFFLINE"] = "1"

            if cached:
                os.environ["HF_HUB_OFFLINE"] = "1"
            elif not allow_download:
                self.enabled = False
                self.voice = voice
                self.speed = speed
                print("[TTS] Model not cached. Voice disabled to avoid download delays.")
                print("[TTS] Run: python3 scripts/prefetch_kokoro.py")
                return

            # Initialize Kokoro pipeline for American English
            self.pipeline = KPipeline(lang_code='a')
            self.voice = voice
            self.speed = speed
            self._speak_lock = threading.Lock()
            self.enabled = True
            print(f"[TTS] Kokoro initialized with voice: {voice}")
        except Exception as e:
            print(f"[TTS] Warning: Could not initialize Kokoro: {e}")
            self.enabled = False
    
    def speak(self, text, blocking=True):
        """
        Convert text to speech and play it.
        
        Args:
            text (str): Text to speak
            blocking (bool): If True, wait for audio to finish before returning
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.enabled:
            print(f"[TTS] Disabled - would have said: {text}")
            return False
        
        if not text or not text.strip():
            return False
        
        try:
            with self._speak_lock:
                # Generate audio using Kokoro
                generator = self.pipeline(
                    text,
                    voice=self.voice,
                    speed=self.speed,
                    split_pattern=r'\n+'
                )
                
                # Process and play each segment
                for i, (gs, ps, audio) in enumerate(generator):
                    # Convert tensor to numpy array if needed
                    import numpy as np
                    if hasattr(audio, 'numpy'):
                        audio = audio.numpy()
                    
                    # Ensure audio is in the correct format for simpleaudio
                    # Convert to int16 format
                    audio_int16 = (audio * 32767).astype(np.int16)
                    
                    # Play audio directly
                    play_obj = sa.play_buffer(
                        audio_int16,
                        num_channels=1,
                        bytes_per_sample=2,
                        sample_rate=24000
                    )
                    
                    if blocking:
                        play_obj.wait_done()
            
            return True
            
        except Exception as e:
            print(f"[TTS] Error speaking: {e}")
            return False
    
    def speak_async(self, text):
        """
        Speak text without blocking (non-blocking mode).
        
        Args:
            text (str): Text to speak
        """
        if not self.enabled:
            print(f"[TTS] Disabled - would have said: {text}")
            return False
        threading.Thread(target=self.speak, args=(text, True), daemon=True).start()
        return True
    
    def set_voice(self, voice):
        """
        Change the voice preset.
        
        Available voices:
        - Male (US): am_adam, am_michael
        - Female (US): af_bella, af_sarah, af_nicole, af_sky
        - British: bf_isabella, bm_lewis
        
        Args:
            voice (str): Voice preset name
        """
        self.voice = voice
        print(f"[TTS] Voice changed to: {voice}")
    
    def set_speed(self, speed):
        """
        Change speech speed.
        
        Args:
            speed (float): Speed multiplier (0.5 = half speed, 2.0 = double speed)
        """
        self.speed = speed
        print(f"[TTS] Speed changed to: {speed}x")


# Example usage
if __name__ == "__main__":
    # Test the voice
    try:
        voice = JarvisVoice(voice='am_adam', speed=1.1)
        
        print("Testing Jarvis Voice...")
        voice.speak("Hello, I am Jarvis. Your personal AI assistant.")
        
        print("\nTesting different voices...")
        voice.set_voice('am_michael')
        voice.speak("This is a different voice.")
        
        print("\nTesting speed control...")
        voice.set_speed(1.3)
        voice.speak("I can speak faster if you prefer.")
        
        print("\nVoice test complete!")
        
    except Exception as e:
        print(f"Error: {e}")
        print("\nMake sure you have installed:")
        print("1. brew install espeak-ng")
        print("2. pip3 install kokoro simpleaudio")
