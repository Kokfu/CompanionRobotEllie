#!/usr/bin/env python3
import shlex, subprocess
from pathlib import Path
import rclpy
from rclpy.node import Node
from std_srvs.srv import Trigger

class AudioServer(Node):
    def __init__(self):
        super().__init__('audio_server')

        # Node parameters (override at launch or via `ros2 param set`)
        self.declare_parameter('capture_device', 'plughw:1,0')
        self.declare_parameter('play_device', 'default')
        self.declare_parameter('default_dir', str(Path.home()))
        self.declare_parameter('duration_sec', 5)
        self.declare_parameter('gain', 3.0)
        self.declare_parameter('filename', 'test_boost.wav')

        self.capture_device = self.get_parameter('capture_device').value
        self.play_device    = self.get_parameter('play_device').value
        self.default_dir    = Path(self.get_parameter('default_dir').value)

        # One-shot service: record -> boost -> play
        self.create_service(Trigger, 'audio/record_then_play', self.handle_record_then_play)
        self.get_logger().info(f"AudioServer ready | cap={self.capture_device} play={self.play_device}")

    def handle_record_then_play(self, req, res):
        # Read latest param values on each call
        duration = max(1, int(self.get_parameter('duration_sec').value))
        gain     = float(self.get_parameter('gain').value)
        filename = str(self.get_parameter('filename').value)
        out_path = (self.default_dir / filename).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        rec_cmd  = (
            f"arecord -D {shlex.quote(self.capture_device)} -f cd -t wav -d {duration} "
            f"| sox -t wav - -t wav {shlex.quote(str(out_path))} vol {gain}"
        )
        play_cmd = f"aplay -D {shlex.quote(self.play_device)} {shlex.quote(str(out_path))}"

        try:
            subprocess.run(['bash','-lc', rec_cmd], check=True)
            subprocess.run(['bash','-lc', play_cmd], check=True)
            res.success = True
            res.message = f"Recorded {duration}s, gain {gain}, file: {out_path}"
        except subprocess.CalledProcessError as e:
            res.success = False
            res.message = f"Failure: {e}"
        return res

def main():
    rclpy.init()
    node = AudioServer()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == "__main__":
    main()
