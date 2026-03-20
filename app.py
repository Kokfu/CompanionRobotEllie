from flask import Flask, render_template, Response, jsonify, request, render_template_string
from werkzeug.utils import secure_filename
import threading, json, time, sqlite3, os, signal
import roslibpy
import cv2
import numpy as np
import base64
import logging
import requests
import warnings
from datetime import datetime
from collections import deque
from pathlib import Path
from PIL import Image
from nav_backend import nav_bp, start_ros  # <-- NEW
from stt_tts_api import stt_tts_bp  # <-- NEW STT/TTS API
from config import get_config, update_robot_config, update_ui_config, reset_config
from utils import log_app, log_ros, log_error, log_telemetry, log_fall_detection, get_state, set_state, update_settings
import subprocess

# Suppress TensorFlow Lite cleanup warnings
warnings.filterwarnings("ignore", category=UserWarning, module="tflite_runtime")
warnings.filterwarnings("ignore", message=".*Delegate.*")
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # Suppress TensorFlow warnings

# ---- Logging setup (quiet noisy libs) ----
import logging, sys
root = logging.getLogger()
if not root.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
logging.getLogger('werkzeug').setLevel(logging.WARNING)
logging.getLogger('roslibpy').setLevel(logging.WARNING)


# ---------------- Prerequisite ----------------
try:
    from dotenv import load_dotenv, find_dotenv
    # Load .env from the current file directory or its parents
    load_dotenv(find_dotenv(), override=True)
    # Fallback: also try alongside app.py explicitly
    load_dotenv(dotenv_path=Path(__file__).parent / '.env', override=True)
except Exception as e:
    log_app(f"[env] dotenv not active: {e}", level=logging.WARNING)
    
# ---------------- UI app ----------------
app = Flask(__name__)

# Register blueprints and start ROS2 background thread
app.register_blueprint(nav_bp)   # routes under /api/nav/*
app.register_blueprint(stt_tts_bp)  # routes under /api/stt-tts/*
start_ros()

# --- ROSBridge configuration ---
# Get the ROSBridge IP address from the user (instead of reading from the config file)
def get_rosbridge_ip():
    try:
        rosbridge_ip = input("Enter ROSBridge IP address (default: 192.168.1.100): ")
        if not rosbridge_ip:
            rosbridge_ip = '192.168.1.100'  # default IP if user presses Enter without input
        return rosbridge_ip
    except EOFError:
        # If running in non-interactive environment, use default
        print("Using default ROSBridge IP: 192.168.1.100")
        return '192.168.1.100'

# Update config with user-provided IP
ROSBridge_IP = get_rosbridge_ip()
ROSBridge_PORT = 9090  # or set this dynamically as well if needed

# Setup ROS connection with dynamic IP
ros = roslibpy.Ros(host=ROSBridge_IP, port=ROSBridge_PORT)

VOICE_LOG_DB = os.path.join(os.getcwd(), 'voice_logs.db')

# ---------------- External process handles (optional) ----------------
global stt_tts_proc
global pan_tilt_proc
stt_tts_proc = None
pan_tilt_proc = None

telemetry_data = {
    'battery_level': 0.0,
    'connected': False,
    'last_update': None,
    'camera_status': 'Not Active',
    'camera_last_update': None
}

_last_batt_ts = 0.0
_last_image_ts = 0.0
battery_sub = None
cmd_vel_pub = None
image_sub = None

# latest RGB frame for the web stream
latest_image = None
image_lock = threading.Lock()

# Telemetry log throttling
_last_tlog_ts = 0.0
_last_batt_logged = None
_TELEM_MIN_PERIOD = 3.0   # seconds
_TELEM_MIN_DELTA  = 0.5   # percent points


# ---------- Alerts config ----------
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')  # set in your shell or .env
TELEGRAM_CHAT_ID   = os.getenv('TELEGRAM_CHAT_ID', '')    # your user/chat ID
ALERT_COOLDOWN_SEC = int(os.getenv('FALL_ALERT_COOLDOWN', '120'))  # avoid spamming
REQUIRE_CONFIRM_SEC = int(os.getenv('FALL_REQUIRE_CONFIRM', '30')) # wait for acks later (voice hook)

# ---------- Telegram Bot config ----------
TELEGRAM_WEBHOOK_SECRET = os.getenv('TELEGRAM_WEBHOOK_SECRET', 'your_webhook_secret')
TELEGRAM_ALLOWED_USERS = os.getenv('TELEGRAM_ALLOWED_USERS', '').split(',') if os.getenv('TELEGRAM_ALLOWED_USERS') else []

# Telegram bot polling state
telegram_last_update_id = 0
telegram_polling_enabled = True


# ---------------- fall model wiring ----------------
# Where the fall repo lives (use local directory)
REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fall-detection-main')
if REPO_ROOT not in os.sys.path:
    os.sys.path.insert(0, REPO_ROOT)

# Import the repo's API
from fall_prediction import Fall_prediction

# Import HumanFallDetection wrapper
try:
    from human_fall_detection_wrapper import get_human_fall_detector, is_human_fall_detection_available
    HUMAN_FALL_DETECTION_AVAILABLE = is_human_fall_detection_available()
except ImportError as e:
    log_app(f"HumanFallDetection wrapper not available: {e}", level=logging.WARNING)
    HUMAN_FALL_DETECTION_AVAILABLE = False

# Patch the repo’s label path bug once, so it works from our UI folder too.
# (fall_prediction.py builds model paths relative to its own file except labels)
import importlib, types
fp_mod = importlib.import_module('fall_prediction')
_orig_cfg = fp_mod._fall_detect_config

def _patched_cfg():
    cfg = _orig_cfg()
    # Ensure labels is absolute, not relative
    here = os.path.dirname(os.path.abspath(fp_mod.__file__))
    labels_abs = os.path.join(here, 'ai_models', 'pose_labels.txt')
    cfg['labels'] = labels_abs
    return cfg

fp_mod._fall_detect_config = _patched_cfg

# Ring buffer for 3-frame inference (PIL Images)
infer_buf = deque(maxlen=3)
# Drop most frames on decode: keep every Nth to stay lightweight
DECODE_STRIDE = int(os.getenv('FALL_DECODE_STRIDE', '4'))  # keep 1 of every 4 decoded frames
_decode_count = 0

# Desired inference FPS
INFER_FPS = float(os.getenv('FALL_INFER_FPS', '2.0'))
CONF_THRESH = float(os.getenv('FALL_CONF_THRESH', '0.7'))

# Fall model mode: 'internal' (default), 'ros2', 'humanfall', or 'hybrid'
FALL_MODEL_MODE = os.getenv('FALL_MODEL_MODE', 'internal').lower()
# External ROS fall topic (String or JSON string)
FALL_ROS_TOPIC = os.getenv('FALL_ROS_TOPIC', '/fall/state')
# HumanFallDetection settings
HUMAN_FALL_DISABLE_CUDA = os.getenv('HUMAN_FALL_DISABLE_CUDA', 'true').lower() == 'true'
HUMAN_FALL_CONF_THRESH = float(os.getenv('HUMAN_FALL_CONF_THRESH', '0.7'))

# Shared fall state for overlay + API
fall_state = {
    'label': 'no fall',
    'confidence': 0.0,
    'angle': 0.0,
    'ts': None,
    '_last_alert_ts' : 0.0,
    '_last_status'  : 'no fall'
}

# Telegram alert cooldown to prevent spam
TELEGRAM_ALERT_COOLDOWN = 30  # 30 seconds cooldown between alerts

# Secondary state from external ROS fall detector
fall_state_ros = {
    'label': 'no fall',
    'confidence': 0.0,
    'angle': 0.0,
    'ts': None
}

# Tertiary state from HumanFallDetection (direct integration)
fall_state_human = {
    'label': 'no fall',
    'confidence': 0.0,
    'angle': 0.0,
    'ts': None
}

def _classify(result: dict, conf_threshold: float):
    label = (result or {}).get('category', '') or ''
    conf = float(result.get('confidence', 0.0)) if result else 0.0
    angle = float(result.get('angle', 0.0)) if result else 0.0
    is_fall = (label.lower() == 'fall') and conf >= conf_threshold
    return is_fall, label, conf, angle

def fall_worker():
    """Run the fall detection models at ~INFER_FPS using frames queued by update_image_data()."""
    period = 1.0 / max(0.1, INFER_FPS)
    print(f"[fall] Inference loop running at ~{INFER_FPS:.1f} FPS")
    
    # Initialize HumanFallDetection if needed
    human_fall_detector = None
    if FALL_MODEL_MODE in ('humanfall', 'hybrid') and HUMAN_FALL_DETECTION_AVAILABLE:
        try:
            human_fall_detector = get_human_fall_detector(disable_cuda=HUMAN_FALL_DISABLE_CUDA)
            log_app("HumanFallDetection initialized successfully")
        except Exception as e:
            log_error(f"Failed to initialize HumanFallDetection: {e}")
            human_fall_detector = None
    
    while True:
        time.sleep(period)
        try:
            if len(infer_buf) < 3:
                continue
            
            # Process with fall-detection-main (internal model)
            if FALL_MODEL_MODE in ('internal', 'hybrid'):
                # Snapshot 3 frames (oldest->newest)
                img1, img2, img3 = infer_buf[0], infer_buf[1], infer_buf[2]
                # Model expects PIL.Image inputs
                result = Fall_prediction(img1, img2, img3)
                is_fall, label, conf, angle = _classify(result, CONF_THRESH)
                with image_lock:
                    # update internal state only; final combination happens in generate_frames()
                    fall_state['label'] = 'FALL' if is_fall else 'no fall'
                    fall_state['confidence'] = conf
                    fall_state['angle'] = angle
                    fall_state['ts'] = datetime.now().strftime('%H:%M:%S')
                # Log fall detection result
                prev = fall_state.get('_last_status', 'no fall')
                curr = 'FALL' if is_fall else 'no fall'
                # Log only on transitions, or periodic high-confidence falls
                if curr != prev or (is_fall and conf >= max(0.9, CONF_THRESH + 0.15)):
                    log_fall_detection(f"[internal] {curr}", conf, angle)
                    
                    # Send Telegram alert when fall is detected on live camera (with cooldown)
                    current_time = time.time()
                    if is_fall and conf >= CONF_THRESH and (current_time - fall_state.get('_last_alert_ts', 0)) > TELEGRAM_ALERT_COOLDOWN:
                        try:
                            photo_bytes = get_latest_jpeg()
                            alert_message = f"🚨 FALL DETECTED!\n\nConfidence: {conf:.2f}\nAngle: {angle:.1f}°\nTime: {datetime.now().strftime('%H:%M:%S')}"
                            telegram_send(alert_message, photo_bytes=photo_bytes)
                            fall_state['_last_alert_ts'] = current_time
                            log_app(f"Telegram fall alert sent - Confidence: {conf:.2f}")
                        except Exception as e:
                            log_error(f"Failed to send Telegram fall alert: {e}")
            
            # Process with HumanFallDetection (direct integration)
            if FALL_MODEL_MODE in ('humanfall', 'hybrid') and human_fall_detector is not None:
                # Get the latest frame from the buffer
                latest_frame = infer_buf[-1]
                # Convert PIL to numpy array (RGB to BGR for OpenCV)
                frame_np = np.array(latest_frame)
                frame_bgr = cv2.cvtColor(frame_np, cv2.COLOR_RGB2BGR)
                
                # Process frame
                result = human_fall_detector.process_frame(frame_bgr)
                
                if 'error' not in result:
                    is_fall = result['is_fall']
                    conf = result['confidence']
                    angle = result['angle']
                    
                    with image_lock:
                        fall_state_human['label'] = 'FALL' if is_fall else 'no fall'
                        fall_state_human['confidence'] = conf
                        fall_state_human['angle'] = angle
                        fall_state_human['ts'] = datetime.now().strftime('%H:%M:%S')
                    
                    # Log fall detection result
                    prev = fall_state_human.get('_last_status', 'no fall')
                    curr = 'FALL' if is_fall else 'no fall'
                    # Log only on transitions, or periodic high-confidence falls
                    if curr != prev or (is_fall and conf >= max(0.9, HUMAN_FALL_CONF_THRESH + 0.15)):
                        log_fall_detection(f"[humanfall] {curr}", conf, angle)

        except Exception as e:
            log_error(f"Fall detection model error: {e}", e)
            
def diagnostics_worker():
    warn_interval = 10.0   # seconds without data => warn
    last_warned = {'/battery_state': 0.0, '/camera/image_raw/compressed': 0.0}
    while True:
        now = time.time()
        if _last_batt_ts and (now - _last_batt_ts) > warn_interval and (now - last_warned['/battery_state']) > warn_interval:
            logging.warning("No data from /battery_state for %.1fs (check publisher/subscription).", now - _last_batt_ts)
            last_warned['/battery_state'] = now
        if _last_image_ts and (now - _last_image_ts) > warn_interval and (now - last_warned['/camera/image_raw/compressed']) > warn_interval:
            logging.warning("No data from /camera/image_raw/compressed for %.1fs (camera or bridge issue?).", now - _last_image_ts)
            last_warned['/camera/image_raw/compressed'] = now
        time.sleep(2.0)


# --- Voice log helpers ---  (add near the top after imports)


def init_voice_db():
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
        # prevent exact duplicates (same timestamp + texts)
        con.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_voice_unique
        ON voice_logs(ts, text_in, text_out);
        """)


def insert_voice_log(entry):
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
    with sqlite3.connect(VOICE_LOG_DB) as con:
        con.row_factory = sqlite3.Row
        return [
            dict(row) for row in con.execute(
                "SELECT ts, lang, stt_engine, text_in, text_out, voice, source FROM voice_logs ORDER BY id DESC LIMIT ?",
                (limit,)
            )
        ]

def clear_voice_logs():
    with sqlite3.connect(VOICE_LOG_DB) as con:
        con.execute("DELETE FROM voice_logs")

def store_voice_log(msg):
    try:
        data = json.loads(msg['data'])
        # round ts to 0.1s so repeated re-publishes in the same instant collapse
        data['ts'] = float(data.get('ts', time.time()))
        insert_voice_log(data)  # UNIQUE index will drop duplicates
    except sqlite3.IntegrityError:
        # duplicate; ignore
        pass
    except Exception as e:
        print(f"Failed to store voice log: {e}")

# ---------------- ROS connect / subscribers ----------------
def _on_fall_msg_ros(message):
    try:
        data = message.get('data', '')
        # Process the fall message data (label, confidence, angle)
        label = 'no fall'
        conf = 0.0
        angle = 0.0
        if isinstance(data, str):
            try:
                obj = json.loads(data)
                label = str(obj.get('label', obj.get('category', 'no fall')))
                conf = float(obj.get('confidence', obj.get('conf', 0.0)))
                angle = float(obj.get('angle', 0.0))
            except Exception:
                label = data
        else:
            label = str(data)

        with image_lock:
            fall_state_ros['label'] = 'FALL' if label.lower() == 'fall' else 'no fall'
            fall_state_ros['confidence'] = conf
            fall_state_ros['angle'] = angle
            fall_state_ros['ts'] = datetime.now().strftime('%H:%M:%S')
    except Exception as e:
        log_error(f"Failed to parse external fall state: {e}")


def connect_to_ros():
    """Connect to ROSBridge and set up subscribers (with retries)."""
    global battery_sub, cmd_vel_pub, image_sub, pan_pub, tilt_pub
    backoff = 2
    connected = False  # Track if connection was made

    def on_connect():
        nonlocal connected
        log_ros("Connected to ROSBridge server")
        connected = True
        telemetry_data['connected'] = True
        telemetry_data['last_update'] = datetime.now().isoformat()
        log_telemetry({'connected': True})

    def on_disconnect():
        nonlocal connected
        if connected:
            log_error("Disconnected from ROSBridge")
        connected = False
        telemetry_data['connected'] = False

    def on_error(error):
        nonlocal connected
        if connected:
            log_error(f"ROSBridge error: {error}")
        connected = False
        telemetry_data['connected'] = False

    # Set up event handlers
    ros.on('connection', on_connect)
    ros.on('disconnection', on_disconnect)
    ros.on('error', on_error)

    while True:
        try:
            if not connected:
                log_ros(f"Connecting to ROSBridge ws://{ROSBridge_IP}:{ROSBridge_PORT} ...")
            
            # Connect to ROSBridge
            ros.run()  # Connect to ROSBridge
            
            # Set up ROS subscribers and publishers
            battery_sub = roslibpy.Topic(ros, '/battery_state', 'sensor_msgs/BatteryState')
            battery_sub.subscribe(update_battery_data)

            image_sub = roslibpy.Topic(ros, '/camera/image_raw/compressed', 'sensor_msgs/CompressedImage')
            image_sub.subscribe(update_image_data)

            cmd_vel_pub = roslibpy.Topic(ros, '/cmd_vel', 'geometry_msgs/Twist')

            if FALL_MODEL_MODE in ('ros2', 'hybrid'):
                fall_sub = roslibpy.Topic(ros, FALL_ROS_TOPIC, 'std_msgs/String')
                fall_sub.subscribe(_on_fall_msg_ros)

            # Pan/Tilt topics (using the topics from pan_tilt_ros_onefile.py)
            pan_angle_sub = roslibpy.Topic(ros, '/pan/angle', 'std_msgs/Int32')
            pan_angle_sub.subscribe(update_pan_angle)
            
            tilt_angle_sub = roslibpy.Topic(ros, '/tilt/angle', 'std_msgs/Int32')
            tilt_angle_sub.subscribe(update_tilt_angle)

            backoff = 2  # reset backoff on success

            # Keep the connection alive - this will block until connection is lost
            ros.run_forever()

        except Exception as e:
            if connected:  # Log error only if we were connected before
                log_error(f"Error connecting to ROSBridge: {e}")
            connected = False  # Reset connection flag
            telemetry_data['connected'] = False
            time.sleep(min(backoff, 30))  # Wait before retrying
            backoff = min(backoff * 2, 30)  # Exponential backoff


# Telemetry log throttling
_last_batt_ts = 0.0
_last_batt_logged = None
_TELEM_MIN_PERIOD = 600.0  # 600 seconds (10 minutes) between telemetry updates

def update_battery_data(message):
    """Update battery data from ROS message (rate-limited logging)."""
    global _last_batt_ts, _last_batt_logged
    battery_percentage = message['percentage']
    telemetry_data['battery_level'] = max(0.0, min(100.0, battery_percentage))
    telemetry_data['last_update'] = datetime.now().isoformat()
    telemetry_data['connected'] = True

    now = time.time()
    bat = telemetry_data['battery_level']
    should_log = False

    # Log only if enough time has passed (10 minutes)
    if _last_batt_logged is None or (now - _last_batt_ts) >= _TELEM_MIN_PERIOD:
        should_log = True

    if should_log:
        _last_batt_ts = now
        _last_batt_logged = bat
        log_telemetry({'battery_level': bat})



def update_image_data(message):
    """Decode incoming CompressedImage, update UI preview and queue frames for fall model."""
    global latest_image, _decode_count, _last_image_ts
    _last_image_ts = time.time()
    try:
        jpg_bytes = base64.b64decode(message['data'])
        nparr = np.frombuffer(jpg_bytes, dtype=np.uint8)
        bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if bgr is None:
            print("Failed to decode image")
            return

        # For web preview: RGB numpy
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

        with image_lock:
            latest_image = rgb
            telemetry_data['camera_status'] = 'Active'
            telemetry_data['camera_last_update'] = datetime.now().isoformat()

        # For fall model: convert to PIL and push every Nth decoded frame
        _decode_count += 1
        if (_decode_count % DECODE_STRIDE) == 0:
            infer_img = Image.fromarray(rgb)   # PIL.Image
            infer_buf.append(infer_img)

    except Exception as e:
        print(f"Error processing image: {str(e)}")
        telemetry_data['camera_status'] = 'Error'

def update_pan_angle(message):
    """Update pan angle from ROS message"""
    global pan_tilt_angles
    try:
        pan_tilt_angles['pan'] = int(message['data'])
    except Exception as e:
        print(f"Error updating pan angle: {e}")

def update_tilt_angle(message):
    """Update tilt angle from ROS message"""
    global pan_tilt_angles
    try:
        pan_tilt_angles['tilt'] = int(message['data'])
    except Exception as e:
        print(f"Error updating tilt angle: {e}")

# ---------------- HTTP: video & APIs ----------------
def generate_frames():
    """Video streaming route with a small overlay from fall_state."""
    while True:
        with image_lock:
            frame_rgb = None if latest_image is None else latest_image.copy()
            # Combine states depending on mode
            if FALL_MODEL_MODE == 'internal':
                label = fall_state['label']
                conf = fall_state['confidence']
                angle = fall_state['angle']
            elif FALL_MODEL_MODE == 'ros2':
                label = fall_state_ros['label']
                conf = fall_state_ros['confidence']
                angle = fall_state_ros['angle']
            elif FALL_MODEL_MODE == 'humanfall':
                label = fall_state_human['label']
                conf = fall_state_human['confidence']
                angle = fall_state_human['angle']
            else:  # hybrid: prefer positive, take max confidence, avg angle
                labels = [fall_state['label'], fall_state_ros['label'], fall_state_human['label']]
                confs = [float(fall_state['confidence']), float(fall_state_ros['confidence']), float(fall_state_human['confidence'])]
                angles = [float(fall_state['angle']), float(fall_state_ros['angle']), float(fall_state_human['angle'])]
                
                any_fall = any(l == 'FALL' for l in labels)
                label = 'FALL' if any_fall else 'no fall'
                conf = max(confs) if confs else 0.0
                angle = sum(angles) / len(angles) if angles else 0.0
        if frame_rgb is None:
            # blank frame if nothing yet
            frame_bgr = np.zeros((480, 640, 3), dtype=np.uint8)
        else:
            # back to BGR for JPEG encoding
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

        # draw overlay
        text = f"{label}   conf={conf:.2f}  angle={angle:.1f}"
        color = (0, 0, 255) if label == 'FALL' else (0, 255, 0)
        cv2.putText(frame_bgr, text, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,0), 3, cv2.LINE_AA)
        cv2.putText(frame_bgr, text, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2, cv2.LINE_AA)

        ret, buffer = cv2.imencode('.jpg', frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ret:
            jpg = buffer.tobytes()

            # --- alert edge detector (send photo once on transition -> FALL) ---
            now = time.time()
            current = 'FALL' if label == 'FALL' else 'no fall'

            with image_lock:
                last_status = fall_state.get('_last_status', 'no fall')
                last_alert  = float(fall_state.get('_last_alert_ts', 0.0))

            became_fall = (last_status != 'FALL' and current == 'FALL')

            if became_fall and (now - last_alert) >= ALERT_COOLDOWN_SEC:
                msg = f"⚠️ FALL detected!\nconf={conf:.2f}, angle={angle:.1f} @ {datetime.now().strftime('%H:%M:%S')}"
                ok = telegram_send(msg, photo_bytes=jpg)  # send with photo snapshot
                if ok:
                    with image_lock:
                        fall_state['_last_alert_ts'] = now

            with image_lock:
                fall_state['_last_status'] = current

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpg + b'\r\n')

        time.sleep(0.033)  # ~30 FPS stream to browser

@app.route('/')
def index():
    return render_template('home.html')

@app.route('/telegram-bot')
def telegram_bot_page():
    """Telegram bot management page"""
    return render_template('telegram_bot.html', 
                         TELEGRAM_BOT_TOKEN=TELEGRAM_BOT_TOKEN,
                         TELEGRAM_CHAT_ID=TELEGRAM_CHAT_ID)

@app.route('/control')
def control():
    return render_template('control.html')

@app.route('/telemetry')
def telemetry():
    return render_template('telemetry.html')

    
@app.route('/nav')
def nav():
    import os
    return render_template(
        'navigation.html',
        model=os.environ.get('TURTLEBOT3_MODEL', '(unset)'),
        map_yaml=os.environ.get('NAV_MAP_YAML', os.path.expanduser('~/map.yaml')),
    )


@app.route('/stt-tts')
def stt_tts():
    return render_template('stt_tts.html')

@app.route('/fall-detection-test')
def fall_detection_test():
    return render_template('fall_detection_test.html')


@app.route('/api/telemetry')
def get_telemetry():
    return jsonify(telemetry_data)

@app.route('/api/config')
def get_config_api():
    """Get application configuration"""
    try:
        config = get_config()
        return jsonify({
            'success': True,
            'config': config
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/config/robot', methods=['POST'])
def update_robot_config_api():
    """Update robot configuration"""
    try:
        data = request.get_json() or {}
        result = update_robot_config(data)
        return jsonify({
            'success': True,
            'message': 'Robot configuration updated successfully',
            'config': result
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/config/ui', methods=['POST'])
def update_ui_config_api():
    """Update UI configuration"""
    try:
        data = request.get_json() or {}
        result = update_ui_config(data)
        return jsonify({
            'success': True,
            'message': 'UI configuration updated successfully',
            'config': result
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/state')
def get_state_api():
    """Get application state"""
    try:
        state = get_state()
        return jsonify({
            'success': True,
            'state': state
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/fall')
def get_fall():
    with image_lock:
        return jsonify(fall_state)

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

# ---------------- Simple Commander (future) ----------------
@app.route('/api/simple_commander/goal', methods=['POST'])
def simple_commander_set_goal():
    # Placeholder: store params, return not implemented
    try:
        payload = request.get_json() or {}
        return jsonify({'ok': False, 'status': 'not_implemented', 'echo': payload}), 501
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/simple_commander/cancel', methods=['POST'])
def simple_commander_cancel():
    return jsonify({'ok': False, 'status': 'not_implemented'}), 501

@app.route('/api/simple_commander/state', methods=['GET'])
def simple_commander_state():
    # Reserved shape for future integration
    return jsonify({'active_goal': None, 'status': 'idle', 'ok': True})

# ---------------- Pan/Tilt control API ----------------
# Global variables to track pan/tilt angles
pan_tilt_angles = {'pan': 90, 'tilt': 90}

@app.route('/api/pantilt/status', methods=['GET'])
def pantilt_status():
    """Get current pan tilt status and angles"""
    try:
        return jsonify({
            'ok': True,
            'connected': telemetry_data['connected'],
            'pan_angle': pan_tilt_angles['pan'],
            'tilt_angle': pan_tilt_angles['tilt']
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/pantilt/center', methods=['POST', 'GET'])
def pantilt_center():
    """Center both pan and tilt to 90 degrees"""
    try:
        # Publish center commands to the ROS topics
        pan_center_topic = roslibpy.Topic(ros, '/pan/center', 'std_msgs/Empty')
        tilt_center_topic = roslibpy.Topic(ros, '/tilt/center', 'std_msgs/Empty')
        
        pan_center_topic.publish(roslibpy.Message({}))
        tilt_center_topic.publish(roslibpy.Message({}))
        
        # Update local angles
        pan_tilt_angles['pan'] = 90
        pan_tilt_angles['tilt'] = 90
        
        return jsonify({'ok': True, 'pan': 90, 'tilt': 90})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/pantilt/set', methods=['POST', 'GET'])
def pantilt_set():
    """Set absolute pan and tilt angles"""
    try:
        pan = float(request.args.get('pan', request.json.get('pan') if request.is_json else 90))
        tilt = float(request.args.get('tilt', request.json.get('tilt') if request.is_json else 90))
        
        # For absolute positioning, we need to calculate steps from current position
        # This is a simplified approach - in practice, you might want more sophisticated control
        pan_steps = int((pan - pan_tilt_angles['pan']) / 20)  # 20 degrees per step
        tilt_steps = int((tilt - pan_tilt_angles['tilt']) / 20)
        
        if pan_steps != 0:
            pan_topic = roslibpy.Topic(ros, '/pan/step', 'std_msgs/Int32')
            pan_topic.publish(roslibpy.Message({'data': pan_steps}))
            pan_tilt_angles['pan'] = pan
        
        if tilt_steps != 0:
            tilt_topic = roslibpy.Topic(ros, '/tilt/step', 'std_msgs/Int32')
            tilt_topic.publish(roslibpy.Message({'data': tilt_steps}))
            pan_tilt_angles['tilt'] = tilt
        
        return jsonify({'ok': True, 'pan': pan, 'tilt': tilt})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/pantilt/pan/step', methods=['POST'])
def pantilt_pan_step():
    """Send pan step command"""
    try:
        steps = int(request.json.get('steps', 0) if request.is_json else 0)
        
        pan_topic = roslibpy.Topic(ros, '/pan/step', 'std_msgs/Int32')
        pan_topic.publish(roslibpy.Message({'data': steps}))
        
        # Update local angle (20 degrees per step)
        pan_tilt_angles['pan'] = max(0, min(180, pan_tilt_angles['pan'] + (steps * 20)))
        
        return jsonify({'ok': True, 'steps': steps, 'pan_angle': pan_tilt_angles['pan']})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/pantilt/tilt/step', methods=['POST'])
def pantilt_tilt_step():
    """Send tilt step command"""
    try:
        steps = int(request.json.get('steps', 0) if request.is_json else 0)
        
        tilt_topic = roslibpy.Topic(ros, '/tilt/step', 'std_msgs/Int32')
        tilt_topic.publish(roslibpy.Message({'data': steps}))
        
        # Update local angle (20 degrees per step)
        pan_tilt_angles['tilt'] = max(0, min(180, pan_tilt_angles['tilt'] + (steps * 20)))
        
        return jsonify({'ok': True, 'steps': steps, 'tilt_angle': pan_tilt_angles['tilt']})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ---------------- robot commands (unchanged) ----------------
def send_velocity_command(linear_x=0.0, angular_z=0.0, speed_factor=1.0):
    if not telemetry_data['connected']:
        print("Not connected to robot")
        return False
    try:
        base_linear_speed = 0.2
        base_angular_speed = 0.5
        final_linear_x = linear_x * base_linear_speed * speed_factor
        final_angular_z = angular_z * base_angular_speed * speed_factor
        twist = roslibpy.Message({
            'linear': {'x': final_linear_x, 'y': 0.0, 'z': 0.0},
            'angular': {'x': 0.0, 'y': 0.0, 'z': final_angular_z}
        })
        cmd_vel_pub.publish(twist)
        return True
    except Exception as e:
        print(f"Error sending command: {str(e)}")
        return False

@app.route('/api/command/<direction>')
def send_command(direction):
    speed_factor = 0.1  # Default or tune per your UI
    commands = {
        'forward': (1.0, 0.0),
        'backward': (-1.0, 0.0),
        'left': (0.0, 1.0),
        'right': (0.0, -1.0),
        'stop': (0.0, 0.0)
    }
    if direction in commands:
        linear_x, angular_z = commands[direction]
        ok = send_velocity_command(linear_x, angular_z, speed_factor)
        return jsonify({'status': 'success' if ok else 'error'})
    return jsonify({'status': 'invalid_command'})

@app.route('/api/command/<direction>/<float:speed>')
def send_command_with_speed(direction, speed):
    speed_factor = max(0.1, min(1.0, speed))
    commands = {
        'forward': (1.0, 0.0),
        'backward': (-1.0, 0.0),
        'left': (0.0, 1.0),
        'right': (0.0, -1.0),
        'stop': (0.0, 0.0)
    }
    if direction in commands:
        linear_x, angular_z = commands[direction]
        ok = send_velocity_command(linear_x, angular_z, speed_factor)
        return jsonify({'status': 'success' if ok else 'error'})
    return jsonify({'status': 'invalid_command'})

# ---------------- telegram utility ----------------
def telegram_send(text: str, photo_bytes: bytes | None = None):
    """Send a text (and optional JPEG bytes) to your Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        # silently skip if not configured
        return False
    try:
        if photo_bytes:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            files = {'photo': ('frame.jpg', photo_bytes, 'image/jpeg')}
            data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': text}
            r = requests.post(url, data=data, files=files, timeout=10)
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {'chat_id': TELEGRAM_CHAT_ID, 'text': text}
            r = requests.post(url, data=data, timeout=10)
        return r.ok
    except Exception as e:
        print(f"[alert] Telegram error: {e}")
        return False

def ask_are_you_ok():
    # TODO: play TTS "Are you okay? I detected a fall. Say 'I'm OK' to cancel."
    # Start a timer; if no 'OK' intent within REQUIRE_CONFIRM_SEC → call telegram_send(...)
    pass

# ---------------- Telegram Bot Functions ----------------
def telegram_bot_send_message(text: str, chat_id: str = None, photo_bytes: bytes = None) -> bool:
    """Send a message (and optional photo) to Telegram chat"""
    if not TELEGRAM_BOT_TOKEN:
        return False
    
    target_chat_id = chat_id or TELEGRAM_CHAT_ID
    if not target_chat_id:
        return False
    
    try:
        if photo_bytes:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            files = {'photo': ('photo.jpg', photo_bytes, 'image/jpeg')}
            data = {'chat_id': target_chat_id, 'caption': text}
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {'chat_id': target_chat_id, 'text': text}
        
        response = requests.post(url, data=data, files=files if photo_bytes else None, timeout=10)
        return response.ok
        
    except Exception as e:
        log_error(f"Telegram bot send error: {e}")
        return False

def get_robot_status_for_telegram() -> str:
    """Get formatted robot status for Telegram"""
    try:
        battery = telemetry_data.get('battery_level', 0.0)
        connected = telemetry_data.get('connected', False)
        camera_status = telemetry_data.get('camera_status', 'Unknown')
        last_update = telemetry_data.get('last_update', 'Never')
        
        status_text = f"""🤖 **Robot Status Report**
        
🔋 **Battery**: {battery:.1f}%
🔗 **Connection**: {'✅ Connected' if connected else '❌ Disconnected'}
📷 **Camera**: {camera_status}
⏰ **Last Update**: {last_update}
🕐 **Report Time**: {datetime.now().strftime('%H:%M:%S')}

📊 **System Status**: {'🟢 Online' if connected else '🔴 Offline'}"""
        
        return status_text
        
    except Exception as e:
        return f"❌ **Error retrieving status**: {str(e)}"

def handle_telegram_command(command: str, chat_id: str, user_id: str = None) -> str:
    """Handle incoming Telegram commands"""
    command = command.lower().strip()
    
    # Check if user is authorized (if TELEGRAM_ALLOWED_USERS is configured)
    if TELEGRAM_ALLOWED_USERS and user_id and str(user_id) not in TELEGRAM_ALLOWED_USERS:
        return "❌ You are not authorized to use this bot."
    
    if command == 'start':
        return """🤖 **Welcome to TurtleBot3 Telegram Bot!**

I'm your robot's remote interface. Here's what I can do:

📋 **Available Commands:**
/help - Show this help message
/status - Get robot status
/photo - Take a photo
/chat - Start interactive chat with AI
/test - Test bot connectivity

🚀 **Ready to help!** Send me a command to get started."""

    elif command == 'help':
        return """📋 **Available Commands:**

/start - Welcome message
/help - Show this help
/status - Get robot status (battery, connection, camera)
/photo - Capture and send current photo
/chat - Start interactive chat with AI
/test - Test bot connectivity

💡 **Tip**: Commands are case-insensitive!
💬 **Chat**: Send any text message to chat with the AI assistant."""

    elif command == 'status':
        return get_robot_status_for_telegram()
    
    elif command == 'photo':
        try:
            photo_bytes = get_latest_jpeg()
            if photo_bytes:
                caption = f"📸 **Robot Camera Snapshot**\n🕐 {datetime.now().strftime('%H:%M:%S')}"
                telegram_bot_send_message(caption, chat_id, photo_bytes)
                return "📸 Photo sent!"
            else:
                return "❌ No camera image available. Camera may be offline or not initialized."
        except Exception as e:
            return f"❌ Error capturing photo: {str(e)}"
    
    elif command == 'test':
        return f"""✅ **Bot Test Successful!**

🤖 Bot is working correctly
🕐 Test time: {datetime.now().strftime('%H:%M:%S')}
📡 Connection: Active
🎯 Ready for commands!"""
    
    elif command == 'chat':
        return """💬 **Interactive Chat Mode**

You can now send me any text message and I'll respond using AI!

Just type your message (no need for commands) and I'll chat with you using Gemini AI.

Type /help to see other commands."""
    
    else:
        return f"❓ Unknown command: {command}\n\nType /help to see available commands."

def handle_telegram_chat(message_text: str, chat_id: str, user_id: str = None) -> str:
    """Handle interactive chat with Gemini AI"""
    # Check if user is authorized
    if TELEGRAM_ALLOWED_USERS and user_id and str(user_id) not in TELEGRAM_ALLOWED_USERS:
        return "❌ You are not authorized to use this bot."
    
    try:
        # Import the STT/TTS core for Gemini integration
        import test_speech as stt_tts_core
        
        # Add robot context to the message
        robot_context = f"""You are an AI assistant for a TurtleBot3 robot. The user is chatting with you via Telegram. 
        
Current robot status:
- Battery: {telemetry_data.get('battery_level', 0.0):.1f}%
- Connected: {telemetry_data.get('connected', False)}
- Camera: {telemetry_data.get('camera_status', 'Unknown')}

User message: {message_text}

Please respond in a helpful, friendly way. You can mention the robot's capabilities like taking photos, checking status, or navigation if relevant to the conversation."""
        
        # Get AI response using Gemini
        ai_response = stt_tts_core.gemini_chat(robot_context)
        
        # Add a small indicator that this is from the robot
        return f"🤖 {ai_response}"
        
    except ImportError:
        return "❌ AI chat feature is not available. Please check the STT/TTS system configuration."
    except Exception as e:
        log_error(f"Error in Telegram chat: {e}")
        return f"❌ Sorry, I encountered an error: {str(e)}"

def telegram_polling_worker():
    """Background worker to poll Telegram for new messages"""
    global telegram_last_update_id, telegram_polling_enabled
    
    if not TELEGRAM_BOT_TOKEN:
        log_app("Telegram bot not configured, skipping polling")
        return
    
    log_app("Starting Telegram bot polling worker")
    
    while telegram_polling_enabled:
        try:
            # Get updates from Telegram
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            params = {
                'offset': telegram_last_update_id + 1,
                'timeout': 30,
                'limit': 10
            }
            
            response = requests.get(url, params=params, timeout=35)
            
            if response.ok:
                data = response.json()
                if data.get('ok'):
                    updates = data.get('result', [])
                    
                    for update in updates:
                        telegram_last_update_id = update['update_id']
                        
                        if 'message' in update:
                            message = update['message']
                            chat_id = str(message.get('chat', {}).get('id', ''))
                            user_id = str(message.get('from', {}).get('id', ''))
                            text = message.get('text', '').strip()
                            
                            if not text:
                                continue
                            
                            log_app(f"Telegram message from {user_id}: {text}")
                            
                            # Handle commands (messages starting with /)
                            if text.startswith('/'):
                                command = text.split()[0][1:]  # Remove '/' and get command
                                response_text = handle_telegram_command(command, chat_id, user_id)
                            else:
                                # Handle regular text messages as chat
                                response_text = handle_telegram_chat(text, chat_id, user_id)
                            
                            # Send response back to Telegram
                            if response_text:
                                telegram_bot_send_message(response_text, chat_id)
                else:
                    log_error(f"Telegram API error: {data.get('description', 'Unknown error')}")
            else:
                log_error(f"Telegram polling HTTP error: {response.status_code}")
                
        except Exception as e:
            log_error(f"Telegram polling error: {e}")
            time.sleep(5)  # Wait before retrying on error
        
        time.sleep(1)  # Check for messages every second


def get_latest_jpeg() -> bytes | None:
    with image_lock:
        if latest_image is None:
            return None
        bgr = cv2.cvtColor(latest_image, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else None

def extract_video_frames(video_path):
    """Extract frames from video for fall detection processing"""
    try:
        import cv2
        frames = []
        cap = cv2.VideoCapture(video_path)
        
        frame_count = 0
        while cap.isOpened() and frame_count < 200:  # Limit to 200 frames for faster processing
            ret, frame = cap.read()
            if not ret:
                break
            
            # Convert BGR to RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Resize frame to standard size
            rgb_frame = cv2.resize(rgb_frame, (640, 480))
            
            # Convert to base64 for transmission
            _, buffer = cv2.imencode('.jpg', cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR))
            frame_b64 = base64.b64encode(buffer).decode('utf-8')
            
            frames.append({
                'frame_number': frame_count,
                'timestamp': frame_count / 30.0,  # Assuming 30 FPS
                'image_data': frame_b64
            })
            
            frame_count += 1
        
        cap.release()
        
        log_fall_detection(f"Extracted {len(frames)} frames from video", 0.0, 0.0)
        return frames
        
    except Exception as e:
        log_error(f"Error extracting video frames: {e}")
        return []

@app.route('/api/alert/test', methods=['POST', 'GET'])
def alert_test():
    """Sends a test Telegram message (with current frame if available)."""
    photo = get_latest_jpeg()
    ok = telegram_send("🔔 Test alert from Turtlebot UI", photo_bytes=photo)
    return jsonify({"ok": bool(ok), "with_photo": photo is not None})

@app.route('/api/fall/force', methods=['POST', 'GET'])
def fall_force_once():
    """Force a FALL transition so the next frame triggers a Telegram."""
    now = time.time()
    with image_lock:
        # Make sure it looks like a transition from non-FALL -> FALL
        fall_state['_last_status'] = 'no fall'
        fall_state['label'] = 'FALL'
        fall_state['confidence'] = 0.99
        fall_state['angle'] = 75.0
        # Allow immediate alert by rewinding last alert time
        fall_state['_last_alert_ts'] = now - (ALERT_COOLDOWN_SEC + 1)

    return jsonify({"forced": True, "note": "Next frame should trigger alert if streaming is active."})

# ---------------- Fall Detection Test API ----------------
@app.route('/api/fall-detection/status', methods=['GET'])
def fall_detection_status():
    """Get fall detection model status"""
    try:
        # Check if the fall detection model is available and loaded
        model_available = False
        try:
            # Try to access the fall prediction module
            if 'Fall_prediction' in globals():
                model_available = True
        except:
            pass
        
        # Check HumanFallDetection availability
        human_fall_available = HUMAN_FALL_DETECTION_AVAILABLE
        
        return jsonify({
            'success': True,
            'model_loaded': model_available,
            'model_type': 'Human Fall Detection',
            'inference_fps': INFER_FPS,
            'confidence_threshold': CONF_THRESH,
            'mode': FALL_MODEL_MODE,
            'human_fall_detection_available': human_fall_available,
            'human_fall_disable_cuda': HUMAN_FALL_DISABLE_CUDA,
            'human_fall_conf_thresh': HUMAN_FALL_CONF_THRESH
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/fall-detection/upload-model', methods=['POST'])
def upload_fall_model():
    """Upload and load a fall detection model"""
    try:
        if 'files' not in request.files:
            return jsonify({'success': False, 'error': 'No files provided'}), 400
        
        files = request.files.getlist('files')
        if not files:
            return jsonify({'success': False, 'error': 'No files uploaded'}), 400
        
        # Create models directory if it doesn't exist
        models_dir = os.path.join(os.getcwd(), 'ai_models')
        os.makedirs(models_dir, exist_ok=True)
        
        uploaded_files = []
        for file in files:
            if file.filename:
                # Save uploaded file
                filename = secure_filename(file.filename)
                file_path = os.path.join(models_dir, filename)
                file.save(file_path)
                uploaded_files.append(filename)
        
        # Note: In a real implementation, you would load the model here
        # For now, we'll just confirm the files were saved
        
        return jsonify({
            'success': True,
            'message': f'Model files uploaded successfully: {", ".join(uploaded_files)}',
            'files': uploaded_files
        })
        
    except Exception as e:
        log_error(f"Error uploading fall detection model: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/fall-detection/process-video', methods=['POST'])
def process_fall_video():
    """Process uploaded video for fall detection"""
    try:
        if 'video' not in request.files:
            return jsonify({'success': False, 'error': 'No video file provided'}), 400
        
        video_file = request.files['video']
        if not video_file or not video_file.filename:
            return jsonify({'success': False, 'error': 'No video file uploaded'}), 400
        
        # Create videos directory if it doesn't exist
        videos_dir = os.path.join(os.getcwd(), 'uploaded_videos')
        os.makedirs(videos_dir, exist_ok=True)
        
        # Save uploaded video
        filename = secure_filename(video_file.filename)
        file_path = os.path.join(videos_dir, filename)
        video_file.save(file_path)
        
        # Extract frames from video for processing
        frames_data = extract_video_frames(file_path)
        
        # Store all frames in a global variable for analysis
        global video_frames_cache
        video_frames_cache = {
            'filename': filename,
            'file_path': file_path,
            'frames': frames_data,
            'frames_count': len(frames_data),
            'processed_at': time.time()
        }
        
        return jsonify({
            'success': True,
            'message': f'Video processed successfully: {filename}',
            'video_data': {
                'filename': filename,
                'file_path': file_path,
                'processed': True,
                'frames_count': len(frames_data),
                'frames': frames_data[:10]  # Send first 10 frames for preview
            }
        })
        
    except Exception as e:
        log_error(f"Error processing fall detection video: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/fall-detection/send-telegram', methods=['POST'])
def send_fall_telegram_alert():
    """Send fall detection alert to Telegram"""
    try:
        data = request.get_json() or {}
        results = data.get('results', {})
        message = data.get('message', 'Fall detected!')
        
        # Get current frame for photo if available
        photo = get_latest_jpeg()
        
        # Send to Telegram
        ok = telegram_send(message, photo_bytes=photo)
        
        if ok:
            return jsonify({
                'success': True,
                'message': 'Fall alert sent to Telegram successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to send Telegram alert. Check bot configuration.'
            }), 500
            
    except Exception as e:
        log_error(f"Error sending Telegram alert: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/fall-detection/json-files', methods=['GET'])
def list_json_files():
    """List all JSON result files"""
    try:
        json_dir = os.path.join(os.getcwd(), 'video_results')
        if not os.path.exists(json_dir):
            return jsonify({'success': True, 'files': []})
        
        files = []
        for filename in os.listdir(json_dir):
            if filename.endswith('.json'):
                file_path = os.path.join(json_dir, filename)
                stat = os.stat(file_path)
                files.append({
                    'filename': filename,
                    'size': stat.st_size,
                    'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        
        # Sort by creation time (newest first)
        files.sort(key=lambda x: x['created'], reverse=True)
        
        return jsonify({
            'success': True,
            'files': files
        })
        
    except Exception as e:
        log_error(f"Error listing JSON files: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/fall-detection/json-files/<filename>', methods=['GET'])
def get_json_file(filename):
    """Get content of a specific JSON file"""
    try:
        json_dir = os.path.join(os.getcwd(), 'video_results')
        file_path = os.path.join(json_dir, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'error': 'File not found'}), 404
        
        with open(file_path, 'r') as f:
            content = json.load(f)
        
        return jsonify({
            'success': True,
            'content': content
        })
        
    except Exception as e:
        log_error(f"Error reading JSON file: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/fall-detection/manual-telegram', methods=['POST'])
def manual_telegram_alert():
    """Manually trigger Telegram alert for demonstration purposes"""
    try:
        # Get current frame for photo
        photo = get_latest_jpeg()
        
        # Send test message
        message = "🔔 Manual Telegram Alert Test\nThis is a demonstration message from the TurtleBot Web UI."
        ok = telegram_send(message, photo_bytes=photo)
        
        if ok:
            return jsonify({
                'success': True,
                'message': 'Manual Telegram alert sent successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to send Telegram alert. Check bot configuration.'
            }), 500
            
    except Exception as e:
        log_error(f"Error sending manual Telegram alert: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ---------------- Telegram Bot Webhook ----------------
@app.route('/api/telegram/webhook', methods=['POST'])
def telegram_webhook():
    """Handle incoming Telegram messages via webhook"""
    try:
        if not TELEGRAM_BOT_TOKEN:
            return jsonify({'error': 'Telegram bot not configured'}), 400
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data received'}), 400
        
        # Extract message information
        message = data.get('message', {})
        if not message:
            return jsonify({'status': 'ok'})  # Not a message update
        
        chat_id = str(message.get('chat', {}).get('id', ''))
        user_id = str(message.get('from', {}).get('id', ''))
        text = message.get('text', '').strip()
        
        if not text:
            return jsonify({'status': 'ok'})  # No text message
        
        log_app(f"Telegram message from {user_id}: {text}")
        
        # Handle commands (messages starting with /)
        if text.startswith('/'):
            command = text.split()[0][1:]  # Remove '/' and get command
            response = handle_telegram_command(command, chat_id, user_id)
        else:
            # Handle regular text messages as chat
            response = handle_telegram_chat(text, chat_id, user_id)
        
        # Send response back to Telegram
        if response:
            telegram_bot_send_message(response, chat_id)
        
        return jsonify({'status': 'ok'})
        
    except Exception as e:
        log_error(f"Telegram webhook error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/telegram/set-webhook', methods=['POST'])
def set_telegram_webhook():
    """Set up Telegram webhook URL"""
    try:
        if not TELEGRAM_BOT_TOKEN:
            return jsonify({'error': 'Telegram bot not configured'}), 400
        
        webhook_url = request.json.get('webhook_url', '')
        
        # Set webhook with Telegram
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
        data = {'url': webhook_url} if webhook_url else {'url': ''}
        
        response = requests.post(url, data=data, timeout=10)
        
        if response.ok:
            result = response.json()
            if result.get('ok'):
                return jsonify({
                    'success': True,
                    'message': 'Webhook set successfully',
                    'webhook_url': webhook_url
                })
            else:
                return jsonify({
                    'success': False,
                    'error': result.get('description', 'Unknown error')
                }), 400
        else:
            return jsonify({
                'success': False,
                'error': f'HTTP {response.status_code}'
            }), 400
            
    except Exception as e:
        log_error(f"Error setting Telegram webhook: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/telegram/test-bot', methods=['POST'])
def test_telegram_bot():
    """Test Telegram bot functionality"""
    try:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return jsonify({
                'success': False,
                'error': 'Telegram bot not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.'
            }), 400
        
        # Test bot connection
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"
        response = requests.get(url, timeout=10)
        
        if not response.ok:
            return jsonify({
                'success': False,
                'error': f'Bot connection failed: HTTP {response.status_code}'
            }), 400
        
        bot_info = response.json()
        if not bot_info.get('ok'):
            return jsonify({
                'success': False,
                'error': bot_info.get('description', 'Unknown error')
            }), 400
        
        # Send test message
        test_message = f"""🤖 **TurtleBot3 Telegram Bot Test**

✅ Bot is working correctly!
🕐 Test time: {datetime.now().strftime('%H:%M:%S')}
📡 Connection: Active
🎯 Ready for commands!

Try these commands:
/start - Welcome message
/help - Show available commands
/status - Get robot status
/photo - Take a photo
/chat - Start AI chat"""
        
        success = telegram_bot_send_message(test_message)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Test message sent successfully',
                'bot_info': bot_info.get('result', {})
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to send test message'
            }), 500
            
    except Exception as e:
        log_error(f"Error testing Telegram bot: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/telegram/send-status', methods=['POST'])
def send_telegram_status():
    """Send robot status to Telegram"""
    try:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return jsonify({
                'success': False,
                'error': 'Telegram bot not configured'
            }), 400
        
        status_message = get_robot_status_for_telegram()
        success = telegram_bot_send_message(status_message)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Status sent to Telegram successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to send status to Telegram'
            }), 500
            
    except Exception as e:
        log_error(f"Error sending Telegram status: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/telegram/send-photo', methods=['POST'])
def send_telegram_photo():
    """Send robot photo to Telegram"""
    try:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return jsonify({
                'success': False,
                'error': 'Telegram bot not configured'
            }), 400
        
        photo_bytes = get_latest_jpeg()
        if photo_bytes:
            caption = f"📸 **Robot Camera Snapshot**\n🕐 {datetime.now().strftime('%H:%M:%S')}"
            success = telegram_bot_send_message(caption, TELEGRAM_CHAT_ID, photo_bytes)
            
            if success:
                return jsonify({
                    'success': True,
                    'message': 'Photo sent to Telegram successfully'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Failed to send photo to Telegram'
                }), 500
        else:
            return jsonify({
                'success': False,
                'error': 'No camera image available'
            }), 400
            
    except Exception as e:
        log_error(f"Error sending Telegram photo: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/fall-detection/test', methods=['POST'])
def test_fall_detection():
    """Test the fall detection model with live camera feed"""
    try:
        # Handle both JSON and FormData requests
        if request.is_json:
            data = request.get_json() or {}
            test_type = data.get('test_type', 'live_camera')
            model_type = data.get('model_type', 'internal')
        else:
            # Handle FormData (for video uploads)
            test_type = request.form.get('test_type', 'live_camera')
            model_type = request.form.get('model_type', 'internal')
        
        if test_type == 'live_camera':
            # Capture current frames for testing
            with image_lock:
                if len(infer_buf) < 3:
                    return jsonify({
                        'success': False, 
                        'error': 'Not enough frames available for testing. Please wait for camera feed.'
                    }), 400
                
                # Get the latest 3 frames
                test_frames = list(infer_buf)[-3:]
            
            results = {}
            
            # Test internal model (fall-detection-main)
            if model_type in ('internal', 'both'):
                start_time = time.time()
                try:
                    img1, img2, img3 = test_frames[0], test_frames[1], test_frames[2]
                    result = Fall_prediction(img1, img2, img3)
                    is_fall, label, conf, angle = _classify(result, CONF_THRESH)
                    processing_time = (time.time() - start_time) * 1000
                    
                    results['internal'] = {
                        'is_fall': is_fall,
                        'confidence': conf,
                        'angle': angle,
                        'processing_time': processing_time,
                        'label': label
                    }
                except Exception as e:
                    results['internal'] = {'error': str(e)}
            
            # Test HumanFallDetection model
            if model_type in ('humanfall', 'both') and HUMAN_FALL_DETECTION_AVAILABLE:
                start_time = time.time()
                try:
                    human_detector = get_human_fall_detector(disable_cuda=HUMAN_FALL_DISABLE_CUDA)
                    latest_frame = test_frames[-1]
                    frame_np = np.array(latest_frame)
                    frame_bgr = cv2.cvtColor(frame_np, cv2.COLOR_RGB2BGR)
                    
                    result = human_detector.process_frame(frame_bgr)
                    processing_time = (time.time() - start_time) * 1000
                    
                    results['humanfall'] = {
                        'is_fall': result['is_fall'],
                        'confidence': result['confidence'],
                        'angle': result['angle'],
                        'processing_time': processing_time,
                        'consecutive_frames': result.get('consecutive_frames', 0),
                        'keypoints_detected': result.get('keypoints_detected', 0)
                    }
                except Exception as e:
                    results['humanfall'] = {'error': str(e)}
            
            # Get current frame for display
            test_image_b64 = None
            with image_lock:
                if latest_image is not None:
                    bgr_image = cv2.cvtColor(latest_image, cv2.COLOR_RGB2BGR)
                    _, buffer = cv2.imencode('.jpg', bgr_image)
                    test_image_b64 = base64.b64encode(buffer).decode('utf-8')
            
            return jsonify({
                'success': True,
                'results': results,
                'timestamp': time.time(),
                'test_image': test_image_b64,
                'frames_processed': len(test_frames),
                'model_type': model_type
            })
            
        elif test_type == 'video':
            # Process uploaded video for testing
            log_app(f"Processing video test with model_type: {model_type}")
            if 'video' not in request.files:
                log_app("No video file found in request.files")
                return jsonify({'success': False, 'error': 'No video file provided'}), 400
            
            video_file = request.files['video']
            if not video_file or not video_file.filename:
                return jsonify({'success': False, 'error': 'No video file uploaded'}), 400
            
            # Create videos directory if it doesn't exist
            videos_dir = os.path.join(os.getcwd(), 'uploaded_videos')
            os.makedirs(videos_dir, exist_ok=True)
            
            # Save uploaded video
            filename = secure_filename(video_file.filename)
            file_path = os.path.join(videos_dir, filename)
            video_file.save(file_path)
            
            # Extract frames from video for processing
            frames_data = extract_video_frames(file_path)
            
            if not frames_data:
                return jsonify({'success': False, 'error': 'Failed to extract frames from video'}), 400
            
            # Process frames with selected model(s)
            results = {}
            processed_frames = 0
            
            # Test internal model (fall-detection-main)
            if model_type in ('internal', 'both'):
                internal_results = []
                try:
                    # Optimized frame processing based on test results
                    window_size = 3
                    step_size = 1  # Process every frame for best accuracy (tested optimal)
                    max_frames = min(len(frames_data) - window_size + 1, 30)  # Limit to 30 frame groups for speed
                    
                    for i in range(0, max_frames, step_size):
                        if i + 2 >= len(frames_data):
                            break
                        
                        # Convert base64 frames to PIL Images
                        frame1_b64 = frames_data[i]['image_data']
                        frame2_b64 = frames_data[i + 1]['image_data']
                        frame3_b64 = frames_data[i + 2]['image_data']
                        
                        # Decode base64 to PIL Images
                        frame1_bytes = base64.b64decode(frame1_b64)
                        frame2_bytes = base64.b64decode(frame2_b64)
                        frame3_bytes = base64.b64decode(frame3_b64)
                        
                        frame1_np = np.frombuffer(frame1_bytes, dtype=np.uint8)
                        frame2_np = np.frombuffer(frame2_bytes, dtype=np.uint8)
                        frame3_np = np.frombuffer(frame3_bytes, dtype=np.uint8)
                        
                        frame1_bgr = cv2.imdecode(frame1_np, cv2.IMREAD_COLOR)
                        frame2_bgr = cv2.imdecode(frame2_np, cv2.IMREAD_COLOR)
                        frame3_bgr = cv2.imdecode(frame3_np, cv2.IMREAD_COLOR)
                        
                        frame1_rgb = cv2.cvtColor(frame1_bgr, cv2.COLOR_BGR2RGB)
                        frame2_rgb = cv2.cvtColor(frame2_bgr, cv2.COLOR_BGR2RGB)
                        frame3_rgb = cv2.cvtColor(frame3_bgr, cv2.COLOR_BGR2RGB)
                        
                        frame1_pil = Image.fromarray(frame1_rgb)
                        frame2_pil = Image.fromarray(frame2_rgb)
                        frame3_pil = Image.fromarray(frame3_rgb)
                        
                        # Process with fall-detection-main
                        start_time = time.time()
                        result = Fall_prediction(frame1_pil, frame2_pil, frame3_pil)
                        is_fall, label, conf, angle = _classify(result, CONF_THRESH)
                        processing_time = (time.time() - start_time) * 1000
                        
                        # Debug logging for first few frames (reduced)
                        if i < 3:
                            log_fall_detection(f"Video frame {i}: {label} (conf={conf:.3f})", conf, angle)
                        
                        internal_results.append({
                            'frame_number': i,
                            'is_fall': is_fall,
                            'confidence': conf,
                            'angle': angle,
                            'processing_time': processing_time,
                            'label': label
                        })
                        processed_frames += 1
                        
                except Exception as e:
                    results['internal'] = {'error': str(e)}
                else:
                    # Analyze results for overall fall detection
                    fall_detections = [r for r in internal_results if r['is_fall']]
                    overall_fall = len(fall_detections) > 0
                    best_result = max(internal_results, key=lambda x: x['confidence']) if internal_results else None
                    
                    results['internal'] = {
                        'results': internal_results,
                        'total_frames_processed': processed_frames,
                        'overall_fall_detected': overall_fall,
                        'fall_detection_count': len(fall_detections),
                        'best_confidence': best_result['confidence'] if best_result else 0.0,
                        'best_angle': best_result['angle'] if best_result else 0.0,
                        'average_confidence': sum(r['confidence'] for r in internal_results) / len(internal_results) if internal_results else 0.0
                    }
            
            # Test HumanFallDetection model
            if model_type in ('humanfall', 'both') and HUMAN_FALL_DETECTION_AVAILABLE:
                humanfall_results = []
                try:
                    human_detector = get_human_fall_detector(disable_cuda=HUMAN_FALL_DISABLE_CUDA)
                    
                    for i, frame_data in enumerate(frames_data[::3]):  # Process every 3rd frame
                        frame_b64 = frame_data['image_data']
                        frame_bytes = base64.b64decode(frame_b64)
                        frame_np = np.frombuffer(frame_bytes, dtype=np.uint8)
                        frame_bgr = cv2.imdecode(frame_np, cv2.IMREAD_COLOR)
                        
                        # Process with HumanFallDetection
                        start_time = time.time()
                        result = human_detector.process_frame(frame_bgr)
                        processing_time = (time.time() - start_time) * 1000
                        
                        humanfall_results.append({
                            'frame_number': i * 3,
                            'is_fall': result['is_fall'],
                            'confidence': result['confidence'],
                            'angle': result['angle'],
                            'processing_time': processing_time,
                            'consecutive_frames': result.get('consecutive_frames', 0),
                            'keypoints_detected': result.get('keypoints_detected', 0)
                        })
                        processed_frames += 1
                        
                except Exception as e:
                    results['humanfall'] = {'error': str(e)}
                else:
                    results['humanfall'] = {
                        'results': humanfall_results,
                        'total_frames_processed': processed_frames
                    }
            
            return jsonify({
                'success': True,
                'results': results,
                'timestamp': time.time(),
                'video_filename': filename,
                'total_frames_extracted': len(frames_data),
                'model_type': model_type
            })
            
        else:
            return jsonify({'success': False, 'error': f'Unsupported test type: {test_type}'}), 400
            
    except Exception as e:
        log_error(f"Error testing fall detection: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500





# ---------------- Meditation Schedule System ----------------
# Import meditation schedule manager
MEDITATION_AVAILABLE = False
meditation_manager = None

try:
    from meditation_schedule_simple import simple_meditation_manager as meditation_manager
    MEDITATION_AVAILABLE = True
    log_app("Simple meditation schedule system loaded")
    
    # Initialize meditation manager with telegram function
    try:
        meditation_manager.set_telegram_function(telegram_send)
        log_app("Simple meditation manager initialized with Telegram function")
    except Exception as e:
        log_app(f"Error initializing simple meditation manager: {e}", level=logging.WARNING)
        
except ImportError as e:
    MEDITATION_AVAILABLE = False
    log_app(f"Simple meditation schedule system not available: {e}", level=logging.WARNING)
except Exception as e:
    MEDITATION_AVAILABLE = False
    log_app(f"Error loading simple meditation schedule system: {e}", level=logging.ERROR)

@app.route('/meditation')
def meditation_page():
    """Meditation schedule management page"""
    return render_template('meditation.html')

@app.route('/api/meditation/schedules', methods=['GET'])
def get_meditation_schedules():
    """Get all meditation schedules"""
    try:
        if not MEDITATION_AVAILABLE:
            return jsonify({'success': False, 'error': 'Meditation system not available'}), 500
        
        schedules = meditation_manager.get_all_schedules()
        return jsonify({
            'success': True,
            'schedules': [schedule.to_dict() for schedule in schedules]
        })
    except Exception as e:
        log_error(f"Error getting meditation schedules: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/meditation/schedules', methods=['POST'])
def create_meditation_schedule():
    """Create a new meditation schedule"""
    try:
        if not MEDITATION_AVAILABLE:
            return jsonify({'success': False, 'error': 'Meditation system not available'}), 500
        
        data = request.get_json() or {}
        title = data.get('title', '').strip()
        time = data.get('time', '').strip()
        duration = int(data.get('duration', 15))
        repeat_days = data.get('repeat_days', [])
        
        if not title or not time:
            return jsonify({'success': False, 'error': 'Title and time are required'}), 400
        
        # Validate time format
        try:
            datetime.strptime(time, '%H:%M')
        except ValueError:
            return jsonify({'success': False, 'error': 'Invalid time format. Use HH:MM'}), 400
        
        # Validate duration
        if duration < 1 or duration > 120:
            return jsonify({'success': False, 'error': 'Duration must be between 1 and 120 minutes'}), 400
        
        schedule_id = meditation_manager.add_schedule(title, time, duration, repeat_days)
        
        return jsonify({
            'success': True,
            'message': 'Meditation schedule created successfully',
            'schedule_id': schedule_id
        })
        
    except Exception as e:
        log_error(f"Error creating meditation schedule: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/meditation/schedules/<schedule_id>', methods=['PUT'])
def update_meditation_schedule(schedule_id):
    """Update an existing meditation schedule"""
    try:
        if not MEDITATION_AVAILABLE:
            return jsonify({'success': False, 'error': 'Meditation system not available'}), 500
        
        data = request.get_json() or {}
        
        # Validate time format if provided
        if 'time' in data:
            try:
                datetime.strptime(data['time'], '%H:%M')
            except ValueError:
                return jsonify({'success': False, 'error': 'Invalid time format. Use HH:MM'}), 400
        
        # Validate duration if provided
        if 'duration' in data:
            duration = int(data['duration'])
            if duration < 1 or duration > 120:
                return jsonify({'success': False, 'error': 'Duration must be between 1 and 120 minutes'}), 400
        
        success = meditation_manager.update_schedule(schedule_id, **data)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Meditation schedule updated successfully'
            })
        else:
            return jsonify({'success': False, 'error': 'Schedule not found'}), 404
            
    except Exception as e:
        log_error(f"Error updating meditation schedule: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/meditation/schedules/<schedule_id>', methods=['DELETE'])
def delete_meditation_schedule(schedule_id):
    """Delete a meditation schedule"""
    try:
        if not MEDITATION_AVAILABLE:
            return jsonify({'success': False, 'error': 'Meditation system not available'}), 500
        
        success = meditation_manager.delete_schedule(schedule_id)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Meditation schedule deleted successfully'
            })
        else:
            return jsonify({'success': False, 'error': 'Schedule not found'}), 404
            
    except Exception as e:
        log_error(f"Error deleting meditation schedule: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/meditation/schedules/<schedule_id>', methods=['GET'])
def get_meditation_schedule(schedule_id):
    """Get a specific meditation schedule"""
    try:
        if not MEDITATION_AVAILABLE:
            return jsonify({'success': False, 'error': 'Meditation system not available'}), 500
        
        schedule = meditation_manager.get_schedule(schedule_id)
        
        if schedule:
            return jsonify({
                'success': True,
                'schedule': schedule.to_dict()
            })
        else:
            return jsonify({'success': False, 'error': 'Schedule not found'}), 404
            
    except Exception as e:
        log_error(f"Error getting meditation schedule: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/meditation/today', methods=['GET'])
def get_today_meditation_schedules():
    """Get meditation schedules for today"""
    try:
        if not MEDITATION_AVAILABLE:
            return jsonify({'success': False, 'error': 'Meditation system not available'}), 500
        
        schedules = meditation_manager.get_today_schedules()
        return jsonify({
            'success': True,
            'schedules': [schedule.to_dict() for schedule in schedules],
            'date': datetime.now().strftime('%A, %B %d, %Y')
        })
    except Exception as e:
        log_error(f"Error getting today's meditation schedules: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/meditation/stats', methods=['GET'])
def get_meditation_stats():
    """Get meditation schedule statistics"""
    try:
        if not MEDITATION_AVAILABLE:
            return jsonify({'success': False, 'error': 'Meditation system not available'}), 500
        
        stats = meditation_manager.get_schedule_stats()
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        log_error(f"Error getting meditation stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/meditation/test-notification', methods=['POST'])
def test_meditation_notification():
    """Test meditation notification system"""
    try:
        if not MEDITATION_AVAILABLE:
            return jsonify({'success': False, 'error': 'Meditation system not available'}), 500
        
        # Create a test schedule
        from meditation_schedule_simple import SimpleMeditationSchedule
        test_schedule = SimpleMeditationSchedule(
            schedule_id="test_meditation",
            title="Test Meditation Session",
            time=datetime.now().strftime('%H:%M'),
            duration=15
        )
        
        # Send test notification
        meditation_manager._send_meditation_notification(test_schedule)
        
        return jsonify({
            'success': True,
            'message': 'Test meditation notification sent'
        })
        
    except Exception as e:
        log_error(f"Error testing meditation notification: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/meditation/reset-notifications', methods=['POST'])
def reset_meditation_notifications():
    """Reset daily meditation notifications"""
    try:
        if not MEDITATION_AVAILABLE:
            return jsonify({'success': False, 'error': 'Meditation system not available'}), 500
        
        meditation_manager.reset_daily_notifications()
        
        return jsonify({
            'success': True,
            'message': 'Daily meditation notifications reset'
        })
        
    except Exception as e:
        log_error(f"Error resetting meditation notifications: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ---------------- threads ----------------
def start_background_threads():
    # prevent duplicate starts if this function is ever called twice
    if getattr(app, "_bg_threads_started", False):
        return

    # ROS + diagnostics
    threading.Thread(target=connect_to_ros, daemon=True).start()
    threading.Thread(target=diagnostics_worker, daemon=True).start()

    # Fall model (if enabled)
    if FALL_MODEL_MODE in ('internal', 'hybrid', 'humanfall'):
        threading.Thread(target=fall_worker, daemon=True).start()
    
    # Telegram bot polling (if configured)
    if TELEGRAM_BOT_TOKEN:
        threading.Thread(target=telegram_polling_worker, daemon=True).start()
        log_app("Telegram bot polling started")

    # Optional external helpers
    if os.getenv('START_STT_TTS_BRIDGE', '1') == '1':
        try:
            # Use the new startup script that sets up environment variables
            stt_cmd = os.getenv('STT_TTS_BRIDGE_CMD', 'python3 start_voice_bridge.py')
            stt_env = os.environ.copy(); stt_env['PYTHONUNBUFFERED'] = '1'
            subprocess.Popen(stt_cmd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=stt_env)
            log_app('stt_tts_bridge started with enhanced voice bridge functionality')
        except Exception as e:
            log_error(f'Failed to start stt_tts_bridge: {e}')

    if os.getenv('START_PAN_TILT_NODE', '0') == '1':
        try:
            pt_cmd = os.getenv('PAN_TILT_CMD', 'python3 pan_tilt_ros_onefile.py --mode teleop')
            pt_env = os.environ.copy(); pt_env['PYTHONUNBUFFERED'] = '1'
            subprocess.Popen(pt_cmd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=pt_env)
            log_app('pan_tilt_ros_onefile started')
        except Exception as e:
            log_error(f'Failed to start pan_tilt_ros_onefile: {e}')

    app._bg_threads_started = True


if __name__ == '__main__':
    # Initialize components
    init_voice_db()
    
    # Load state manager
    from utils import state_manager
    state_manager.load_state()
    
    # Log startup
    log_app('TurtleBot Web UI starting up')
    log_app(f'ROS Bridge configured: {ROSBridge_IP}:{ROSBridge_PORT}')
    
    # NEW: start threads even without the reloader
    start_background_threads()
    
    host = '0.0.0.0'; port = 5000
    log_app(f"Web UI hosting at http://{host}:{port}  |  ROSBridge: {ROSBridge_IP}:{ROSBridge_PORT}")
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
