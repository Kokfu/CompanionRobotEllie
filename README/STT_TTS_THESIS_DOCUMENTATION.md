# STT/TTS System - Thesis Documentation

## Overview
This document highlights the core STT/TTS (Speech-to-Text/Text-to-Speech) implementation for the TurtleBot Web UI project. The system provides voice interaction capabilities with wake word detection, multi-language support, and AI-powered responses.

## Core Architecture

### 1. Main Components

#### **stt_tts_api.py** - Web UI Integration Layer
- **Purpose**: Flask Blueprint providing REST API endpoints for STT/TTS functionality
- **Key Features**:
  - API key rotation for quota management (5 keys)
  - Voice selection (Kore, Aoede, Charon)
  - Language support (English, Chinese)
  - Audio data conversion (PCM to WAV)
  - Voice logging to SQLite database

#### **stt_tts_bridge_standalone.py** - ROS2 Voice Bridge
- **Purpose**: Standalone ROS2 node for continuous voice interaction
- **Key Features**:
  - Wake word detection ("hey", "nexo", "hey nexo")
  - Continuous audio monitoring
  - STT engine selection (VOSK/Whisper)
  - Gemini AI integration for responses
  - ROS2 topic publishing (/audio/speaker, /audio/mic)

#### **start_voice_bridge.py** - System Launcher
- **Purpose**: Environment setup and bridge initialization
- **Key Features**:
  - Dynamic VOSK model path configuration
  - Environment variable setup
  - Process management

### 2. Technical Implementation

#### **STT Engine Configuration**
```python
# Dual STT engine support
STT_ENGINE = "vosk"  # Primary: VOSK (offline)
WHISPER_MODEL = "base.en"  # Fallback: Whisper (online)
```

#### **TTS Engine Configuration**
```python
# Gemini TTS with multiple voices
GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"
VOICE_OPTIONS = {
    'Kore': 'Men\'s voice',
    'Aoede': 'Girl\'s voice', 
    'Charon': 'Soft child\'s voice'
}
```

#### **API Key Management**
```python
# Rotating API keys for quota management
GENAI_API_KEYS = "key1,key2,key3,key4,key5"  # 5 keys = 75 requests/day
```

### 3. Key Algorithms

#### **Wake Word Detection**
- **Method**: Continuous audio monitoring with sliding window
- **Parameters**: 1.0s polling, 2.5s window, 3.0s cooldown
- **Implementation**: Real-time audio processing with ring buffer

#### **Audio Processing Pipeline**
1. **Input**: 16kHz mono audio from robot microphone
2. **Processing**: Ring buffer (15 seconds) for continuous monitoring
3. **STT**: VOSK (offline) or Whisper (online) transcription
4. **AI Response**: Gemini 2.5 Flash for intelligent responses
5. **TTS**: Gemini TTS with voice selection
6. **Output**: 24kHz audio to robot speakers

#### **API Key Rotation Algorithm**
```python
def get_next_api_key():
    current_key = _api_keys[_current_key_index]
    _current_key_index = (_current_key_index + 1) % len(_api_keys)
    return current_key
```

### 4. Database Schema

#### **Voice Logs (voice_logs.db)**
```sql
CREATE TABLE voice_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,                    -- Timestamp
    lang TEXT,                  -- Language
    stt_engine TEXT,           -- STT engine used
    text_in TEXT,              -- Input speech
    text_out TEXT,             -- AI response
    voice TEXT,                -- TTS voice used
    source TEXT                -- Source (Voice Bridge, Web UI, etc.)
);
```

### 5. ROS2 Integration

#### **Topics**
- `/audio/mic` - Audio input from robot microphone
- `/audio/speaker` - Audio output to robot speakers

#### **Services**
- `/voice/do_interaction` - Manual trigger for voice interaction

### 6. Web UI Integration

#### **API Endpoints**
- `POST /api/stt-tts/start-stt` - Manual STT trigger
- `POST /api/stt-tts/tts` - Text-to-speech conversion
- `POST /api/stt-tts/test-voice` - Voice testing
- `POST /api/stt-tts/direct-tts` - Direct TTS (for replay)
- `GET /api/stt-tts/logs` - Voice interaction history
- `GET /api/stt-tts/voices` - Available voices

#### **Frontend Features**
- Real-time voice selection
- Language switching
- Voice log replay
- Live activity monitoring
- Audio level visualization

### 7. Performance Optimizations

#### **Quota Management**
- 5 API keys rotating automatically
- 75 requests/day capacity (5 × 15)
- Automatic fallback between keys

#### **Audio Processing**
- Ring buffer for efficient memory usage
- PCM to WAV conversion for web compatibility
- Downsampling for optimal performance

#### **Error Handling**
- Graceful fallback from VOSK to Whisper
- API key rotation on quota exhaustion
- Robust error recovery mechanisms

### 8. Configuration Management

#### **Environment Variables**
```bash
# STT Configuration
STT_ENGINE=vosk
VOSK_MODEL_DIR=/path/to/vosk-model-small-en-us-0.15
LANGUAGE_HINT=en

# TTS Configuration  
GEMINI_TTS_MODEL=gemini-2.5-flash-preview-tts
VOICE_NAME=Kore

# Wake Word Settings
REQUIRE_WAKE_WORD=true
WAKE_WORDS=hey,nexo,hey nexo
WAKE_POLL_SEC=1.0
WAKE_LISTEN_SEC=2.5
COOLDOWN_SEC=3.0

# API Keys
GENAI_API_KEYS=key1,key2,key3,key4,key5
```

### 9. Key Innovations

1. **Hybrid STT Approach**: VOSK (offline) + Whisper (online) fallback
2. **API Key Rotation**: Automatic quota management across multiple keys
3. **Voice Logging**: Complete interaction history with replay capability
4. **Web UI Integration**: Seamless browser-based voice control
5. **ROS2 Bridge**: Real-time robot audio integration
6. **Multi-language Support**: English and Chinese language processing

### 10. System Flow

```
Audio Input → Wake Word Detection → STT → AI Processing → TTS → Audio Output
     ↓              ↓                ↓         ↓          ↓         ↓
Robot Mic → Continuous Monitor → VOSK/Whisper → Gemini → Gemini TTS → Robot Speaker
     ↓              ↓                ↓         ↓          ↓         ↓
Web UI ← API Endpoints ← Voice Logs ← Database ← Response ← Audio Data ← WAV Conversion
```

This architecture provides a robust, scalable voice interaction system suitable for robotic applications with comprehensive logging and web-based management capabilities.
