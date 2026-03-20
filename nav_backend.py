# nav_backend.py  (Simple Commander edition)
import os, io, math, threading, time, yaml, json
from typing import Optional, Tuple
from flask import Blueprint, jsonify, send_file, request
from PIL import Image  # pip install Pillow pyyaml

# ROS 2
import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from geometry_msgs.msg import PoseWithCovarianceStamped, Twist, PoseStamped

# Nav2 Simple Commander
from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult

# -------- Config (can be overridden via env) --------
# Default to the app's config directory
_APP_ROOT = '/home/kokfu/turtlebot_webui/v3'
_CFG_DIR = os.path.join(_APP_ROOT, 'config')
MAP_YAML_PATH = os.path.expanduser(os.getenv('NAV_MAP_YAML', os.path.join(_CFG_DIR, 'map.yaml')))
POINTS_YAML_PATH = os.path.expanduser(os.getenv('NAV_POINTS_YAML', os.path.join(_CFG_DIR, 'nav_points.yaml')))
TURTLEBOT_MODEL_ENV = os.environ.get('TURTLEBOT3_MODEL', '(unset)')

_node = None
_executor = None
_bp_started = False

# -------- Map metadata --------
if not os.path.exists(MAP_YAML_PATH):
    raise FileNotFoundError(f"MAP_YAML_PATH not found: {MAP_YAML_PATH}")

with open(MAP_YAML_PATH, 'r') as f:
    MAP_META = yaml.safe_load(f)

_map_dir = os.path.dirname(MAP_YAML_PATH)
_map_img_rel = MAP_META['image']
MAP_IMAGE_PATH = _map_img_rel if os.path.isabs(_map_img_rel) else os.path.join(_map_dir, _map_img_rel)
MAP_RESOLUTION = float(MAP_META['resolution'])
ORIGIN_X, ORIGIN_Y, _ = MAP_META['origin']

with Image.open(MAP_IMAGE_PATH) as _im:
    MAP_W, MAP_H = _im.size

def map_to_pixel(mx: float, my: float):
    px = (mx - ORIGIN_X) / MAP_RESOLUTION
    py = (ORIGIN_Y + (MAP_H - 1) * MAP_RESOLUTION - my) / MAP_RESOLUTION
    return px, py

def px_to_map(px: float, py: float):
    mx = ORIGIN_X + px * MAP_RESOLUTION
    my = ORIGIN_Y + (MAP_H - 1 - py) * MAP_RESOLUTION
    return mx, my

def _make_pose(x: float, y: float, yaw_rad: float, frame: str = 'map') -> PoseStamped:
    msg = PoseStamped()
    msg.header.frame_id = frame
    msg.pose.position.x = float(x)
    msg.pose.position.y = float(y)
    msg.pose.orientation.z = math.sin(yaw_rad / 2.0)
    msg.pose.orientation.w = math.cos(yaw_rad / 2.0)
    return msg

# -------- Points persistence helpers (optional) --------
def _load_points() -> dict:
    if not os.path.exists(POINTS_YAML_PATH):
        return {}
    with open(POINTS_YAML_PATH, 'r') as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}

def _save_points(data: dict):
    os.makedirs(os.path.dirname(POINTS_YAML_PATH), exist_ok=True)
    with open(POINTS_YAML_PATH, 'w') as f:
        yaml.safe_dump(data, f)

# -------- ROS2 node --------
class NavGateway(Node):
    def __init__(self):
        super().__init__('web_nav_gateway')

        # Keep your existing pubs/subs for UI and safety
        self.initpose_pub = self.create_publisher(PoseWithCovarianceStamped, 'initialpose', 10)
        self.cmdvel_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self._pose_lock = threading.Lock()
        self._last_pose = None
        self.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', self._on_amcl_pose, 10)

        # Simple Commander
        self.navigator = BasicNavigator()
        # NOTE: BasicNavigator manages its own internal node/spin steps; we do not
        # need to add it to our executor. We just ensure rclpy is initialized.
        self._nav2_ready = False
        threading.Thread(target=self._wait_nav2_active_bg, daemon=True).start()

        # Waypoints store (in-memory, persisted to YAML via endpoints)
        self.named_points = _load_points()  # name -> {x, y, yaw}

    # --- AMCL pose callback ---
    def _on_amcl_pose(self, msg: PoseWithCovarianceStamped):
        q = msg.pose.pose.orientation
        yaw = math.atan2(2.0 * q.w * q.z, 1.0 - 2.0 * q.z * q.z)
        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y
        with self._pose_lock:
            self._last_pose = (x, y, yaw)

    def get_last_pose(self) -> Optional[Tuple[float, float, float]]:
        with self._pose_lock:
            return self._last_pose

    # --- Nav2 lifecycle wait (non-blocking to not stall Flask) ---
    def _wait_nav2_active_bg(self):
        try:
            # Will block until Nav2 lifecycle is ACTIVE
            self.navigator.waitUntilNav2Active()
            self._nav2_ready = True
        except Exception as e:
            self.get_logger().warn(f"waitUntilNav2Active failed: {e}")

    # --- Initial pose ---
    def publish_initialpose(self, x: float, y: float, yaw_rad: float):
        # Publish traditional /initialpose (for RViz/AMCL)
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = 'map'
        msg.pose.pose.position.x = float(x)
        msg.pose.pose.position.y = float(y)
        msg.pose.pose.orientation.z = math.sin(yaw_rad / 2.0)
        msg.pose.pose.orientation.w = math.cos(yaw_rad / 2.0)
        msg.pose.covariance[0]  = 0.25
        msg.pose.covariance[7]  = 0.25
        msg.pose.covariance[35] = (math.radians(10))**2
        self.initpose_pub.publish(msg)

        # Also set via Commander helper (publishes initialpose internally)
        try:
            self.navigator.setInitialPose(_make_pose(x, y, yaw_rad))
        except Exception as e:
            self.get_logger().warn(f"setInitialPose failed (will rely on /initialpose): {e}")

    # --- Navigate (blocking) ---
    def navigate_to_sync(self, x: float, y: float, yaw_rad: float = 0.0) -> dict:
        if not self._nav2_ready:
            # Try a final quick wait without blocking forever
            t0 = time.time()
            while not self._nav2_ready and (time.time() - t0) < 5.0:
                time.sleep(0.1)
            if not self._nav2_ready:
                return {'accepted': False, 'status': -2, 'error': 'Nav2 not active'}

        goal = _make_pose(x, y, yaw_rad)
        try:
            self.navigator.goToPose(goal)
        except Exception as e:
            return {'accepted': False, 'status': -1, 'error': f'goToPose failed: {e}'}

        t0 = time.time()
        while not self.navigator.isTaskComplete():
            # Optional: fetch feedback; could be exposed via a new endpoint if you want live ETA
            _ = self.navigator.getFeedback()
            if (time.time() - t0) > 300.0:
                try:
                    self.navigator.cancelTask()
                except Exception:
                    pass
                return {'accepted': True, 'status': -4, 'error': 'result timeout'}
            time.sleep(0.1)
            
            result = self.navigator.getResult()

        # Make a robust status payload for any Commander version
        def _code(r):
            # try to extract an int-like code
            if isinstance(r, (int, float)):
                return int(r)
            v = getattr(r, 'value', None)
            if isinstance(v, (int, float)):
                return int(v)
            return -9  # unknown

        def _name(r):
            return getattr(r, 'name', str(r))

        return {
            'accepted': True,
            'status': _name(result),          # e.g. "SUCCEEDED" / "CANCELED" / "FAILED"
            'status_code': _code(result)      # e.g. 0/1/2 depending on Commander/Nav2
        }


    # --- Cancel current task ---
    def cancel_goal_sync(self) -> dict:
        try:
            self.navigator.cancelTask()
            return {'cancel_sent': True}
        except Exception as e:
            return {'cancel_sent': False, 'error': str(e)}

    # --- E-stop (cancel + brake zeros) ---
    def cancel_active(self) -> dict:
        info = self.cancel_goal_sync()
        return info

    def hard_brake(self, duration_sec: float = 1.0, rate_hz: float = 20.0):
        msg = Twist()
        dt = 1.0 / rate_hz
        end = time.time() + duration_sec
        while time.time() < end:
            self.cmdvel_pub.publish(msg)
            time.sleep(dt)

    # --- Named points helpers ---
    def set_point(self, name: str, x: float, y: float, yaw: float):
        self.named_points[name] = {'x': float(x), 'y': float(y), 'yaw': float(yaw)}
        _save_points(self.named_points)

    def get_point(self, name: str):
        return self.named_points.get(name)

    def all_points(self) -> dict:
        return dict(self.named_points)

# ----- Blueprint -----
nav_bp = Blueprint('nav', __name__, url_prefix='/api/nav')

@nav_bp.get('/health')
def api_health():
    return jsonify({
        'node': _node is not None,
        'model_env': TURTLEBOT_MODEL_ENV,
        'map_yaml': MAP_YAML_PATH,
        'nav2_active': bool(_node and _node._nav2_ready)
    })

@nav_bp.post('/init_pose')
def api_init_pose():
    data = request.get_json(force=True) or {}
    x = float(data.get('x', 0.0)); y = float(data.get('y', 0.0)); yaw = float(data.get('yaw', 0.0))
    _node.publish_initialpose(x, y, yaw)
    return jsonify({'ok': True})

@nav_bp.post('/goal')
def api_goal():
    data = request.get_json(force=True) or {}
    x = float(data['x']); y = float(data['y']); yaw = float(data.get('yaw', 0.0))
    result = _node.navigate_to_sync(x, y, yaw)
    return jsonify(result)

@nav_bp.post('/cancel')
def api_cancel():
    result = _node.cancel_goal_sync()
    return jsonify(result)

@nav_bp.post('/estop')
def api_estop():
    cancel_info = _node.cancel_active()
    _node.hard_brake(duration_sec=1.0, rate_hz=20.0)
    return jsonify({'ok': True, 'cancel': cancel_info})

@nav_bp.get('/pose')
def api_pose():
    p = _node.get_last_pose()
    if p is None:
        return jsonify({'has_pose': False})
    x, y, yaw = p
    return jsonify({'has_pose': True, 'x': x, 'y': y, 'yaw': yaw})

@nav_bp.get('/mapmeta')
def api_mapmeta():
    return jsonify({
        'width_px': MAP_W,
        'height_px': MAP_H,
        'resolution': MAP_RESOLUTION,
        'origin': [ORIGIN_X, ORIGIN_Y],
        'image': '/api/nav/map_image'
    })

@nav_bp.get('/map_image')
def map_image():
    with Image.open(MAP_IMAGE_PATH) as im:
        buf = io.BytesIO()
        im.save(buf, format='PNG')
        buf.seek(0)
        return send_file(buf, mimetype='image/png')

# --- Named points endpoints (optional but handy) ---
@nav_bp.get('/points')
def api_points_list():
    return jsonify(_node.all_points())

@nav_bp.post('/points')
def api_points_set():
    """Body: {"name":"A","x":..., "y":..., "yaw":...}  (yaw in radians)"""
    data = request.get_json(force=True) or {}
    name = str(data['name']).strip()
    x = float(data['x']); y = float(data['y']); yaw = float(data.get('yaw', 0.0))
    _node.set_point(name, x, y, yaw)
    return jsonify({'ok': True, 'saved': {name: _node.get_point(name)}})

@nav_bp.post('/goto_point')
def api_goto_point():
    """Body: {"name":"A"}"""
    data = request.get_json(force=True) or {}
    name = str(data['name']).strip()
    p = _node.get_point(name)
    if not p:
        return jsonify({'accepted': False, 'status': -5, 'error': f'Point "{name}" not found'}), 404
    result = _node.navigate_to_sync(p['x'], p['y'], p.get('yaw', 0.0))
    return jsonify(result)

@nav_bp.post('/save_here')
def api_save_here():
    data = request.get_json(force=True) or {}
    name = str(data.get('name', '')).strip()
    if not name:
        return jsonify({'ok': False, 'error': 'name required'}), 400
    p = _node.get_last_pose()
    if p is None:
        return jsonify({'ok': False, 'error': 'No AMCL pose yet'}), 409
    x, y, yaw = p
    _node.set_point(name, x, y, yaw)
    return jsonify({'ok': True, 'saved': {name: _node.get_point(name)}})

@nav_bp.post('/save_from_click')
def api_save_from_click():
    data = request.get_json(force=True) or {}
    name = str(data.get('name','')).strip()
    if not name:
        return jsonify({'ok': False, 'error': 'name required'}), 400
    try:
        px = float(data['px']); py = float(data['py'])
    except Exception:
        return jsonify({'ok': False, 'error': 'px/py required'}), 400
    yaw_deg = float(data.get('yaw_deg', 0.0))
    mx, my = px_to_map(px, py)
    _node.set_point(name, mx, my, math.radians(yaw_deg))
    return jsonify({'ok': True, 'saved': {name: _node.get_point(name)}})

@nav_bp.post('/points/delete')
def api_points_delete():
    data = request.get_json(force=True) or {}
    name = str(data.get('name','')).strip()
    if not name:
        return jsonify({'ok': False, 'error': 'name required'}), 400
    points = _node.all_points()
    if name not in points:
        return jsonify({'ok': False, 'error': f'"{name}" not found'}), 404
    del points[name]
    _save_points(points)
    _node.named_points = points
    return jsonify({'ok': True})

@nav_bp.post('/goto_sequence')
def api_goto_sequence():
    data = request.get_json(force=True) or {}
    names = data.get('names', [])
    if not names:
        return jsonify({'ok': False, 'error': 'names[] required'}), 400
    poses = []
    for n in names:
        p = _node.get_point(n)
        if not p:
            return jsonify({'ok': False, 'error': f'missing "{n}"'}), 404
        poses.append(_make_pose(p['x'], p['y'], p.get('yaw', 0.0)))
    try:
        _node.navigator.goThroughPoses(poses)
    except Exception as e:
        return jsonify({'ok': False, 'error': f'goThroughPoses failed: {e}'}), 500
    t0 = time.time()
    while not _node.navigator.isTaskComplete():
        _ = _node.navigator.getFeedback()
        if (time.time() - t0) > 1800:
            try:
                _node.navigator.cancelTask()
            except Exception:
                pass
            return jsonify({'ok': False, 'error': 'sequence timeout'}), 504
        time.sleep(0.1)
    res = _node.navigator.getResult()
    name = getattr(res, 'name', str(res))
    return jsonify({'ok': True, 'result': name})

def start_ros():
    global _node, _executor, _bp_started
    if _bp_started:
        return
    _bp_started = True

    if not rclpy.ok():
        rclpy.init()

    _node = NavGateway()
    _executor = MultiThreadedExecutor()
    _executor.add_node(_node)

    def _spin():
        try:
            _executor.spin()
        finally:
            if rclpy.ok():
                rclpy.shutdown()

    threading.Thread(target=_spin, daemon=True).start()

