# file: manual_servo_degrees.py
import pigpio, curses, time

# ---------------- CONFIG ----------------
# GPIO pins (yellow wire)
S1_GPIO = 18   # Servo1 signal
S2_GPIO = 17   # Servo2 signal

# Per-servo pulse limits (tune these if ends buzz/bind)
S1_MIN_US, S1_MAX_US = 600, 2400
S2_MIN_US, S2_MAX_US = 600, 2400

HOME_DEG = 90            # center
STEP_DEG = 5             # per key press
BIGSTEP_DEG = 15         # with Shift (uppercase)

# ---------------------------------------

def clamp(v, lo, hi): return max(lo, min(hi, v))

def angle_to_us(angle_deg, lo_us, hi_us):
    angle_deg = clamp(angle_deg, 0, 180)
    return int(lo_us + (hi_us - lo_us) * (angle_deg / 180.0))

def main(stdscr):
    pi = pigpio.pi()
    if not pi.connected:
        raise RuntimeError("pigpiod not running. Start with: sudo pigpiod")

    curses.cbreak(); curses.noecho(); curses.curs_set(0)
    stdscr.nodelay(True); stdscr.keypad(True)

    s1 = HOME_DEG
    s2 = HOME_DEG

    def apply():
        pi.set_servo_pulsewidth(S1_GPIO, angle_to_us(s1, S1_MIN_US, S1_MAX_US))
        pi.set_servo_pulsewidth(S2_GPIO, angle_to_us(s2, S2_MIN_US, S2_MAX_US))

    def draw():
        stdscr.clear()
        stdscr.addstr(0, 0, "Two-Servo Degree Controller (pigpio)")
        stdscr.addstr(2, 0, f"Servo1 GPIO {S1_GPIO}: {int(s1):3d}°   Keys: Q (+), A (-)   (Shift = ±{BIGSTEP_DEG}°)")
        stdscr.addstr(3, 0, f"Servo2 GPIO {S2_GPIO}: {int(s2):3d}°   Keys: W (+), S (-)   (Shift = ±{BIGSTEP_DEG}°)")
        stdscr.addstr(5, 0, f"C = center (90°)   Z = release pulses   Esc = quit")
        stdscr.addstr(7, 0, f"Ranges: S1 {S1_MIN_US}-{S1_MAX_US} µs, S2 {S2_MIN_US}-{S2_MAX_US} µs   Step={STEP_DEG}°")
        stdscr.refresh()

    apply(); draw()

    try:
        while True:
            ch = stdscr.getch()
            if ch == -1:
                time.sleep(0.01); continue

            # Uppercase means Shift held
            if ch in (ord('q'), ord('Q')):
                s1 = clamp(s1 + (BIGSTEP_DEG if ch == ord('Q') else STEP_DEG), 0, 180)
            elif ch in (ord('a'), ord('A')):
                s1 = clamp(s1 - (BIGSTEP_DEG if ch == ord('A') else STEP_DEG), 0, 180)

            elif ch in (ord('w'), ord('W')):
                s2 = clamp(s2 + (BIGSTEP_DEG if ch == ord('W') else STEP_DEG), 0, 180)
            elif ch in (ord('s'), ord('S')):
                s2 = clamp(s2 - (BIGSTEP_DEG if ch == ord('S') else STEP_DEG), 0, 180)

            elif ch in (ord('c'), ord('C')):
                s1 = HOME_DEG; s2 = HOME_DEG

            elif ch in (ord('z'), ord('Z')):
                pi.set_servo_pulsewidth(S1_GPIO, 0)
                pi.set_servo_pulsewidth(S2_GPIO, 0)
                # continue loop so you can re-apply after releasing

            elif ch == 27:  # Esc
                break

            apply(); draw()

    finally:
        pi.set_servo_pulsewidth(S1_GPIO, 0)
        pi.set_servo_pulsewidth(S2_GPIO, 0)
        pi.stop()
        curses.nocbreak(); stdscr.keypad(False); curses.echo(); curses.curs_set(1); curses.endwin()

if __name__ == "__main__":
    curses.wrapper(main)

