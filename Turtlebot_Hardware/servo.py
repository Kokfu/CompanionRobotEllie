# file: manual_servo_control.py
import pigpio
import curses
import time

# === CONFIG ===
SERVO1 = 18   # GPIO for servo 1 (yellow wire)
SERVO2 = 17   # GPIO for servo 2 (yellow wire)

MIN_US  = 500     # typical SG90 min
MID_US  = 1500    # center
MAX_US  = 2500    # typical SG90 max
STEP_US = 25      # nudge step per key press (tweak as you like)

def clamp(v, lo, hi): return max(lo, min(hi, v))

def main(stdscr):
    pi = pigpio.pi()
    if not pi.connected:
        raise RuntimeError("pigpiod not running. Start with: sudo pigpiod")

    curses.cbreak()
    stdscr.nodelay(True)  # non-blocking getch
    stdscr.keypad(True)
    curses.noecho()
    curses.curs_set(0)

    s1 = MID_US
    s2 = MID_US

    def apply():
        pi.set_servo_pulsewidth(SERVO1, s1)
        pi.set_servo_pulsewidth(SERVO2, s2)

    def draw():
        stdscr.clear()
        stdscr.addstr(0, 0, "Manual Servo Control (pigpio)")
        stdscr.addstr(2, 0, f"Servo1 GPIO {SERVO1}: {s1:4d} µs   Keys: Q (+), A (-)")
        stdscr.addstr(3, 0, f"Servo2 GPIO {SERVO2}: {s2:4d} µs   Keys: W (+), S (-)")
        stdscr.addstr(5, 0, "C = center both   Z = release (stop)   Esc = quit")
        stdscr.addstr(7, 0, f"Range: {MIN_US}-{MAX_US} µs | Step: {STEP_US} µs")
        stdscr.refresh()

    # start centered
    apply()
    draw()

    try:
        while True:
            ch = stdscr.getch()
            if ch == -1:
                time.sleep(0.01)
                continue

            # increase/decrease servo1
            if ch in (ord('q'), ord('Q')):
                s1 = clamp(s1 + STEP_US, MIN_US, MAX_US)
            elif ch in (ord('a'), ord('A')):
                s1 = clamp(s1 - STEP_US, MIN_US, MAX_US)

            # increase/decrease servo2
            elif ch in (ord('w'), ord('W')):
                s2 = clamp(s2 + STEP_US, MIN_US, MAX_US)
            elif ch in (ord('s'), ord('S')):
                s2 = clamp(s2 - STEP_US, MIN_US, MAX_US)

            # center both
            elif ch in (ord('c'), ord('C')):
                s1, s2 = MID_US, MID_US

            # release (stop pulses)
            elif ch in (ord('z'), ord('Z')):
                pi.set_servo_pulsewidth(SERVO1, 0)
                pi.set_servo_pulsewidth(SERVO2, 0)

            # ESC to quit
            elif ch == 27:
                break

            apply()
            draw()

    finally:
        # release servos on exit
        pi.set_servo_pulsewidth(SERVO1, 0)
        pi.set_servo_pulsewidth(SERVO2, 0)
        pi.stop()
        curses.nocbreak()
        stdscr.keypad(False)
        curses.echo()
        curses.curs_set(1)
        curses.endwin()

if __name__ == "__main__":
    curses.wrapper(main)

