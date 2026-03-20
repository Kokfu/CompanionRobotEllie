// ROS connection configuration
const ROSBRIDGE_SERVER_IP = '10.10.16.100';  // Change to your robot IP
const ROSBRIDGE_PORT = '9090';

// Initialize ROS connection
let ros = new ROSLIB.Ros({
    url: `ws://${ROSBRIDGE_SERVER_IP}:${ROSBRIDGE_PORT}`
});

// Connection event handlers
ros.on('connection', () => {
    console.log('Connected to ROSBridge server');
    document.getElementById('status').innerText = "✅ Connected to Robot";
    document.getElementById('status').className = "connected";
});

ros.on('error', (error) => {
    console.error('Error connecting to ROSBridge server:', error);
    document.getElementById('status').innerText = "❌ Connection Error";
    document.getElementById('status').className = "disconnected";
});

ros.on('close', () => {
    console.log('Connection to ROSBridge server closed');
    document.getElementById('status').innerText = "🔌 Disconnected from Robot";
    document.getElementById('status').className = "disconnected";
});

// Initialize command publisher
const cmdVel = new ROSLIB.Topic({
    ros: ros,
    name: '/cmd_vel',
    messageType: 'geometry_msgs/msg/Twist'
});

// Initialize battery subscriber
const batterySub = new ROSLIB.Topic({
    ros: ros,
    name: '/battery_state',
    messageType: 'sensor_msgs/BatteryState'
});

batterySub.subscribe((message) => {
    const batteryLevel = message.percentage * 100;
    document.getElementById('battery-level').textContent = `${batteryLevel.toFixed(1)}%`;
    document.getElementById('last-update').textContent = new Date().toLocaleString();
});

// Initialize image subscriber
const imageSub = new ROSLIB.Topic({
    ros: ros,
    name: '/image_raw',
    messageType: 'sensor_msgs/CompressedImage'  // Adjust if your topic uses a different message type
});

imageSub.subscribe((message) => {
    // Assuming the image is in base64 format
    const imageData = message.data;
    const imgElement = document.getElementById('camera-feed');
    imgElement.src = 'data:image/jpeg;base64,' + imageData;
});

// Global variables
let currentSpeed = 0.1; // Start with minimum speed
const speedValue = document.getElementById('speed-value');

// Speed control functions
function increaseSpeed() {
    currentSpeed = Math.min(1.0, currentSpeed + 0.1);
    updateSpeedDisplay();
}

function decreaseSpeed() {
    currentSpeed = Math.max(0.1, currentSpeed - 0.1);
    updateSpeedDisplay();
}

function updateSpeedDisplay() {
    speedValue.textContent = currentSpeed.toFixed(1);
}

// Keyboard controls
document.addEventListener('keydown', (event) => {
    switch(event.key) {
        case 'ArrowUp':
            sendCommand('forward', currentSpeed);
            break;
        case 'ArrowDown':
            sendCommand('backward', currentSpeed);
            break;
        case 'ArrowLeft':
            sendCommand('left', currentSpeed);
            break;
        case 'ArrowRight':
            sendCommand('right', currentSpeed);
            break;
        case ' ':
            sendCommand('stop');
            break;
        case '+':
            increaseSpeed();
            break;
        case '-':
            decreaseSpeed();
            break;
    }
});

// Send command to robot with speed
function sendCommand(direction, speed = null) {
    const url = speed ? `/api/command/${direction}/${speed}` : `/api/command/${direction}`;
    fetch(url)
        .then(response => response.json())
        .then(data => {
            if (data.status === 'error') {
                console.error('Failed to send command');
            }
        })
        .catch(error => {
            console.error('Error sending command:', error);
        });
}

// Update status and battery information
function updateStatus() {
    fetch('/api/telemetry')
        .then(response => response.json())
        .then(data => {
            const statusElement = document.getElementById('status');
            const batteryElement = document.getElementById('battery-level');
            const lastUpdateElement = document.getElementById('last-update');
            const fallStatusElement = document.getElementById('fall-status');
            const isFall = data.fall_label === 'fall' && data.fall_confidence >= 0.7; // or use FALL_CONF

            if (data.connected) {
                statusElement.innerHTML = '<span>🟢</span> Connected to Robot';
                statusElement.className = 'status connected';
            } else {
                statusElement.innerHTML = '<span>🔴</span> Disconnected from Robot';
                statusElement.className = 'status disconnected';
            }

            batteryElement.textContent = `${Math.min(100, Math.max(0, data.battery_level)).toFixed(1)}%`;
            lastUpdateElement.textContent = new Date(data.last_update).toLocaleString();
            fallStatusElement.textContent = isFall
            ? `FALL (conf=${data.fall_confidence.toFixed(2)})`
            : `No fall (conf=${data.fall_confidence.toFixed(2)})`;
        })
        .catch(error => {
            console.error('Error fetching telemetry:', error);
        });
}

// Video error handling
function handleVideoError() {
    const videoError = document.getElementById('video-error');
    videoError.style.display = 'block';
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Update status every second
    setInterval(updateStatus, 1000);
}); 
