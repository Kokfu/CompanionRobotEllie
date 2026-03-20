#!/usr/bin/env python3
"""
Voice Bridge Startup Script
Sets up environment variables and starts the STT/TTS bridge
"""

import os
import sys
import subprocess
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def setup_environment():
    """Setup environment variables for the voice bridge"""
    
    # Set VOSK model directory (use small model for better accuracy)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    vosk_model_dir = os.path.join(current_dir, 'STT_Models', 'vosk-model-small-en-us-0.15')
    
    if os.path.exists(vosk_model_dir):
        os.environ['VOSK_MODEL_DIR'] = vosk_model_dir
        logger.info(f"Set VOSK_MODEL_DIR to: {vosk_model_dir}")
    else:
        logger.error(f"VOSK model directory not found: {vosk_model_dir}")
        return False
    
    # Set other environment variables
    os.environ['STT_ENGINE'] = 'vosk'
    os.environ['LANGUAGE_HINT'] = 'en'
    os.environ['VOICE_NAME'] = 'Kore'
    os.environ['GEMINI_CHAT_MODEL'] = 'gemini-2.5-flash'
    os.environ['GEMINI_TTS_MODEL'] = 'gemini-2.5-flash-preview-tts'
    
    # Wake word settings
    os.environ['REQUIRE_WAKE_WORD'] = 'true'
    os.environ['WAKE_WORDS'] = 'hey, nexo, hey nexo'
    os.environ['WAKE_POLL_SEC'] = '1.0'
    os.environ['WAKE_LISTEN_SEC'] = '2.5'
    os.environ['COOLDOWN_SEC'] = '3.0'
    
    # Audio settings
    os.environ['IN_RATE'] = '16000'
    os.environ['OUT_RATE'] = '24000'
    
    logger.info("Environment variables set successfully")
    return True

def main():
    """Main function to start the voice bridge"""
    logger.info("Starting Voice Bridge...")
    
    # Setup environment
    if not setup_environment():
        logger.error("Failed to setup environment")
        sys.exit(1)
    
    # Start the voice bridge (use standalone version without web UI integration)
    bridge_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stt_tts_bridge_standalone.py')
    
    if not os.path.exists(bridge_script):
        logger.error(f"Voice bridge script not found: {bridge_script}")
        sys.exit(1)
    
    logger.info(f"Starting voice bridge: {bridge_script}")
    
    try:
        # Start the bridge process
        subprocess.run([sys.executable, bridge_script], check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Voice bridge failed with exit code: {e.returncode}")
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        logger.info("Voice bridge stopped by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()


