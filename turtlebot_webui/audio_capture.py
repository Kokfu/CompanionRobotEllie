#!/usr/bin/env python3
"""
Audio capture module for real-time STT functionality
Provides microphone recording and audio processing capabilities
"""

import os
import sys
import time
import wave
import tempfile
import threading
import queue
import logging
from datetime import datetime

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    logging.warning("PyAudio not available. Audio capture will be simulated.")

# Audio configuration
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SIZE = 1024
FORMAT = pyaudio.paInt16 if PYAUDIO_AVAILABLE else None
RECORD_SECONDS = 5  # Default recording duration

class AudioCapture:
    def __init__(self):
        self.audio = None
        self.stream = None
        self.is_recording = False
        self.audio_queue = queue.Queue()
        self.recording_thread = None
        
        if PYAUDIO_AVAILABLE:
            try:
                self.audio = pyaudio.PyAudio()
            except Exception as e:
                logging.error(f"Failed to initialize PyAudio: {e}")
                self.audio = None

    def start_recording(self, duration=RECORD_SECONDS):
        """Start recording audio from microphone"""
        if not PYAUDIO_AVAILABLE or not self.audio:
            # Simulate recording if PyAudio is not available
            return self._simulate_recording(duration)
        
        try:
            if self.is_recording:
                return False, "Already recording"
            
            self.is_recording = True
            self.recording_thread = threading.Thread(
                target=self._record_audio, 
                args=(duration,)
            )
            self.recording_thread.start()
            
            return True, "Recording started"
            
        except Exception as e:
            logging.error(f"Failed to start recording: {e}")
            return False, str(e)

    def stop_recording(self):
        """Stop recording and return audio data"""
        if not self.is_recording:
            return None, "Not recording"
        
        self.is_recording = False
        
        if self.recording_thread:
            self.recording_thread.join(timeout=2)
        
        # Get audio data from queue
        audio_frames = []
        while not self.audio_queue.empty():
            audio_frames.append(self.audio_queue.get())
        
        if audio_frames:
            # Combine all audio frames
            audio_data = b''.join(audio_frames)
            
            # Save to temporary WAV file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                with wave.open(temp_file.name, 'wb') as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(2)  # 16-bit
                    wf.setframerate(SAMPLE_RATE)
                    wf.writeframes(audio_data)
                
                return temp_file.name, "Recording completed"
        
        return None, "No audio data captured"

    def _record_audio(self, duration):
        """Internal method to record audio"""
        try:
            self.stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                frames_per_buffer=CHUNK_SIZE
            )
            
            frames = []
            for _ in range(0, int(SAMPLE_RATE / CHUNK_SIZE * duration)):
                if not self.is_recording:
                    break
                data = self.stream.read(CHUNK_SIZE)
                frames.append(data)
                self.audio_queue.put(data)
            
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
            
        except Exception as e:
            logging.error(f"Error during audio recording: {e}")
        finally:
            self.is_recording = False

    def _simulate_recording(self, duration):
        """Simulate recording when PyAudio is not available"""
        logging.info(f"Simulating audio recording for {duration} seconds")
        time.sleep(duration)
        
        # Create a silent WAV file for testing
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            with wave.open(temp_file.name, 'wb') as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(SAMPLE_RATE)
                # Create silent audio data
                silent_data = b'\x00' * (SAMPLE_RATE * duration * 2)
                wf.writeframes(silent_data)
            
            return temp_file.name, "Simulated recording completed"

    def cleanup(self):
        """Clean up audio resources"""
        if self.is_recording:
            self.stop_recording()
        
        if self.stream:
            self.stream.close()
            self.stream = None
        
        if self.audio:
            self.audio.terminate()
            self.audio = None

    def get_available_devices(self):
        """Get list of available audio input devices"""
        if not PYAUDIO_AVAILABLE or not self.audio:
            return []
        
        devices = []
        try:
            device_count = self.audio.get_device_count()
            for i in range(device_count):
                device_info = self.audio.get_device_info_by_index(i)
                if device_info['maxInputChannels'] > 0:
                    devices.append({
                        'index': i,
                        'name': device_info['name'],
                        'channels': device_info['maxInputChannels'],
                        'sample_rate': device_info['defaultSampleRate']
                    })
        except Exception as e:
            logging.error(f"Error getting audio devices: {e}")
        
        return devices

# Global audio capture instance
audio_capture = AudioCapture()

def get_audio_capture():
    """Get the global audio capture instance"""
    return audio_capture

def cleanup_audio():
    """Clean up audio resources"""
    audio_capture.cleanup()
