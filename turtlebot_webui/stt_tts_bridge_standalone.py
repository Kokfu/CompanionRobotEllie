#!/usr/bin/env python3
"""
Standalone Voice Bridge - Works without web UI integration
"""

import os, sys, time, wave, tempfile, json, subprocess, threading, random, sqlite3
from collections import deque

import rclpy
from rclpy.node import Node
from std_srvs.srv import Trigger
from std_msgs.msg import UInt8MultiArray

# =========================
# ---- Config via env -----
# =========================
STT_ENGINE        = os.environ.get("STT_ENGINE", "vosk").lower()   # "whisper" or "vosk"
VOSK_MODEL_DIR    = os.environ.get("VOSK_MODEL_DIR", "")
WHISPER_MODEL     = os.environ.get("WHISPER_MODEL", "base.en")     # "base.en", "small.en", etc.
WHISPER_COMPUTE   = os.environ.get("WHISPER_COMPUTE", "int8")      # "int8" | "int8_float32" | "float32"
LANGUAGE_HINT     = os.environ.get("LANGUAGE_HINT", "en")          # "en","ms","zh",...

GEMINI_CHAT_MODEL = os.environ.get("GEMINI_CHAT_MODEL", "gemini-2.5-flash")
GEMINI_TTS_MODEL  = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
VOICE_NAME        = os.environ.get("VOICE_NAME", "Kore")

IN_RATE           = int(os.environ.get("IN_RATE", "16000"))
OUT_RATE          = int(os.environ.get("OUT_RATE", "24000"))

# --- Wake word settings (all optional, tweak as you like) ---
REQUIRE_WAKE_WORD = os.environ.get("REQUIRE_WAKE_WORD", "true").lower() in ("1","true","yes","on")
WAKE_WORDS_ENV    = os.environ.get("WAKE_WORDS", "hey, nexo, hey nexo")
WAKE_WORDS        = [w.strip().lower() for w in WAKE_WORDS_ENV.split(",") if w.strip()]
WAKE_POLL_SEC     = float(os.environ.get("WAKE_POLL_SEC", "1.0"))   # how often to check
WAKE_LISTEN_SEC   = float(os.environ.get("WAKE_LISTEN_SEC", "2.5")) # window length for wake detection
COOLDOWN_SEC      = float(os.environ.get("COOLDOWN_SEC", "3.0"))    # min gap between triggers

# =========================
# ---- Audio framing  -----
# =========================
SAMPLE_RATE  = 16000
CHANNELS     = 1
SAMPLE_BYTES = 2
FRAME_MS     = 120
FRAME_BYTES  = int(SAMPLE_RATE * (FRAME_MS/1000.0) * SAMPLE_BYTES * CHANNELS)

RING_SECONDS = 15
RING_BYTES   = SAMPLE_RATE * RING_SECONDS * SAMPLE_BYTES * CHANNELS

# =========================
# --- Voice Logging ---
# =========================
VOICE_LOG_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'voice_logs.db')

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

# =========================
# --- API Key Management ---
# =========================
_api_keys = []
_current_key_index = 0
_key_usage_count = {}

def load_api_keys():
    """Load and rotate API keys from environment variables"""
    global _api_keys, _current_key_index
    
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
    
    # Fallback to GOOGLE_API_KEY
    if not _api_keys:
        google_key = os.environ.get("GOOGLE_API_KEY", "")
        if google_key:
            _api_keys = [google_key]
    
    # Initialize usage tracking
    for key in _api_keys:
        _key_usage_count[key] = 0
    
    print(f"[API] Loaded {len(_api_keys)} API keys")
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
    
    print(f"[API] Using key {_current_key_index + 1}/{len(_api_keys)} (usage: {_key_usage_count[current_key]})")
    return current_key

# =========================
# --- Lazy-initialized STT/TTS helpers ---
# =========================
_vosk_model = None
_whisper_model = None
_vosk_available = True

# Ensure multiple possible paths are importable to find test_speech.py
POSSIBLE_PATHS = [
    os.path.dirname(os.path.abspath(__file__)),  # current directory
    os.path.expanduser('~/'),  # home directory
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # parent of v3
]

for path in POSSIBLE_PATHS:
    if path not in sys.path:
        sys.path.insert(0, path)

try:
    import test_speech as stt_tts_core
    print(f"[stt_tts_bridge] Successfully imported test_speech from {stt_tts_core.__file__}")
except ImportError as e:
    print(f"[stt_tts_bridge] Failed to import test_speech: {e}")
    print(f"[stt_tts_bridge] Searched paths: {POSSIBLE_PATHS}")
    sys.exit(1)

def ensure_wav_16k_mono_16bit(src_path: str) -> str:
    """Return a path to a 16kHz mono 16-bit PCM WAV copy of src_path."""
    with tempfile.TemporaryDirectory() as td:
        dst = os.path.join(td, "out.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-i", src_path, "-ar", str(IN_RATE), "-ac", "1",
             "-sample_fmt", "s16", dst],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
        )
        final = os.path.abspath("temp_16k.wav")
        subprocess.run(["cp", dst, final], check=True)
    return final

# ---- Vosk ----
def _init_vosk(logger=None):
    global _vosk_model, _vosk_available
    if _vosk_model is None and _vosk_available:
        try:
            from vosk import Model
            if not VOSK_MODEL_DIR:
                raise RuntimeError("VOSK_MODEL_DIR is not set")
            if logger:
                logger.info(f"[init] Loading Vosk model from: {VOSK_MODEL_DIR}")
            
            # Load model with timeout to prevent hanging
            import signal
            
            def timeout_handler(signum, frame):
                raise TimeoutError("VOSK model loading timed out")
            
            # Set timeout for model loading (120 seconds for small model)
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(120)
            
            _vosk_model = Model(VOSK_MODEL_DIR)
            signal.alarm(0)  # Cancel timeout
            
            if logger:
                logger.info("[init] Vosk model loaded successfully")
        except TimeoutError:
            if logger:
                logger.error("[init] VOSK model loading timed out - switching to Whisper")
            _vosk_available = False
        except Exception as e:
            if logger:
                logger.error(f"[init] Failed to load VOSK model: {e} - switching to Whisper")
            _vosk_available = False

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

# ---- Whisper (faster-whisper) ----
def _init_whisper(logger=None):
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        if logger:
            logger.info(f"[init] Loading Whisper model={WHISPER_MODEL} compute={WHISPER_COMPUTE} device=cpu lang={LANGUAGE_HINT}")
        _whisper_model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type=WHISPER_COMPUTE)

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
    
    # Use Whisper as backup
    if logger: 
        logger.info(f"[debug] STT engine: whisper ({WHISPER_MODEL}, {WHISPER_COMPUTE}, lang={LANGUAGE_HINT})")
    return whisper_transcribe(wav16k_path)

# ---- Gemini Chat & TTS ----
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

def save_wav(path, pcm_bytes, channels=1, rate=OUT_RATE, sample_width=2):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_bytes)

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
                    ),
                ),
            )
            # raw 24k PCM bytes
            return resp.candidates[0].content.parts[0].inline_data.data
        except Exception as e:
            if logger:
                logger.warning(f"[gemini_tts] Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                continue
            else:
                logger.error(f"[gemini_tts] All API keys failed")
                raise e

def downsample_to_16k(src_wav: str, dst_wav: str):
    subprocess.run(
        ["ffmpeg", "-y", "-i", src_wav, "-ar", str(IN_RATE), "-ac", "1", dst_wav],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
    )

# =========================
# --------- ROS2 ----------
# =========================
class SttTtsBridge(Node):
    def __init__(self):
        super().__init__('stt_tts_bridge')

        # Initialize voice logging database
        init_voice_db()

        # Load API keys
        if not load_api_keys():
            self.get_logger().error("No API keys available! Please check your .env file.")
            return

        # Keep your original RELIABLE defaults by passing an integer depth (10)
        self.sub = self.create_subscription(UInt8MultiArray, '/audio/mic', self.on_mic, 10)
        self.pub = self.create_publisher(UInt8MultiArray, '/audio/speaker', 10)
        self.srv = self.create_service(Trigger, '/voice/do_interaction', self.handle_interaction)

        self.ring = deque(maxlen=RING_BYTES)  # byte ring buffer

        # Debug summary at startup
        self.get_logger().info("===== Standalone Voice Bridge Started =====")
        self.get_logger().info(f"STT_ENGINE={STT_ENGINE}  (vosk model={VOSK_MODEL_DIR} | whisper model={WHISPER_MODEL}, compute={WHISPER_COMPUTE}, lang={LANGUAGE_HINT})")
        self.get_logger().info(f"Gemini chat={GEMINI_CHAT_MODEL}, tts={GEMINI_TTS_MODEL}, voice={VOICE_NAME}")
        self.get_logger().info(f"API Keys: {len(_api_keys)} keys loaded with rotation")
        self.get_logger().info(f"Wake: REQUIRE_WAKE_WORD={REQUIRE_WAKE_WORD}, words={WAKE_WORDS}, poll={WAKE_POLL_SEC}s, window={WAKE_LISTEN_SEC}s, cooldown={COOLDOWN_SEC}s")
        self.get_logger().info("Call /voice/do_interaction OR just say a wake word to trigger.")
        self.get_logger().info("================================")

        # Wake-word polling thread (no extra deps; reuses your STT)
        self._stop = False
        self._speaking_now = False
        self._last_trigger_ts = 0.0
        self._wake_thread = threading.Thread(target=self._wake_loop, daemon=True)
        self._wake_thread.start()

    # ---- Audio RX ----
    def on_mic(self, msg: UInt8MultiArray):
        self.ring.extend(bytes(msg.data))

    # ---- Utilities ----
    def get_ring_snapshot(self, seconds: float) -> bytes:
        need_bytes = int(SAMPLE_RATE * seconds * SAMPLE_BYTES * CHANNELS)
        buf = bytes(self.ring)
        return buf[-need_bytes:] if len(buf) >= need_bytes else buf

    def dump_last_seconds_to_wav(self, seconds: float, path: str):
        data = self.get_ring_snapshot(seconds)
        self.get_logger().info(f"[debug] ring_size={len(bytes(self.ring))} bytes, dump={len(data)} bytes")
        with wave.open(path, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(SAMPLE_BYTES)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(data)

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

    # ---- Manual trigger (service) ----
    def handle_interaction(self, req, resp):
        ok, said = self._run_interaction(capture_sec=7.0)
        resp.success = ok
        resp.message = "OK. Said: " + said if ok else said
        return resp

    # ---- Wake-loop: periodically look for wake words in recent audio ----
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

    def _trigger_async(self):
        self._last_trigger_ts = time.time()
        threading.Thread(target=self._run_interaction, kwargs=dict(capture_sec=7.0), daemon=True).start()

    # ---- The main pipeline: STT → LLM → TTS → publish ----
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

def main():
    rclpy.init()
    node = SttTtsBridge()
    try:
        rclpy.spin(node)
    finally:
        node._stop = True
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
