# Pan Tilt Control Setup Guide

This guide explains how to set up and use the pan tilt control functionality in the TurtleBot3 Web UI.

## Overview

The pan tilt system consists of:
- **Hardware**: Pan/tilt servo motors connected to GPIO pins on Raspberry Pi
- **ROS2 Node**: `pan_tilt_ros_onefile.py` - handles hardware control and ROS communication
- **Web UI**: Pan tilt control interface accessible at `/pantilt`

## Hardware Setup

### GPIO Connections
- **Tilt Servo**: GPIO 18 (BCM)
- **Pan Servo**: GPIO 17 (BCM)
- **Power**: 5V supply for servos
- **Ground**: Common ground

### Servo Specifications
- **Tilt**: Positional servo (20° steps, 0.35s pulse duration)
- **Pan**: Continuous servo (20° steps, timed movement)
- **Range**: 0° to 180° for both axes
- **Center**: 90° for both axes

## Software Setup

### 1. Start the Pan Tilt ROS Node

#### On Raspberry Pi (Driver Mode)
```bash
# Run with sudo for GPIO access
sudo -E python3 pan_tilt_ros_onefile.py --mode driver
```

#### On PC (Teleop Mode - for testing)
```bash
# Run without sudo (no GPIO access needed)
python3 pan_tilt_ros_onefile.py --mode teleop
```

### 2. Verify ROS Topics

Check that the pan tilt topics are available:
```bash
ros2 topic list | grep -E "(pan|tilt)"
```

Expected topics:
- `/pan/step` - Pan step commands (std_msgs/Int32)
- `/pan/center` - Pan center command (std_msgs/Empty)
- `/pan/angle` - Pan angle feedback (std_msgs/Int32)
- `/tilt/step` - Tilt step commands (std_msgs/Int32)
- `/tilt/center` - Tilt center command (std_msgs/Empty)
- `/tilt/angle` - Tilt angle feedback (std_msgs/Int32)

### 3. Test Manual Control

#### Using ROS2 CLI
```bash
# Move pan left (negative step)
ros2 topic pub /pan/step std_msgs/Int32 "data: -1"

# Move pan right (positive step)
ros2 topic pub /pan/step std_msgs/Int32 "data: 1"

# Move tilt up (positive step)
ros2 topic pub /tilt/step std_msgs/Int32 "data: 1"

# Move tilt down (negative step)
ros2 topic pub /tilt/step std_msgs/Int32 "data: -1"

# Center both pan and tilt
ros2 topic pub /pan/center std_msgs/Empty "{}"
ros2 topic pub /tilt/center std_msgs/Empty "{}"
```

#### Using the Teleop Node
When running in teleop mode, use these keyboard controls:
- **1/2/3**: Tilt UP/STOP/DOWN
- **4/5/6**: Pan UP/STOP/DOWN
- **c**: Center both
- **t**: Center tilt only
- **p**: Center pan only
- **Esc**: Quit

## Web UI Usage

### Accessing the Pan Tilt Control
1. Start the web UI: `python3 app.py`
2. Navigate to `http://localhost:5000/pantilt`
3. Ensure the pan tilt ROS node is running

### Web UI Features

#### Visual Controls
- **Pan Control**: Left/Right buttons with step controls
- **Tilt Control**: Up/Down buttons with step controls
- **Preset Positions**: Quick access to common positions
- **Status Display**: Real-time angle feedback and connection status

#### Keyboard Controls
- **Q/A**: Pan Left/Right
- **W/S**: Tilt Up/Down
- **Space**: Stop all movement
- **C**: Center both pan and tilt
- **1/2/3**: Look Forward/Up/Down presets

#### Preset Positions
- **Center**: 90°, 90° (neutral position)
- **Look Forward**: 90°, 45° (slightly down)
- **Look Up**: 90°, 135° (upward)
- **Look Down**: 90°, 0° (downward)

## API Endpoints

The web UI provides these REST API endpoints:

### Status
```bash
GET /api/pantilt/status
# Returns: {"ok": true, "connected": true, "pan_angle": 90, "tilt_angle": 90}
```

### Step Commands
```bash
POST /api/pantilt/pan/step
Content-Type: application/json
{"steps": 1}  # Positive = right, Negative = left

POST /api/pantilt/tilt/step
Content-Type: application/json
{"steps": 1}  # Positive = up, Negative = down
```

### Absolute Positioning
```bash
POST /api/pantilt/set
Content-Type: application/json
{"pan": 90, "tilt": 45}
```

### Center Command
```bash
POST /api/pantilt/center
# Centers both pan and tilt to 90°
```

## Troubleshooting

### Common Issues

#### 1. "Not connected to pan tilt system"
- **Cause**: Pan tilt ROS node not running
- **Solution**: Start the pan tilt node in driver or teleop mode

#### 2. No movement when sending commands
- **Cause**: Hardware not connected or GPIO permissions
- **Solution**: 
  - Check GPIO connections
  - Run driver mode with `sudo`
  - Verify servo power supply

#### 3. Erratic movement
- **Cause**: Power supply issues or loose connections
- **Solution**: 
  - Check 5V power supply to servos
  - Verify all connections are secure
  - Check for interference

#### 4. Web UI shows "Disconnected"
- **Cause**: ROSBridge connection issues
- **Solution**:
  - Verify ROSBridge is running
  - Check ROSBridge IP address in web UI
  - Ensure pan tilt topics are published

### Debug Commands

```bash
# Check if pan tilt node is running
ps aux | grep pan_tilt

# Monitor pan tilt topics
ros2 topic echo /pan/angle
ros2 topic echo /tilt/angle

# Check topic publishing rate
ros2 topic hz /pan/angle
ros2 topic hz /tilt/angle

# List all ROS nodes
ros2 node list

# Check node info
ros2 node info /pan_tilt_driver
```

## Configuration

### Environment Variables
You can customize the pan tilt behavior using these environment variables:

```bash
# Pan/Tilt center positions (default: 90°)
export PAN_CENTER_DEG=90
export TILT_CENTER_DEG=90

# Step sizes (default: 20°)
export PAN_STEP_DEG=20
export TILT_STEP_DEG=20

# Auto-start pan tilt node with web UI
export START_PAN_TILT_NODE=1
export PAN_TILT_CMD="python3 pan_tilt_ros_onefile.py --mode teleop"
```

### Hardware Calibration
If the servos don't center properly at 90°, you can adjust the pulse widths in `pan_tilt_ros_onefile.py`:

```python
# Tilt servo pulse widths (microseconds)
TILT_UP_US    = 1322.2     # "move up"
TILT_MID_US   = 1366.7     # midpoint (reference)
TILT_DOWN_US  = 1411.1     # "move down"

# Pan servo pulse widths (microseconds)
PAN_UP_US     = 1200       # CW rotation
PAN_DOWN_US   = 1500       # CCW rotation
```

## Safety Notes

1. **Power Supply**: Ensure adequate 5V power supply for servos
2. **Mechanical Limits**: Don't force servos beyond their physical limits
3. **GPIO Protection**: Use appropriate voltage level shifters if needed
4. **Emergency Stop**: Always have a way to stop movement quickly
5. **Calibration**: Test movement ranges before mounting camera

## Integration with Other Systems

The pan tilt system can be integrated with:
- **Computer Vision**: Point camera at detected objects
- **Navigation**: Look in direction of movement
- **Telepresence**: Follow user commands
- **Surveillance**: Automated scanning patterns

Example integration code:
```python
# Point camera at detected object
def point_at_object(x, y, image_width, image_height):
    # Convert image coordinates to pan/tilt angles
    pan_angle = 90 + (x - image_width/2) * 0.1  # Scale factor
    tilt_angle = 90 - (y - image_height/2) * 0.1
    
    # Send command via API
    requests.post('http://localhost:5000/api/pantilt/set', 
                  json={'pan': pan_angle, 'tilt': tilt_angle})
```
