# file: pan_tilt_ros_onefile.py
# Run:
#   PI  : sudo -E python3 pan_tilt_ros_onefile.py --mode driver
#   PC  :        python3 pan_tilt_ros_onefile.py --mode teleop
#
# Topics:
#   Subscribed by driver:
#     /tilt/step   (std_msgs/Int32)   : +1 up, -1 down, 0 stop
#     /pan/step    (std_msgs/Int32)   : +1 up, -1 down, 0 stop (timed)
#     /tilt/center (std_msgs/Empty)   : center to 90° in steps
#     /pan/center  (std_msgs/Empty)
#   Published by driver:
#     /tilt/angle  (std_msgs/Int32)   : tracked degrees (positional)
#     /pan/angle   (std_msgs/Int32)   : tracked degrees (open-loop)
#
# Teleop keys (on PC):
#   Tilt: 1=UP, 2=STOP, 3=DOWN | Pan: 4=UP, 5=STOP, 6=DOWN
#   c=center both, t=center tilt, p=center pan, Esc=quit

import argparse
import time
import sys

import rclpy
from rclpy.node import Node
from std_msgs.msg import Int32, Empty

# ================= Hardware/logic constants =================
# GPIO pins (BCM) – used only in --mode driver
TILT_PIN = 18
PAN_PIN  = 17
FREQ_HZ  = 50

# Tilt (positional) — your pulses
TILT_UP_US    = 1305.2     # "move up"
TILT_MID_US   = 1366.7     # midpoint (reference)
TILT_DOWN_US  = 1411.1     # "move down"
TILT_STEP_DEG = 20         # degrees per step
TILT_PULSE_S  = 0.35       # how long to hold the pulse

# Pan (continuous) — timed open-loop
PAN_UP_US     = 1200       # treat as "up" (CW)
PAN_DOWN_US   = 1500       # treat as "down" (CCW)
PAN_STEP_DEG  = 20         # degrees per step
PAN_CW_DEGPS  = 85.0       # deg/s at 1200 us
PAN_CCW_DEGPS = 85.0       # deg/s at 1500 us

CENTER_DEG = 90
MIN_DEG, MAX_DEG = 0, 180

def clamp(x, lo, hi): return lo if x < lo else (hi if x > hi else x)
def us_to_dc(us):     return float(us) / 20000.0 * 100.0  # 50 Hz => 20 ms frame

# ============================= DRIVER =============================
class PanTiltDriver(Node):
    """Runs on the Pi. Subscribes to step/center topics, publishes angles, drives GPIO."""
    def __init__(self):
        super().__init__('pan_tilt_driver')

        # Lazy-import GPIO so teleop can run on a PC without RPi.GPIO
        global GPIO
        import RPi.GPIO as GPIO

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(TILT_PIN, GPIO.OUT)
        GPIO.setup(PAN_PIN,  GPIO.OUT)
        self.GPIO = GPIO
        self.tilt_pwm = GPIO.PWM(TILT_PIN, FREQ_HZ)
        self.pan_pwm  = GPIO.PWM(PAN_PIN,  FREQ_HZ)
        self.tilt_pwm.start(0)   # idle = no pulses
        self.pan_pwm.start(0)

        # tracked angles (software model)
        self.tilt_deg = float(CENTER_DEG)
        self.pan_deg  = float(CENTER_DEG)

        # pubs
        self.pub_tilt = self.create_publisher(Int32, '/tilt/angle', 10)
        self.pub_pan  = self.create_publisher(Int32, '/pan/angle',  10)

        # subs
        self.create_subscription(Int32, '/tilt/step',   self.on_tilt_step,   10)
        self.create_subscription(Int32, '/pan/step',    self.on_pan_step,    10)
        self.create_subscription(Empty, '/tilt/center', self.on_tilt_center, 10)
        self.create_subscription(Empty, '/pan/center',  self.on_pan_center,  10)

        # periodic publisher (keeps teleop UI fresh)
        self.create_timer(0.25, self.publish_angles)

        self.get_logger().info("Driver ready (GPIO18: Tilt, GPIO17: Pan).")

    # ------------ Tilt (positional) helpers ------------
    def tilt_step_up(self):
        self.tilt_pwm.ChangeDutyCycle(us_to_dc(TILT_UP_US))
        time.sleep(TILT_PULSE_S)
        self.tilt_pwm.ChangeDutyCycle(0)
        self.tilt_deg = clamp(self.tilt_deg + TILT_STEP_DEG, MIN_DEG, MAX_DEG)

    def tilt_step_down(self):
        self.tilt_pwm.ChangeDutyCycle(us_to_dc(TILT_DOWN_US))
        time.sleep(TILT_PULSE_S)
        self.tilt_pwm.ChangeDutyCycle(0)
        self.tilt_deg = clamp(self.tilt_deg - TILT_STEP_DEG, MIN_DEG, MAX_DEG)

    def tilt_stop(self):
        self.tilt_pwm.ChangeDutyCycle(0)

    def on_tilt_step(self, msg: Int32):
        n = msg.data
        if n == 0:
            self.tilt_stop()
        elif n > 0:
            for _ in range(n): self.tilt_step_up()
        else:
            for _ in range(-n): self.tilt_step_down()

    def on_tilt_center(self, _msg: Empty):
        delta = self.tilt_deg - CENTER_DEG
        if delta == 0: return
        steps = max(1, int(abs(round(delta / TILT_STEP_DEG))))
        if delta > 0:
            for _ in range(steps): self.tilt_step_down()
        else:
            for _ in range(steps): self.tilt_step_up()

    # ------------ Pan (continuous) helpers ------------
    def pan_spin(self, pulse_us, secs):
        self.pan_pwm.ChangeDutyCycle(us_to_dc(pulse_us))
        time.sleep(max(0.0, secs))
        self.pan_pwm.ChangeDutyCycle(0)  # idle = no pulses (prevents creep)

    def pan_step_up(self):
        secs = PAN_STEP_DEG / max(1.0, PAN_CW_DEGPS)
        self.pan_spin(PAN_UP_US, secs)
        self.pan_deg = clamp(self.pan_deg + PAN_STEP_DEG, MIN_DEG, MAX_DEG)

    def pan_step_down(self):
        secs = PAN_STEP_DEG / max(1.0, PAN_CCW_DEGPS)
        self.pan_spin(PAN_DOWN_US, secs)
        self.pan_deg = clamp(self.pan_deg - PAN_STEP_DEG, MIN_DEG, MAX_DEG)

    def pan_stop(self):
        self.pan_pwm.ChangeDutyCycle(0)

    def on_pan_step(self, msg: Int32):
        n = msg.data
        if n == 0:
            self.pan_stop()
        elif n > 0:
            for _ in range(n): self.pan_step_up()
        else:
            for _ in range(-n): self.pan_step_down()

    def on_pan_center(self, _msg: Empty):
        delta = self.pan_deg - CENTER_DEG
        if delta == 0: return
        steps = max(1, int(abs(round(delta / PAN_STEP_DEG))))
        if delta > 0:
            for _ in range(steps): self.pan_step_down()
        else:
            for _ in range(steps): self.pan_step_up()

    # ------------ Publish angles ------------
    def publish_angles(self):
        self.pub_tilt.publish(Int32(data=int(self.tilt_deg)))
        self.pub_pan.publish(Int32(data=int(self.pan_deg)))

    # ------------ Cleanup ------------
    def destroy_node(self):
        try:
            self.tilt_pwm.ChangeDutyCycle(0)
            self.pan_pwm.ChangeDutyCycle(0)
            self.tilt_pwm.stop(); self.pan_pwm.stop()
            self.GPIO.cleanup()
        except Exception:
            pass
        super().destroy_node()

# ============================ TELEOP ============================
class Teleop(Node):
    """Runs on a PC (or Pi). Reads keys and publishes step/center topics. Also shows angles."""
    def __init__(self, use_curses=True):
        super().__init__('pan_tilt_teleop')
        self.pub_tilt_step = self.create_publisher(Int32, '/tilt/step', 10)
        self.pub_pan_step  = self.create_publisher(Int32, '/pan/step',  10)
        self.pub_tilt_ctr  = self.create_publisher(Empty, '/tilt/center', 10)
        self.pub_pan_ctr   = self.create_publisher(Empty, '/pan/center',  10)

        self.tilt_deg = CENTER_DEG
        self.pan_deg  = CENTER_DEG
        self.create_subscription(Int32, '/tilt/angle', self._on_tilt_angle, 10)
        self.create_subscription(Int32, '/pan/angle',  self._on_pan_angle,  10)

        self.use_curses = use_curses

    def _on_tilt_angle(self, msg: Int32):
        self.tilt_deg = msg.data

    def _on_pan_angle(self, msg: Int32):
        self.pan_deg = msg.data

    # --- Key UI (curses) ---
    def run_ui(self):
        import curses
        def loop(stdscr):
            curses.cbreak(); curses.noecho(); curses.curs_set(0)
            stdscr.nodelay(True)
            status = "Ready"
            while rclpy.ok():
                stdscr.clear()
                stdscr.addstr(0,0,"Teleop: 1/2/3 = Tilt UP/STOP/DOWN   |   4/5/6 = Pan UP/STOP/DOWN")
                stdscr.addstr(1,0,"         c=center both  t=center tilt  p=center pan   Esc=quit")
                stdscr.addstr(3,0,f"Tilt angle: {self.tilt_deg:3d}°    Pan angle: {self.pan_deg:3d}°")
                stdscr.addstr(5,0,f"Status: {status}")
                stdscr.refresh()

                rclpy.spin_once(self, timeout_sec=0.0)
                ch = stdscr.getch()
                if ch == -1:
                    time.sleep(0.02); continue
                if ch == 27:  # Esc
                    break
                elif ch == ord('1'):
                    self.pub_tilt_step.publish(Int32(data=+1)); status="Tilt +1"
                elif ch == ord('2'):
                    self.pub_tilt_step.publish(Int32(data=0));  status="Tilt STOP"
                elif ch == ord('3'):
                    self.pub_tilt_step.publish(Int32(data=-1)); status="Tilt -1"
                elif ch == ord('4'):
                    self.pub_pan_step.publish(Int32(data=+1));  status="Pan +1"
                elif ch == ord('5'):
                    self.pub_pan_step.publish(Int32(data=0));   status="Pan STOP"
                elif ch == ord('6'):
                    self.pub_pan_step.publish(Int32(data=-1));  status="Pan -1"
                elif ch in (ord('c'), ord('C')):
                    self.pub_tilt_ctr.publish(Empty()); self.pub_pan_ctr.publish(Empty()); status="Center BOTH"
                elif ch in (ord('t'), ord('T')):
                    self.pub_tilt_ctr.publish(Empty()); status="Center TILT"
                elif ch in (ord('p'), ord('P')):
                    self.pub_pan_ctr .publish(Empty()); status="Center PAN"
                else:
                    pass
            # graceful exit
        import curses
        curses.wrapper(loop)

# ============================ MAIN ============================
def main():
    parser = argparse.ArgumentParser(description="ROS 2 pan/tilt (single-file)")
    parser.add_argument('--mode', choices=['driver','teleop'], required=True,
                        help="driver = run on Pi (GPIO); teleop = run on PC (keyboard)")
    args = parser.parse_args()

    rclpy.init()

    if args.mode == 'driver':
        node = PanTiltDriver()
        try:
            rclpy.spin(node)
        finally:
            node.destroy_node()
            rclpy.shutdown()
    else:
        node = Teleop()
        try:
            node.run_ui()
        finally:
            node.destroy_node()
            rclpy.shutdown()

if __name__ == '__main__':
    main()

