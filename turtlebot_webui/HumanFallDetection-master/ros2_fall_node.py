#!/usr/bin/env python3
import threading, time, collections
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import numpy as np

from fall_detector import FallDetector

class RosFallNode(Node):
    def __init__(self):
        super().__init__('fall_detector_ros')
        self.bridge = CvBridge()
        self.queue = collections.deque(maxlen=2)  # keep last frame only
        self.sub = self.create_subscription(Image, '/camera/image_raw', self.cb, 10)

    def cb(self, msg):
        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        self.queue.append(frame)

    def frames(self):
        # generator that yields the newest available frame
        while rclpy.ok():
            if self.queue:
                yield self.queue[-1]
            else:
                time.sleep(0.005)

def main():
    rclpy.init()
    node = RosFallNode()
    fd = FallDetector()  # parses CLI flags passed to this script

    # run detector in background; keep ROS spinning in main thread
    t = threading.Thread(target=lambda: fd.run_with_frames(node.frames()), daemon=True)
    t.start()

    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        try:
            node.destroy_node()
        except Exception:
            pass
        try:
            rclpy.shutdown()
        except Exception:
            pass

if __name__ == '__main__':
    main()

