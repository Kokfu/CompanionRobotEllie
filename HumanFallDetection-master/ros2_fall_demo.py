#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
import numpy as np, cv2, time

# OpenPifPaf
import openpifpaf

class PifPafROSNode(Node):
    def __init__(self):
        super().__init__('pifpaf_fall_demo')

        # Params
        self.declare_parameter('in_topic', '/image_raw/compressed')
        self.declare_parameter('out_topic', '/fall_detection/annotated/compressed')
        self.declare_parameter('checkpoint', 'resnet50')  # or 'shufflenetv2k30'
        self.declare_parameter('cpu', True)

        in_topic  = self.get_parameter('in_topic').get_parameter_value().string_value
        out_topic = self.get_parameter('out_topic').get_parameter_value().string_value
        checkpoint = self.get_parameter('checkpoint').get_parameter_value().string_value
        cpu = self.get_parameter('cpu').get_parameter_value().bool_value

        # Predictor
        if cpu:
            openpifpaf.network.Factory.device = 'cpu'
        self.predictor = openpifpaf.Predictor(checkpoint=checkpoint)
        self.annotation_painter = openpifpaf.show.AnnotationPainter()

        # I/O
        self.sub = self.create_subscription(CompressedImage, in_topic, self.cb, 10)
        self.pub = self.create_publisher(CompressedImage, out_topic, 10)
        self.get_logger().info(f"Subscribed: {in_topic}")
        self.get_logger().info(f"Publishing: {out_topic}")
        self.get_logger().info(f"Model checkpoint: {checkpoint} on {'CPU' if cpu else 'CUDA'}")

        self.last_fps_t = time.time()
        self.frame_cnt = 0

    def cb(self, msg: CompressedImage):
        # Decode JPEG → BGR
        np_arr = np.frombuffer(msg.data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if frame is None:
            self.get_logger().warn("Failed to decode JPEG frame")
            return

        # Run OpenPifPaf
        preds, _, _ = self.predictor.numpy_image(frame)

        # Draw annotations
        vis = frame.copy()
        self.annotation_painter.annotations(vis, preds)

        # (Optional) very simple fall cue (height≈y-range heuristic):
        # NOTE: Replace with your project’s real fall logic if available.
        if preds:
            ys = [int(kp.y) for ann in preds for kp in ann.data if kp.v > 0]
            if ys:
                h = max(ys) - min(ys)
                if h < vis.shape[0] * 0.25:  # very crude heuristic
                    cv2.putText(vis, "POSSIBLE FALL", (20, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)

        # Re-encode to JPEG and publish
        ok, enc = cv2.imencode('.jpg', vis, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            self.get_logger().warn("JPEG encode failed")
            return
        out = CompressedImage()
        out.header = msg.header
        out.format = 'jpeg'
        out.data = enc.tobytes()
        self.pub.publish(out)

        # FPS log (lightweight)
        self.frame_cnt += 1
        if time.time() - self.last_fps_t >= 5.0:
            fps = self.frame_cnt / (time.time() - self.last_fps_t)
            self.get_logger().info(f"~{fps:.2f} FPS")
            self.last_fps_t = time.time()
            self.frame_cnt = 0

def main():
    rclpy.init()
    node = PifPafROSNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()

