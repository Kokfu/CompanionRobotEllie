#!/usr/bin/env python3
import threading
import time
from typing import Optional

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage

from flask import Flask, Response, render_template_string

HTML = """
<!doctype html>
<title>ROS2 Image Viewer</title>
<h2>ROS2 Image Viewer</h2>
<p>Streaming: <a href="/stream">/stream</a> | Snapshot: <a href="/snapshot.jpg">/snapshot.jpg</a></p>
<img src="/stream" style="max-width: 100%; height: auto; border: 1px solid #ccc;" />
"""

app = Flask(__name__)

latest_jpeg_lock = threading.Lock()
latest_jpeg: Optional[bytes] = None

class JPEGSub(Node):
    def __init__(self, topic):
        super().__init__('flask_image_view_sub')
        self.sub = self.create_subscription(CompressedImage, topic, self.cb, 10)
        self.get_logger().info(f"Subscribed to {topic}")

    def cb(self, msg: CompressedImage):
        global latest_jpeg
        # msg.data is already jpeg bytes
        with latest_jpeg_lock:
            latest_jpeg = bytes(msg.data)

def ros_spin(topic: str):
    rclpy.init()
    node = JPEGSub(topic)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/snapshot.jpg")
def snapshot():
    with latest_jpeg_lock:
        if latest_jpeg is None:
            # Return an empty 1x1 JPEG if no frame yet
            return Response(b'\xff\xd8\xff\xd9', mimetype='image/jpeg')
        return Response(latest_jpeg, mimetype='image/jpeg')

@app.route("/stream")
def stream():
    def gen():
        boundary = b'--frame\r\n'
        last_sent = 0.0
        while True:
            # throttle to avoid spamming when unchanged
            time.sleep(0.03)
            with latest_jpeg_lock:
                frame = latest_jpeg
            if frame is None:
                continue
            # Multipart MJPEG chunk
            yield boundary
            yield b'Content-Type: image/jpeg\r\n'
            yield b'Content-Length: ' + str(len(frame)).encode() + b'\r\n\r\n'
            yield frame + b'\r\n'
    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    import argparse, os
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="/fall_detection/annotated/compressed",
                        help="sensor_msgs/CompressedImage topic")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    # Start ROS2 subscriber in a background thread
    t = threading.Thread(target=ros_spin, args=(args.topic,), daemon=True)
    t.start()

    # Launch Flask
    # Note: do NOT use debug reloader (it would start ROS twice)
    app.run(host=args.host, port=args.port, debug=False, threaded=True)

