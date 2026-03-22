#!/usr/bin/env python3
"""
STT/TTS API endpoints for the TurtleBot Web UI
Provides speech-to-text and text-to-speech functionality with voice selection and language support
"""

import os
import sys
import json
import time
import tempfile
import wave
import subprocess
import sqlite3
from datetime import datetime
from flask import Blueprint, request, jsonify
import logging

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not available, continue with existing env vars

# Add multiple possible paths to find test_speech
POSSIBLE_PATHS = [
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # parent of v3
    os.path.expanduser('~/'),  # home directory
    os.path.dirname(os.path.abspath(__file__)),  # current directory
]

for path in POSSIBLE_PATHS:
    if path not in sys.path:
        sys.path.insert(0, path)

try:
    import test_speech as stt_tts_core
    logging.info(f"Successfully imported test_speech from {stt_tts_core.__file__}")
except ImportError as e:
    logging.error(f"Failed to import test_speech from any path: {e}")
    logging.error(f"Searched paths: {POSSIBLE_PATHS}")
    stt_tts_core = None

try:
    from audio_capture import get_audio_capture
    AUDIO_CAPTURE_AVAILABLE = True
except ImportError as e:
    logging.error(f"Failed to import audio_capture: {e}")
    AUDIO_CAPTURE_AVAILABLE = False

# Create blueprint
stt_tts_bp = Blueprint('stt_tts', __name__, url_prefix='/api/stt-tts')

# Voice mapping for Gemini TTS
VOICE_MAPPING = {
    'Kore': 'Kore',      # Men's voice
    'Aoede': 'Aoede',    # Girl's voice  
    'Charon': 'Charon'   # Soft child's voice
}

# =========================
# --- API Key Management ---
# =========================
_api_keys = []
_current_key_index = 0
_key_usage_count = {}

def load_api_keys():
    """Load and rotate API keys from environment variables"""
    global _api_keys, _current_key_index
    
    # Reset the keys list to ensure fresh loading
    _api_keys = []
    _current_key_index = 0
    
    # Load from .env file
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    # Get GENAI_API_KEYS (comma-separated)
    genai_keys_str = os.environ.get("GENAI_API_KEYS", "")
    if genai_keys_str:
        _api_keys = [key.strip() for key in genai_keys_str.split(",") if key.strip()]
        logging.info(f"[API] Loaded {len(_api_keys)} keys from GENAI_API_KEYS")
    
    # Fallback to GOOGLE_API_KEY (also handle comma-separated)
    if not _api_keys:
        google_key = os.environ.get("GOOGLE_API_KEY", "")
        if google_key:
            # Handle both single key and comma-separated keys
            if ',' in google_key:
                _api_keys = [key.strip() for key in google_key.split(",") if key.strip()]
                logging.info(f"[API] Loaded {len(_api_keys)} keys from GOOGLE_API_KEY (comma-separated)")
            else:
                _api_keys = [google_key.strip()]
                logging.info(f"[API] Loaded 1 key from GOOGLE_API_KEY")
    
    # Initialize usage tracking
    _key_usage_count.clear()
    for key in _api_keys:
        _key_usage_count[key] = 0
    
    logging.info(f"[API] Total loaded: {len(_api_keys)} API keys for web UI")
    return len(_api_keys) > 0

def get_next_api_key():
    """Get next API key with rotation"""
    global _current_key_index, _key_usage_count
    
    if not _api_keys:
        return None
    
    # Get current key
    current_key = _api_keys[_current_key_index]
    _key_usage_count[current_key] += 1
    
    # Rotate to next key
    _current_key_index = (_current_key_index + 1) % len(_api_keys)
    
    logging.info(f"[API] Using key {_current_key_index + 1}/{len(_api_keys)} (usage: {_key_usage_count[current_key]})")
    return current_key

def pcm_to_wav(pcm_data, sample_rate=24000, channels=1, bits_per_sample=16):
    """Convert raw PCM data to WAV format"""
    import struct
    
    # Calculate data size
    data_size = len(pcm_data)
    
    # WAV header
    wav_header = struct.pack('<4sI4s4sIHHIIHH4sI',
        b'RIFF',                    # ChunkID
        36 + data_size,             # ChunkSize
        b'WAVE',                    # Format
        b'fmt ',                    # Subchunk1ID
        16,                         # Subchunk1Size
        1,                          # AudioFormat (PCM)
        channels,                   # NumChannels
        sample_rate,                # SampleRate
        sample_rate * channels * bits_per_sample // 8,  # ByteRate
        channels * bits_per_sample // 8,                # BlockAlign
        bits_per_sample,            # BitsPerSample
        b'data',                    # Subchunk2ID
        data_size                   # Subchunk2Size
    )
    
    return wav_header + pcm_data

# Language to Vosk model mapping
LANGUAGE_MODELS = {
    'en': 'vosk-model-en-us-0.22',
    'zh': 'vosk-model-small-cn-0.22'
}

# Database path
VOICE_LOG_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'voice_logs.db')

def get_vosk_model_path(language):
    """Get the path to the Vosk model for the specified language"""
    model_name = LANGUAGE_MODELS.get(language, 'vosk-model-en-us-0.22')
    
    # Try multiple possible locations for STT_Models
    possible_model_dirs = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'STT_Models'),  # v3/STT_Models
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'STT_Models'),  # parent/STT_Models
        os.path.expanduser('~/STT_Models'),  # home/STT_Models
    ]
    
    for model_dir in possible_model_dirs:
        model_path = os.path.join(model_dir, model_name)
        if os.path.exists(model_path):
            logging.info(f"Found Vosk model: {model_path}")
            return model_path
    
    # If not found, log all attempted paths
    logging.error(f"Vosk model '{model_name}' not found in any of these locations:")
    for model_dir in possible_model_dirs:
        attempted_path = os.path.join(model_dir, model_name)
        logging.error(f"  - {attempted_path}")
    
    return None

def init_voice_db():
    """Initialize the voice logs database"""
    with sqlite3.connect(VOICE_LOG_DB) as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS voice_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            lang TEXT,
            stt_engine TEXT,
            text_in TEXT,
            text_out TEXT,
            voice TEXT,
            source TEXT
        );
        """)
        # Prevent exact duplicates
        con.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_voice_unique
        ON voice_logs(ts, text_in, text_out);
        """)

def insert_voice_log(entry):
    """Insert a voice log entry into the database"""
    with sqlite3.connect(VOICE_LOG_DB) as con:
        con.execute("""
            INSERT INTO voice_logs (ts, lang, stt_engine, text_in, text_out, voice, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            entry.get("ts"), entry.get("lang"), entry.get("stt_engine"),
            entry.get("text_in"), entry.get("text_out"),
            entry.get("voice"), entry.get("source")
        ))

def get_voice_logs(limit=100):
    """Get voice logs from the database"""
    with sqlite3.connect(VOICE_LOG_DB) as con:
        con.row_factory = sqlite3.Row
        return [
            dict(row) for row in con.execute(
                "SELECT ts, lang, stt_engine, text_in, text_out, voice, source FROM voice_logs ORDER BY id DESC LIMIT ?",
                (limit,)
            )
        ]

def clear_voice_logs():
    """Clear all voice logs from the database"""
    with sqlite3.connect(VOICE_LOG_DB) as con:
        con.execute("DELETE FROM voice_logs")

def setup_environment(language, voice):
    """Setup environment variables for STT/TTS processing"""
    # Load environment variables from .env file if not already loaded
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # dotenv not available, continue with existing env vars
    
    # Set Vosk model directory based on language
    model_path = get_vosk_model_path(language)
    if model_path:
        os.environ['VOSK_MODEL_DIR'] = model_path
        logging.info(f"Set VOSK_MODEL_DIR to: {model_path}")
    else:
        logging.error(f"Vosk model not found for language: {language}")
        # Fallback to English model
        fallback_path = get_vosk_model_path('en')
        if fallback_path:
            os.environ['VOSK_MODEL_DIR'] = fallback_path
            logging.warning(f"Using fallback English model: {fallback_path}")
    
    # Set language hint
    os.environ['LANGUAGE_HINT'] = language
    
    # Set voice for TTS
    os.environ['VOICE_NAME'] = voice
    
    # Set STT engine to Vosk
    os.environ['STT_ENGINE'] = 'vosk'
    
    # Get next API key with rotation
    api_key = get_next_api_key()
    if api_key:
        os.environ['GOOGLE_API_KEY'] = api_key
        logging.info(f"Using rotated API key (length: {len(api_key)})")
    else:
        logging.warning("No API keys available - TTS functionality may not work")

@stt_tts_bp.route('/start-stt', methods=['POST'])
def start_stt():
    """Start speech-to-text processing with 15-second recording without wake word"""
    try:
        if not stt_tts_core:
            return jsonify({
                'success': False, 
                'error': 'STT/TTS core not available. Please check that test_speech.py is accessible and dependencies are installed.',
                'debug_info': {
                    'searched_paths': POSSIBLE_PATHS,
                    'current_directory': os.getcwd(),
                    'python_path': sys.path[:5]  # First 5 paths for debugging
                }
            }), 500
        
        data = request.get_json()
        language = data.get('language', 'en')
        voice = data.get('voice', 'Kore')
        duration = data.get('duration', 15)  # Fixed 15-second recording duration
        
        # Setup environment
        setup_environment(language, voice)
        
        # Trigger 15-second microphone recording without wake word
        try:
            import subprocess
            import time
            
            # First, trigger the microphone to start recording for 15 seconds
            # This will publish to the mic topic to start continuous recording
            mic_start_result = subprocess.run([
                'ros2', 'topic', 'pub', '--once', '/mic/start_recording', 'std_msgs/msg/String', 
                'data: "start_15_seconds"'
            ], capture_output=True, text=True, timeout=5)
            
            if mic_start_result.returncode != 0:
                logging.warning(f"Mic start command failed: {mic_start_result.stderr}")
            
            # Wait for the 15-second recording to complete
            logging.info("Starting 15-second recording...")
            time.sleep(15)
            
            # Now trigger the voice bridge to process the recorded audio
            result = subprocess.run([
                'ros2', 'service', 'call', '/voice/do_interaction', 'std_srvs/srv/Trigger'
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                # Wait a moment for the processing to complete
                time.sleep(2)
                
                # Get the latest voice log to see what was recognized
                recent_logs = get_voice_logs(1)
                if recent_logs and recent_logs[0].get('text_in'):
                    recognized_text = recent_logs[0]['text_in']
                else:
                    recognized_text = "15-second recording completed, but no speech was recognized. Please try speaking again."
            else:
                return jsonify({
                    'success': False, 
                    'error': 'Failed to process recorded audio. Make sure the voice bridge is running.'
                }), 500
                
        except subprocess.TimeoutExpired:
            return jsonify({
                'success': False, 
                'error': 'Audio processing timed out. Please try again.'
            }), 500
        except Exception as e:
            logging.error(f"STT processing error: {e}")
            return jsonify({
                'success': False, 
                'error': f'Failed to process audio: {str(e)}'
            }), 500
        
        if not recognized_text or not recognized_text.strip():
            return jsonify({'success': False, 'error': 'No speech recognized during 15-second recording'}), 400
        
        # Log the STT result
        log_entry = {
            'ts': time.time(),
            'lang': language,
            'stt_engine': 'vosk',
            'text_in': recognized_text,
            'text_out': '',
            'voice': voice,
            'source': 'STT (15s recording)'
        }
        insert_voice_log(log_entry)
        
        return jsonify({
            'success': True,
            'text': recognized_text,
            'language': language,
            'voice': voice,
            'recording_duration': 15
        })
        
    except Exception as e:
        logging.error(f"STT error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@stt_tts_bp.route('/play-tts', methods=['POST'])
def play_tts():
    """Play text-to-speech"""
    try:
        if not stt_tts_core:
            return jsonify({
                'success': False, 
                'error': 'STT/TTS core not available. Please check that test_speech.py is accessible and dependencies are installed.',
                'debug_info': {
                    'searched_paths': POSSIBLE_PATHS,
                    'current_directory': os.getcwd(),
                    'python_path': sys.path[:5]  # First 5 paths for debugging
                }
            }), 500
        
        data = request.get_json()
        text = data.get('text', '')
        voice = data.get('voice', 'Kore')
        language = data.get('language', 'en')
        output_mode = data.get('output_mode', 'both')  # 'robot', 'webui', or 'both'
        
        if not text:
            return jsonify({'success': False, 'error': 'No text provided'}), 400
        
        # Setup environment
        setup_environment(language, voice)
        
        # Generate TTS using Gemini
        try:
            # Use the real Gemini TTS functionality
            pcm_24k = stt_tts_core.gemini_tts(text)
            
            # Save to temporary file and play
            with tempfile.TemporaryDirectory() as td:
                out_24k = os.path.join(td, "reply_24k.wav")
                out_16k = os.path.join(td, "reply_16k.wav")
                
                stt_tts_core.save_wav(out_24k, pcm_24k, channels=1, rate=stt_tts_core.OUT_RATE, sample_width=2)
                stt_tts_core.downsample_to_16k(out_24k, out_16k)
                
                # Handle audio output based on mode
                audio_data = None
                if output_mode in ['webui', 'both']:
                    # Read the 16k audio file for WebUI playback
                    with open(out_16k, 'rb') as f:
                        audio_data = f.read()
                
                if output_mode in ['robot', 'both']:
                    # For robot output, we would publish to ROS topic
                    # This would be handled by the ROS bridge
                    pass
                
                # Simulate playback time
                time.sleep(1)
            
            # Log the TTS result
            log_entry = {
                'ts': time.time(),
                'lang': language,
                'stt_engine': 'gemini',
                'text_in': '',
                'text_out': text,
                'voice': voice,
                'source': 'TTS'
            }
            insert_voice_log(log_entry)
            
            response_data = {
                'success': True,
                'response_text': text,
                'voice': voice,
                'language': language,
                'output_mode': output_mode
            }
            
            # Include audio data for WebUI playback if requested
            if audio_data and output_mode in ['webui', 'both']:
                import base64
                response_data['audio_data'] = base64.b64encode(audio_data).decode('utf-8')
            
            return jsonify(response_data)
            
        except Exception as e:
            logging.error(f"TTS generation error: {e}")
            return jsonify({'success': False, 'error': f'TTS generation failed: {str(e)}'}), 500
        
    except Exception as e:
        logging.error(f"TTS error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@stt_tts_bp.route('/test-voice', methods=['POST'])
def test_voice():
    """Test a specific voice with sample text"""
    try:
        if not stt_tts_core:
            return jsonify({'success': False, 'error': 'STT/TTS core not available'}), 500
        
        data = request.get_json()
        voice = data.get('voice', 'Kore')
        language = data.get('language', 'en')
        output_mode = data.get('output_mode', 'webui')  # Default to WebUI for testing
        
        # Sample texts for different voices and languages
        sample_texts = {
            'en': {
                'Kore': "Hello, I am the men's voice. This is how I sound.",
                'Aoede': "Hi there! I'm the girl's voice. Listen to my clear tone.",
                'Charon': "Hello, I'm the soft child's voice. I sound gentle and warm."
            },
            'zh': {
                'Kore': "你好，我是男声。这就是我的声音。",
                'Aoede': "你好！我是女声。听听我清晰的声音。",
                'Charon': "你好，我是温柔的童声。我听起来很温和。"
            }
        }
        
        text = sample_texts.get(language, sample_texts['en']).get(voice, sample_texts['en']['Kore'])
        
        # Setup environment
        setup_environment(language, voice)
        
        # Generate TTS using Gemini
        try:
            # Use the real Gemini TTS functionality
            pcm_24k = stt_tts_core.gemini_tts(text)
            
            # Save to temporary file and play
            with tempfile.TemporaryDirectory() as td:
                out_24k = os.path.join(td, "test_24k.wav")
                out_16k = os.path.join(td, "test_16k.wav")
                
                stt_tts_core.save_wav(out_24k, pcm_24k, channels=1, rate=stt_tts_core.OUT_RATE, sample_width=2)
                stt_tts_core.downsample_to_16k(out_24k, out_16k)
                
                # Handle audio output based on mode
                audio_data = None
                if output_mode in ['webui', 'both']:
                    # Read the 16k audio file for WebUI playback
                    with open(out_16k, 'rb') as f:
                        audio_data = f.read()
                
                if output_mode in ['robot', 'both']:
                    # For robot output, we would publish to ROS topic
                    # This would be handled by the ROS bridge
                    pass
                
                # Simulate playback time
                time.sleep(1)
            
            # Log the voice test result
            log_entry = {
                'ts': time.time(),
                'lang': language,
                'stt_engine': 'gemini',
                'text_in': '',
                'text_out': text,
                'voice': voice,
                'source': 'Voice Test'
            }
            insert_voice_log(log_entry)
            
            response_data = {
                'success': True,
                'response_text': text,
                'voice': voice,
                'language': language,
                'output_mode': output_mode
            }
            
            # Include audio data for WebUI playback if requested
            if audio_data and output_mode in ['webui', 'both']:
                import base64
                response_data['audio_data'] = base64.b64encode(audio_data).decode('utf-8')
            
            return jsonify(response_data)
            
        except Exception as e:
            logging.error(f"Voice test generation error: {e}")
            return jsonify({'success': False, 'error': f'Voice test failed: {str(e)}'}), 500
        
    except Exception as e:
        logging.error(f"Voice test error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@stt_tts_bp.route('/logs', methods=['GET'])
def get_logs():
    """Get voice logs"""
    try:
        limit = int(request.args.get('limit', 100))
        logs = get_voice_logs(limit)
        
        return jsonify({
            'success': True,
            'logs': logs
        })
        
    except Exception as e:
        logging.error(f"Get logs error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@stt_tts_bp.route('/clear-logs', methods=['POST'])
def clear_logs():
    """Clear all voice logs"""
    try:
        clear_voice_logs()
        
        return jsonify({
            'success': True,
            'message': 'Voice logs cleared successfully'
        })
        
    except Exception as e:
        logging.error(f"Clear logs error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@stt_tts_bp.route('/direct-tts', methods=['POST'])
def direct_tts():
    """Direct text-to-speech without STT"""
    try:
        if not stt_tts_core:
            return jsonify({
                'success': False, 
                'error': 'STT/TTS core not available. Please check that test_speech.py is accessible and dependencies are installed.'
            }), 500
        
        data = request.get_json()
        text = data.get('text', '')
        voice = data.get('voice', 'Kore')
        language = data.get('language', 'en')
        output_mode = data.get('output_mode', 'both')
        
        if not text:
            return jsonify({'success': False, 'error': 'No text provided'}), 400
        
        # Setup environment
        setup_environment(language, voice)
        
        # Generate TTS using Gemini
        try:
            audio_data = stt_tts_core.gemini_tts(text)
            
            # Log the TTS result
            log_entry = {
                'ts': time.time(),
                'lang': language,
                'stt_engine': 'direct',
                'text_in': '',
                'text_out': text,
                'voice': voice,
                'source': 'Direct TTS'
            }
            insert_voice_log(log_entry)
            
            # Convert PCM data to WAV format for web playback
            wav_data = pcm_to_wav(audio_data, sample_rate=24000)
            
            # Convert WAV data to base64 for JSON transmission
            import base64
            audio_base64 = base64.b64encode(wav_data).decode('utf-8')
            
            return jsonify({
                'success': True,
                'response_text': text,
                'voice': voice,
                'language': language,
                'audio_data': audio_base64,
                'audio_format': 'wav'
            })
            
        except Exception as e:
            logging.error(f"TTS generation error: {e}")
            return jsonify({'success': False, 'error': f'TTS generation failed: {str(e)}'}), 500
        
    except Exception as e:
        logging.error(f"Direct TTS error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@stt_tts_bp.route('/voices', methods=['GET'])
def get_voices():
    """Get available voices"""
    return jsonify({
        'success': True,
        'voices': list(VOICE_MAPPING.keys()),
        'languages': list(LANGUAGE_MODELS.keys())
    })

@stt_tts_bp.route('/monitor', methods=['GET'])
def get_monitor_data():
    """Get real-time monitoring data for STT/TTS"""
    try:
        # Get recent logs for monitoring
        recent_logs = get_voice_logs(10)  # Last 10 entries
        
        # Check model status
        en_model = get_vosk_model_path('en')
        zh_model = get_vosk_model_path('zh')
        
        # Check if core modules are available
        stt_available = stt_tts_core is not None
        audio_capture_available = AUDIO_CAPTURE_AVAILABLE
        
        # Get current timestamp
        current_time = time.time()
        
        return jsonify({
            'success': True,
            'timestamp': current_time,
            'models': {
                'stt_core': stt_available,
                'audio_capture': audio_capture_available,
                'en_model': en_model is not None,
                'zh_model': zh_model is not None,
                'en_model_path': en_model,
                'zh_model_path': zh_model
            },
            'recent_activity': recent_logs,
            'system_status': 'running' if stt_available else 'error'
        })
        
    except Exception as e:
        logging.error(f"Monitor data error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@stt_tts_bp.route('/status', methods=['GET'])
def get_status():
    """Get STT/TTS system status"""
    try:
        # Check if models are available
        en_model = get_vosk_model_path('en')
        zh_model = get_vosk_model_path('zh')
        
        # Get audio devices if available
        audio_devices = []
        if AUDIO_CAPTURE_AVAILABLE:
            try:
                audio_capture = get_audio_capture()
                audio_devices = audio_capture.get_available_devices()
            except Exception as e:
                logging.error(f"Error getting audio devices: {e}")
        
        return jsonify({
            'success': True,
            'status': {
                'stt_tts_core_available': stt_tts_core is not None,
                'audio_capture_available': AUDIO_CAPTURE_AVAILABLE,
                'english_model_available': en_model is not None,
                'chinese_model_available': zh_model is not None,
                'available_voices': list(VOICE_MAPPING.keys()),
                'available_languages': list(LANGUAGE_MODELS.keys()),
                'audio_devices': audio_devices
            }
        })
        
    except Exception as e:
        logging.error(f"Status check error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@stt_tts_bp.route('/audio-devices', methods=['GET'])
def get_audio_devices():
    """Get available audio input devices"""
    try:
        if not AUDIO_CAPTURE_AVAILABLE:
            return jsonify({
                'success': False, 
                'error': 'Audio capture not available'
            }), 500
        
        audio_capture = get_audio_capture()
        devices = audio_capture.get_available_devices()
        
        return jsonify({
            'success': True,
            'devices': devices
        })
        
    except Exception as e:
        logging.error(f"Get audio devices error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Initialize database and API keys when module is imported
init_voice_db()
load_api_keys()
