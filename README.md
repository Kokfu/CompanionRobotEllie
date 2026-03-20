# TurtleBot3 Web UI v3

A comprehensive web interface for controlling TurtleBot3 robots with advanced features including fall detection, navigation, and real-time telemetry.

## 🚀 Features

### Core Functionality
- **Real-time Robot Control**: Keyboard and button-based movement controls
- **Live Video Streaming**: Camera feed with fall detection overlay
- **Telemetry Monitoring**: Battery level, connection status, and system health
- **Navigation System**: Interactive map-based navigation with waypoint management
- **Voice Logging**: Speech-to-text and text-to-speech integration

### Advanced Features
- **Fall Detection**: AI-powered fall detection with Telegram alerts
- **Responsive Design**: Mobile-first design that works on all screen sizes
- **Configuration Management**: Persistent settings with server-side storage
- **State Synchronization**: Real-time synchronization across all interface components
- **Comprehensive Logging**: Organized logging system with file rotation

## 🏗️ Architecture

### Backend Structure
```
├── app.py                 # Main Flask application
├── config.py             # Configuration management
├── nav_backend.py        # Navigation system backend
├── utils/
│   ├── __init__.py       # Utility package initialization
│   ├── logger.py         # Centralized logging system
│   └── state_manager.py  # Shared state management
├── templates/            # HTML templates
├── static/
│   └── js/
│       ├── app.js        # Legacy JavaScript
│       └── shared.js     # Shared JavaScript utilities
└── logs/                 # Log files directory
    ├── app/              # Application logs
    ├── ros/              # ROS communication logs
    ├── errors/           # Error logs
    └── telemetry/        # Telemetry logs
```

### Key Components

#### Configuration System (`config.py`)
- **Persistent Settings**: All settings are saved to `config.json`
- **Validation**: Input validation for IP addresses, ports, and numeric values
- **Type Safety**: Uses dataclasses for type-safe configuration management
- **API Integration**: RESTful API endpoints for configuration management

#### Logging System (`utils/logger.py`)
- **Organized Logging**: Separate log files for different components
- **Log Rotation**: Automatic log rotation to prevent disk space issues
- **Multiple Levels**: INFO, WARNING, ERROR logging levels
- **Structured Format**: Consistent timestamp and formatting across all logs

#### State Management (`utils/state_manager.py`)
- **Shared State**: Synchronized state across all interface components
- **Persistence**: State is automatically saved and restored
- **Event System**: Subscriber pattern for state change notifications
- **Thread Safety**: Thread-safe operations for concurrent access

## 🔧 Configuration

### Environment Variables
Create a `.env` file in the project root:

```env
# ROS Bridge Configuration
ROSBridge_IP=192.168.68.201
ROSBridge_PORT=9090

# Fall Detection
FALL_DECODE_STRIDE=4
FALL_INFER_FPS=2.0
FALL_CONF_THRESH=0.7
FALL_ALERT_COOLDOWN=120
FALL_REQUIRE_CONFIRM=30

# Telegram Alerts
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Navigation
TURTLEBOT3_MODEL=waffle
NAV_MAP_YAML=~/map.yaml
NAV_POINTS_YAML=~/nav_points.yaml
```

### Default Configuration
The system comes with sensible defaults:
- **ROS Bridge**: `192.168.68.201:9090`
- **Base Speed**: `0.2` (20%)
- **Turn Speed**: `0.5` (50%)
- **Fall Detection**: Enabled with 70% confidence threshold
- **Logging**: INFO level with file rotation

## 🚀 Installation

### Prerequisites
- Python 3.8+
- ROS2 (for navigation features)
- TurtleBot3 robot or simulation

### Setup
1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd turtlebot_webui/v3
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

4. **Run the application**:
   ```bash
   python app.py
   ```

5. **Access the interface**:
   Open your browser to `http://localhost:5000`

## 📱 Usage

### Control Interface
- **Keyboard Controls**: WASD or arrow keys for movement
- **Speed Control**: Adjustable speed slider (10%-100%)
- **Emergency Stop**: Spacebar or stop button
- **Video Feed**: Real-time camera stream with fall detection overlay

### Settings Management
- **Connection Settings**: Configure ROS Bridge IP and port
- **Movement Settings**: Adjust base and turn speeds
- **Interface Settings**: Toggle features like dark mode and keyboard controls
- **Persistent Storage**: All settings are automatically saved

### Navigation System
- **Interactive Map**: Click to set waypoints
- **Named Points**: Save and recall common locations
- **Real-time Tracking**: See robot position on the map
- **Path Planning**: Automatic path planning with obstacle avoidance

### Fall Detection
- **AI Monitoring**: Continuous fall detection using pose estimation
- **Telegram Alerts**: Automatic notifications with photos
- **Configurable Thresholds**: Adjust confidence levels and cooldown periods
- **Visual Overlay**: Real-time status display on video feed

## 🔍 API Endpoints

### Configuration API
- `GET /api/config` - Get current configuration
- `POST /api/config/robot` - Update robot settings
- `POST /api/config/ui` - Update UI settings
- `POST /api/config/reset` - Reset to defaults

### State API
- `GET /api/state` - Get current application state
- `POST /api/state/speed` - Update speed setting

### Control API
- `GET /api/command/<direction>/<speed>` - Send movement commands
- `GET /api/telemetry` - Get robot telemetry data
- `GET /api/fall` - Get fall detection status

### Navigation API
- `GET /api/nav/health` - Navigation system status
- `POST /api/nav/goal` - Set navigation goal
- `POST /api/nav/cancel` - Cancel current navigation
- `GET /api/nav/pose` - Get current robot pose

## 🐛 Troubleshooting

### Common Issues

#### Connection Problems
- **Check ROS Bridge**: Ensure ROS Bridge server is running on the configured IP/port
- **Network Connectivity**: Verify network connection to the robot
- **Firewall Settings**: Check if ports 9090 and 5000 are accessible

#### Configuration Issues
- **Settings Not Saving**: Check file permissions for `config.json`
- **Invalid IP Address**: Ensure IP address format is correct (e.g., 192.168.1.100)
- **Port Range**: Port must be between 1-65535

#### Performance Issues
- **High CPU Usage**: Reduce fall detection FPS or increase decode stride
- **Memory Issues**: Check log file sizes and enable log rotation
- **Video Lag**: Reduce video quality or check network bandwidth

### Log Files
Check the following log files for detailed error information:
- `logs/app/app.log` - General application logs
- `logs/ros/ros.log` - ROS communication logs
- `logs/errors/errors.log` - Error logs with stack traces
- `logs/telemetry/telemetry.log` - Telemetry data logs

## 🔄 Recent Updates

### Version 3.0 Improvements
1. **✅ Functional IP Configuration**: Settings now properly save and apply ROS Bridge configuration
2. **✅ Responsive Mobile Design**: Mobile-first design with touch-friendly controls
3. **✅ Better Code Organization**: Modular structure with separate utility packages
4. **✅ Consistent Base Setup**: Shared configuration and state management
5. **✅ Comprehensive Logging**: Organized logging system with proper file structure
6. **✅ Speed Slider Synchronization**: Real-time synchronization across all components

### Technical Improvements
- **Configuration Management**: Server-side configuration with validation
- **State Synchronization**: Real-time state updates across all interface components
- **Error Handling**: Comprehensive error handling with user-friendly messages
- **Performance Optimization**: Debounced API calls and efficient state management
- **Mobile Optimization**: Touch-friendly interface with responsive breakpoints

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📞 Support

For support and questions:
- Create an issue in the repository
- Check the troubleshooting section
- Review the log files for error details

---

**TurtleBot3 Web UI v3** - Advanced robot control interface with modern web technologies.
