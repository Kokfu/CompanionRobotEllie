# STT/TTS System - Main Code Highlights for Thesis

## 1. API Key Rotation Algorithm

### **File**: `stt_tts_api.py` & `stt_tts_bridge_standalone.py`

```python
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
```

**Key Innovation**: Automatic rotation through 5 API keys, providing 75 requests/day instead of 15.

---

## 2. Hybrid STT Engine (VOSK + Whisper Fallback)

### **File**: `stt_tts_bridge_standalone.py`

```python
def transcribe(wav16k_path: str, logger=None) -> str:
    global _vosk_available
    # Try VOSK first, fallback to Whisper
    if STT_ENGINE == "vosk" and _vosk_available:
        try:
            if logger: 
                logger.info(f"[debug] STT engine: vosk (model_dir={VOSK_MODEL_DIR})")
            return vosk_transcribe(wav16k_path)
        except Exception as e:
            if logger:
                logger.warning(f"[debug] VOSK failed: {e}, falling back to Whisper")
            _vosk_available = False
    
    # Fallback to Whisper
    if logger:
        logger.info(f"[debug] STT engine: whisper ({WHISPER_MODEL}, {WHISPER_COMPUTE}, lang={LANGUAGE_HINT})")
    return whisper_transcribe(wav16k_path)

def vosk_transcribe(wav16k_path: str) -> str:
    _init_vosk()
    if _vosk_model is None:
        raise RuntimeError("VOSK model not available")
    
    from vosk import KaldiRecognizer
    wf = wave.open(wav16k_path, "rb")
    rec = KaldiRecognizer(_vosk_model, wf.getframerate())
    text = ""
    while True:
        data = wf.readframes(4000)
        if not data:
            break
        if rec.AcceptWaveform(data):
            partial = json.loads(rec.Result()).get("text", "")
            if partial:
                text += (" " if text else "") + partial
    final = json.loads(rec.FinalResult()).get("text", "")
    if final:
        text += (" " if text else "") + final
    return text.strip()

def whisper_transcribe(wav16k_path: str) -> str:
    _init_whisper()
    segments, info = _whisper_model.transcribe(
        wav16k_path,
        language=LANGUAGE_HINT if LANGUAGE_HINT else None,
        beam_size=1,
        best_of=1,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=700),
        condition_on_previous_text=False
    )
    out = []
    for seg in segments:
        out.append(seg.text.strip())
    return " ".join(out).strip()
```

**Key Innovation**: Offline VOSK for privacy + online Whisper for accuracy, with automatic fallback.

---

## 3. Wake Word Detection Algorithm

### **File**: `stt_tts_bridge_standalone.py`

```python
def _wake_loop(self):
    while rclpy.ok() and not self._stop:
        time.sleep(WAKE_POLL_SEC)

        # Don't trigger while speaking
        if self._speaking_now:
            continue

        # Cooldown
        if (time.time() - self._last_trigger_ts) < COOLDOWN_SEC:
            continue

        # Need enough audio to check
        if len(self.ring) < int(SAMPLE_RATE * WAKE_LISTEN_SEC * SAMPLE_BYTES * CHANNELS):
            continue

        try:
            with tempfile.TemporaryDirectory() as td:
                probe_wav = os.path.join(td, "wake_probe.wav")
                self.dump_last_seconds_to_wav(WAKE_LISTEN_SEC, probe_wav)
                wav16k = ensure_wav_16k_mono_16bit(probe_wav)

                # Quick transcription just for wake detection
                txt = transcribe(wav16k, logger=self.get_logger()).lower()
                if not txt:
                    continue

                self.get_logger().info(f"[wake] heard: {txt!r}")

                if not REQUIRE_WAKE_WORD:
                    # Treat any speech as trigger
                    self._trigger_async()
                    continue

                # Wake-word check
                if any(w in txt for w in WAKE_WORDS):
                    self.get_logger().info("[wake] Wake word detected → triggering interaction.")
                    self._trigger_async()
        except Exception as e:
            self.get_logger().error(f"[wake] check failed: {e}")
```

**Key Innovation**: Continuous audio monitoring with ring buffer, real-time wake word detection.

---

## 4. Main Voice Interaction Pipeline

### **File**: `stt_tts_bridge_standalone.py`

```python
def _run_interaction(self, capture_sec: float):
    try:
        with tempfile.TemporaryDirectory() as td:
            in_wav  = os.path.join(td, "in.wav")
            out24   = os.path.join(td, "reply_24k.wav")
            out16   = os.path.join(td, "reply_16k.wav")

            # capture
            self.get_logger().info(f"[run] Capturing last {capture_sec:.1f}s …")
            self.dump_last_seconds_to_wav(capture_sec, in_wav)

            # STT
            self.get_logger().info("[run] Transcribing …")
            wav16k = ensure_wav_16k_mono_16bit(in_wav)
            said   = transcribe(wav16k, logger=self.get_logger())
            self.get_logger().info(f"[STT] {said!r}")

            if not said:
                return False, "No speech recognized."

            # Gemini
            self.get_logger().info("[run] Querying Gemini …")
            start_time = time.time()
            reply_text = gemini_chat(said, logger=self.get_logger())
            response_time = time.time() - start_time
            self.get_logger().info(f"[AI ] {reply_text!r}")

            # Log the complete interaction
            log_entry = {
                'ts': time.time(),
                'lang': LANGUAGE_HINT,
                'stt_engine': 'whisper' if not _vosk_available else 'vosk',
                'text_in': said,
                'text_out': reply_text,
                'voice': VOICE_NAME,
                'source': 'Voice Bridge'
            }
            insert_voice_log(log_entry)
            self.get_logger().info(f"[LOG] Voice interaction logged to database")

            # TTS
            self.get_logger().info("[run] Synthesizing speech …")
            pcm_24k = gemini_tts(reply_text, logger=self.get_logger())
            save_wav(out24, pcm_24k, channels=1, rate=OUT_RATE, sample_width=2)
            downsample_to_16k(out24, out16)

            with wave.open(out16, "rb") as wf:
                frames = wf.readframes(wf.getnframes())

            # Play
            self.get_logger().info("[run] Playing to /audio/speaker …")
            self._speaking_now = True
            try:
                self.publish_pcm16(frames, realtime=True)
                # Calculate audio duration
                audio_duration = len(frames) / (SAMPLE_RATE * SAMPLE_BYTES * CHANNELS)
                self.get_logger().info(f"[run] Audio output completed ({audio_duration:.2f}s)")
            finally:
                self._speaking_now = False

            return True, said
    except Exception as e:
        self.get_logger().error(f"[run] Interaction failed: {e}")
        return False, str(e)
```

**Key Innovation**: Complete end-to-end voice interaction with logging and real-time audio processing.

---

## 5. Gemini AI Integration with API Key Rotation

### **File**: `stt_tts_bridge_standalone.py`

```python
def gemini_chat(user_text: str, logger=None) -> str:
    max_retries = len(_api_keys) if _api_keys else 1
    
    for attempt in range(max_retries):
        try:
            # Get API key with rotation
            api_key = get_next_api_key()
            if not api_key:
                raise RuntimeError("No API keys available")
            
            # Set the API key in environment
            os.environ['GOOGLE_API_KEY'] = api_key
            
            from google import genai
            from google.genai import types as genai_types
            
            # Initialize client with explicit API key
            client = genai.Client(api_key=api_key)
            
            # Verify client is working
            if not client:
                raise RuntimeError("Failed to initialize Gemini client")
            
            cfg = genai_types.GenerateContentConfig(
                system_instruction=(
                    "You are a companion robot voice assistant. "
                    "Answer clearly and concisely (1–2 sentences). "
                    "If the user asks a command, acknowledge briefly."
                ),
                thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
                temperature=0.6,
            )
            
            resp = client.models.generate_content(
                model=GEMINI_CHAT_MODEL,
                contents=user_text,
                config=cfg,
            )
            reply = (resp.text or "").strip()
            if not reply:
                logger.error(f"[gemini_chat] No reply text returned from Gemini API.")
                return "Sorry, I didn't catch that."
            return reply
        except Exception as e:
            if logger:
                logger.warning(f"[gemini_chat] Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                continue
            else:
                logger.error(f"[gemini_chat] All API keys failed")
                return "Sorry, something went wrong with the chat service."

def gemini_tts(text: str, logger=None) -> bytes:
    max_retries = len(_api_keys) if _api_keys else 1
    
    for attempt in range(max_retries):
        try:
            # Get API key with rotation
            api_key = get_next_api_key()
            if not api_key:
                raise RuntimeError("No API keys available")
            
            # Set the API key in environment
            os.environ['GOOGLE_API_KEY'] = api_key
            
            from google import genai
            from google.genai import types as genai_types
            
            # Initialize client with explicit API key
            client = genai.Client(api_key=api_key)
            
            # Verify client is working
            if not client:
                raise RuntimeError("Failed to initialize Gemini client")
            
            resp = client.models.generate_content(
                model=GEMINI_TTS_MODEL,
                contents=text,
                config=genai_types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=genai_types.SpeechConfig(
                        voice_config=genai_types.VoiceConfig(
                            prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                                voice_name=VOICE_NAME
                            )
                        )
                    )
                ),
            )
            return resp.candidates[0].content.parts[0].inline_data.data  # raw PCM bytes
        except Exception as e:
            if logger:
                logger.warning(f"[gemini_tts] Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                continue
            else:
                logger.error(f"[gemini_tts] All API keys failed")
                raise RuntimeError("All API keys failed for TTS")
```

**Key Innovation**: Automatic API key rotation for both chat and TTS, with retry logic and error handling.

---

## 6. Audio Processing and PCM to WAV Conversion

### **File**: `stt_tts_api.py`

```python
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

def save_wav(path, pcm_bytes, channels=1, rate=OUT_RATE, sample_width=2):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_bytes)
```

**Key Innovation**: Efficient PCM to WAV conversion for web browser compatibility.

---

## 7. Voice Logging Database System

### **File**: `stt_tts_bridge_standalone.py`

```python
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
    try:
        with sqlite3.connect(VOICE_LOG_DB) as con:
            con.execute("""
                INSERT INTO voice_logs (ts, lang, stt_engine, text_in, text_out, voice, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.get("ts"), entry.get("lang"), entry.get("stt_engine"),
                entry.get("text_in"), entry.get("text_out"),
                entry.get("voice"), entry.get("source")
            ))
    except sqlite3.IntegrityError:
        # Duplicate entry; ignore
        pass
    except Exception as e:
        print(f"Failed to store voice log: {e}")
```

**Key Innovation**: Complete voice interaction logging with duplicate prevention and replay capability.

---

## 8. ROS2 Audio Publishing

### **File**: `stt_tts_bridge_standalone.py`

```python
def publish_pcm16(self, pcm_bytes: bytes, realtime: bool = True):
    if not realtime:
        msg = UInt8MultiArray()
        msg.data = list(pcm_bytes)
        self.pub.publish(msg)
        return
    idx = 0
    period = FRAME_MS / 1000.0
    while idx < len(pcm_bytes):
        chunk = pcm_bytes[idx: idx + FRAME_BYTES]
        if not chunk:
            break
        msg = UInt8MultiArray()
        msg.data = list(chunk)
        self.pub.publish(msg)
        idx += len(chunk)
        time.sleep(period)
```

**Key Innovation**: Real-time audio streaming to robot speakers with frame-based publishing.

---

## 9. Web UI API Endpoints

### **File**: `stt_tts_api.py`

```python
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
```

**Key Innovation**: RESTful API for web-based voice control with audio data streaming.

---

## Summary of Key Innovations

1. **API Key Rotation**: 5x quota increase through automatic key rotation
2. **Hybrid STT**: Offline VOSK + online Whisper fallback
3. **Wake Word Detection**: Continuous audio monitoring with ring buffer
4. **Voice Logging**: Complete interaction history with replay
5. **Real-time Audio**: ROS2-based audio streaming
6. **Web Integration**: Browser-based voice control
7. **Error Handling**: Robust fallback mechanisms
8. **Audio Processing**: Efficient PCM to WAV conversion

These code sections represent the core technical innovations of the STT/TTS system suitable for thesis documentation.
