# Telegram Bot Integration for TurtleBot3 Web UI - Thesis Documentation

## Overview
This document provides a comprehensive overview of the Telegram bot integration implemented in the TurtleBot3 Web UI system. The bot enables remote interaction with the robot through natural language commands and AI-powered chat functionality.

## 1. Configuration and Setup

### 1.1 Environment Variables
```python
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')  # Bot token from @BotFather
TELEGRAM_CHAT_ID   = os.getenv('TELEGRAM_CHAT_ID', '')    # User/chat ID for notifications
TELEGRAM_WEBHOOK_SECRET = os.getenv('TELEGRAM_WEBHOOK_SECRET', 'your_webhook_secret')
TELEGRAM_ALLOWED_USERS = os.getenv('TELEGRAM_ALLOWED_USERS', '').split(',') if os.getenv('TELEGRAM_ALLOWED_USERS') else []
```

### 1.2 Required Dependencies
```python
import requests  # For HTTP requests to Telegram API
import threading  # For background polling
import json      # For JSON message handling
from datetime import datetime  # For timestamps
```

## 2. Core Telegram Bot Functions

### 2.1 Message Sending Function
```python
def telegram_bot_send_message(text: str, chat_id: str = None, photo_bytes: bytes = None) -> bool:
    """Send a message (and optional photo) to Telegram chat"""
    if not TELEGRAM_BOT_TOKEN:
        return False
    
    target_chat_id = chat_id or TELEGRAM_CHAT_ID
    if not target_chat_id:
        return False
    
    try:
        if photo_bytes:
            # Send photo with caption
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            files = {'photo': ('photo.jpg', photo_bytes, 'image/jpeg')}
            data = {'chat_id': target_chat_id, 'caption': text}
        else:
            # Send text message
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {'chat_id': target_chat_id, 'text': text}
        
        response = requests.post(url, data=data, files=files if photo_bytes else None, timeout=10)
        return response.ok
    except Exception as e:
        log_error(f"Telegram send error: {e}")
        return False
```

### 2.2 Command Handler
```python
def handle_telegram_command(command: str, chat_id: str, user_id: str = None) -> str:
    """Handle incoming Telegram commands"""
    command = command.lower().strip()
    
    # Authorization check
    if TELEGRAM_ALLOWED_USERS and user_id and str(user_id) not in TELEGRAM_ALLOWED_USERS:
        return "❌ You are not authorized to use this bot."
    
    if command == 'start':
        return """🤖 **Welcome to TurtleBot3 Telegram Bot!**

I'm your robot's remote interface. Here's what I can do:

📋 **Available Commands:**
/help - Show this help message
/status - Get robot status
/photo - Take a photo
/chat - Start interactive chat with AI
/test - Test bot connectivity

🚀 **Ready to help!** Send me a command to get started."""

    elif command == 'status':
        return get_robot_status_for_telegram()
    
    elif command == 'photo':
        try:
            photo_bytes = get_latest_jpeg()
            if photo_bytes:
                caption = f"📸 **Robot Camera Snapshot**\n🕐 {datetime.now().strftime('%H:%M:%S')}"
                telegram_bot_send_message(caption, chat_id, photo_bytes)
                return "📸 Photo sent!"
            else:
                return "❌ No camera image available. Camera may be offline or not initialized."
        except Exception as e:
            return f"❌ Error capturing photo: {str(e)}"
    
    # Additional commands...
```

### 2.3 AI Chat Handler
```python
def handle_telegram_chat(message_text: str, chat_id: str, user_id: str = None) -> str:
    """Handle interactive chat with Gemini AI"""
    # Authorization check
    if TELEGRAM_ALLOWED_USERS and user_id and str(user_id) not in TELEGRAM_ALLOWED_USERS:
        return "❌ You are not authorized to use this bot."
    
    try:
        # Import the STT/TTS core for Gemini integration
        import test_speech as stt_tts_core
        
        # Add robot context to the message
        robot_context = f"""You are an AI assistant for a TurtleBot3 robot. The user is chatting with you via Telegram. 
        
Current robot status:
- Battery: {telemetry_data.get('battery_level', 0.0):.1f}%
- Connected: {telemetry_data.get('connected', False)}
- Camera: {telemetry_data.get('camera_status', 'Unknown')}

User message: {message_text}

Please respond in a helpful, friendly way. You can mention the robot's capabilities like taking photos, checking status, or navigation if relevant to the conversation."""
        
        # Get AI response using Gemini
        ai_response = stt_tts_core.gemini_chat(robot_context)
        
        # Add a small indicator that this is from the robot
        return f"🤖 {ai_response}"
        
    except ImportError:
        return "❌ AI chat feature is not available. Please check the STT/TTS system configuration."
    except Exception as e:
        return f"❌ Error in AI chat: {str(e)}"
```

## 3. Message Polling System

### 3.1 Background Polling Worker
```python
def telegram_polling_worker():
    """Background worker to poll Telegram for new messages"""
    global telegram_last_update_id, telegram_polling_enabled
    
    if not TELEGRAM_BOT_TOKEN:
        log_app("Telegram bot not configured, skipping polling")
        return
    
    log_app("Starting Telegram bot polling worker")
    
    while telegram_polling_enabled:
        try:
            # Get updates from Telegram
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            params = {
                'offset': telegram_last_update_id + 1,
                'timeout': 30,
                'limit': 10
            }
            
            response = requests.get(url, params=params, timeout=35)
            
            if response.ok:
                data = response.json()
                if data.get('ok'):
                    updates = data.get('result', [])
                    
                    for update in updates:
                        telegram_last_update_id = update['update_id']
                        
                        if 'message' in update:
                            message = update['message']
                            chat_id = str(message.get('chat', {}).get('id', ''))
                            user_id = str(message.get('from', {}).get('id', ''))
                            text = message.get('text', '').strip()
                            
                            if not text:
                                continue
                            
                            log_app(f"Telegram message from {user_id}: {text}")
                            
                            # Handle commands (starting with /)
                            if text.startswith('/'):
                                response_text = handle_telegram_command(text, chat_id, user_id)
                            else:
                                # Handle regular chat messages
                                response_text = handle_telegram_chat(text, chat_id, user_id)
                            
                            # Send response back to user
                            if response_text:
                                telegram_bot_send_message(response_text, chat_id)
                                
        except Exception as e:
            log_error(f"Telegram polling error: {e}")
            time.sleep(5)  # Wait before retrying
        
        time.sleep(1)  # Small delay between polling cycles
```

### 3.2 Polling State Management
```python
# Telegram bot polling state
telegram_last_update_id = 0
telegram_polling_enabled = True

def start_background_threads():
    """Start all background threads"""
    # ... other threads ...
    
    # Start Telegram polling thread
    if TELEGRAM_BOT_TOKEN:
        telegram_thread = threading.Thread(target=telegram_polling_worker, daemon=True)
        telegram_thread.start()
        log_app("Telegram polling thread started")
```

## 4. Web API Endpoints

### 4.1 Bot Management Endpoints
```python
@app.route('/telegram-bot')
def telegram_bot_page():
    """Telegram bot management page"""
    return render_template('telegram_bot.html', 
                         TELEGRAM_BOT_TOKEN=TELEGRAM_BOT_TOKEN,
                         TELEGRAM_CHAT_ID=TELEGRAM_CHAT_ID)

@app.route('/api/telegram/test-bot', methods=['POST'])
def test_telegram_bot():
    """Test Telegram bot functionality"""
    try:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return jsonify({
                'success': False,
                'error': 'Telegram bot not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.'
            }), 400
        
        # Test bot connection
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"
        response = requests.get(url, timeout=10)
        
        if response.ok:
            bot_info = response.json()
            return jsonify({
                'success': True,
                'message': 'Bot is working correctly!',
                'bot_info': bot_info.get('result', {})
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to connect to Telegram API'
            }), 400
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
```

### 4.2 Robot Control Endpoints
```python
@app.route('/api/telegram/send-status', methods=['POST'])
def send_telegram_status():
    """Send robot status to Telegram"""
    try:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return jsonify({
                'success': False,
                'error': 'Telegram bot not configured'
            }), 400
        
        status_message = get_robot_status_for_telegram()
        success = telegram_bot_send_message(status_message)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Robot status sent to Telegram'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to send status to Telegram'
            }), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/telegram/send-photo', methods=['POST'])
def send_telegram_photo():
    """Send robot photo to Telegram"""
    try:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return jsonify({
                'success': False,
                'error': 'Telegram bot not configured'
            }), 400
        
        photo_bytes = get_latest_jpeg()
        if photo_bytes:
            caption = f"📸 **Robot Camera Snapshot**\n🕐 {datetime.now().strftime('%H:%M:%S')}"
            success = telegram_bot_send_message(caption, photo_bytes=photo_bytes)
            
            if success:
                return jsonify({
                    'success': True,
                    'message': 'Photo sent to Telegram'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Failed to send photo to Telegram'
                }), 500
        else:
            return jsonify({
                'success': False,
                'error': 'No camera image available'
            }), 400
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
```

## 5. Integration with Robot Systems

### 5.1 Robot Status Integration
```python
def get_robot_status_for_telegram() -> str:
    """Get formatted robot status for Telegram"""
    try:
        # Get current telemetry data
        battery = telemetry_data.get('battery_level', 0.0)
        connected = telemetry_data.get('connected', False)
        camera_status = telemetry_data.get('camera_status', 'Unknown')
        
        # Format status message
        status_emoji = "🟢" if connected else "🔴"
        battery_emoji = "🔋" if battery > 20 else "⚠️"
        camera_emoji = "📷" if camera_status == "Active" else "❌"
        
        status_message = f"""🤖 **TurtleBot3 Status Report**

{status_emoji} **Connection**: {'Connected' if connected else 'Disconnected'}
{battery_emoji} **Battery**: {battery:.1f}%
{camera_emoji} **Camera**: {camera_status}
🕐 **Time**: {datetime.now().strftime('%H:%M:%S')}

Ready for commands!"""
        
        return status_message
        
    except Exception as e:
        return f"❌ Error getting robot status: {str(e)}"
```

### 5.2 Camera Integration
```python
def get_latest_jpeg() -> bytes:
    """Get the latest camera frame as JPEG bytes"""
    try:
        if latest_frame is not None:
            # Convert frame to JPEG
            _, buffer = cv2.imencode('.jpg', latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            return buffer.tobytes()
        return None
    except Exception as e:
        log_error(f"Error getting latest JPEG: {e}")
        return None
```

## 6. Security Features

### 6.1 User Authorization
```python
# Check if user is authorized (if TELEGRAM_ALLOWED_USERS is configured)
if TELEGRAM_ALLOWED_USERS and user_id and str(user_id) not in TELEGRAM_ALLOWED_USERS:
    return "❌ You are not authorized to use this bot."
```

### 6.2 Webhook Security
```python
@app.route('/api/telegram/webhook', methods=['POST'])
def telegram_webhook():
    """Handle incoming Telegram messages via webhook"""
    try:
        if not TELEGRAM_BOT_TOKEN:
            return jsonify({'error': 'Telegram bot not configured'}), 400
        
        # Verify webhook secret if configured
        if TELEGRAM_WEBHOOK_SECRET:
            secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
            if secret != TELEGRAM_WEBHOOK_SECRET:
                return jsonify({'error': 'Unauthorized'}), 401
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data received'}), 400
        
        # Process webhook data...
        
    except Exception as e:
        log_error(f"Webhook error: {e}")
        return jsonify({'error': str(e)}), 500
```

## 7. Error Handling and Logging

### 7.1 Comprehensive Error Handling
```python
try:
    # Telegram API operations
    response = requests.post(url, data=data, files=files if photo_bytes else None, timeout=10)
    return response.ok
except requests.exceptions.Timeout:
    log_error("Telegram API timeout")
    return False
except requests.exceptions.RequestException as e:
    log_error(f"Telegram API request error: {e}")
    return False
except Exception as e:
    log_error(f"Unexpected Telegram error: {e}")
    return False
```

### 7.2 Logging Integration
```python
# Log successful operations
log_app(f"Telegram message sent successfully to chat {chat_id}")

# Log errors
log_error(f"Telegram send error: {e}")

# Log polling status
log_app("Starting Telegram bot polling worker")
log_app(f"Telegram message from {user_id}: {text}")
```

## 8. Key Features Summary

### 8.1 Command System
- **/start** - Welcome message and bot introduction
- **/help** - Display available commands
- **/status** - Get current robot status (battery, connection, camera)
- **/photo** - Capture and send current camera image
- **/chat** - Start interactive AI chat mode
- **/test** - Test bot connectivity

### 8.2 AI Integration
- **Gemini AI Integration** - Natural language processing for general chat
- **Context-Aware Responses** - AI responses include current robot status
- **Robot-Specific Knowledge** - AI understands robot capabilities and limitations

### 8.3 Real-time Communication
- **Polling System** - Continuous message checking for immediate responses
- **Webhook Support** - Alternative webhook-based message handling
- **Background Processing** - Non-blocking message handling

### 8.4 Robot Control
- **Status Monitoring** - Real-time robot status via Telegram
- **Photo Capture** - Remote camera access through bot
- **Fall Detection Integration** - Automatic alerts for safety events

## 9. Technical Architecture

### 9.1 System Components
```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Telegram API  │◄──►│  Flask Web App   │◄──►│  TurtleBot3     │
│                 │    │                  │    │  Robot System   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                              │
                              ▼
                       ┌──────────────────┐
                       │   Gemini AI      │
                       │   Integration    │
                       └──────────────────┘
```

### 9.2 Data Flow
1. **User sends message** → Telegram API
2. **Polling worker** → Retrieves message from Telegram API
3. **Command/Chat handler** → Processes message
4. **Robot integration** → Gets status/camera data if needed
5. **AI processing** → Generates response using Gemini
6. **Response sending** → Sends reply back through Telegram API

## 10. Configuration Requirements

### 10.1 Environment Setup
```bash
# Required environment variables
export TELEGRAM_BOT_TOKEN="your_bot_token_from_botfather"
export TELEGRAM_CHAT_ID="your_telegram_user_id"
export TELEGRAM_ALLOWED_USERS="user_id1,user_id2"  # Optional
export TELEGRAM_WEBHOOK_SECRET="your_secret"       # Optional
```

### 10.2 Bot Creation Process
1. **Create Bot** - Message @BotFather on Telegram
2. **Get Token** - Receive bot token from @BotFather
3. **Get Chat ID** - Use @userinfobot to get your user ID
4. **Configure** - Set environment variables
5. **Test** - Use /test command to verify setup

## 11. Future Enhancements

### 11.1 Potential Improvements
- **Voice Message Support** - Handle voice messages with STT
- **Location Sharing** - Process location data for navigation
- **File Upload** - Handle document and image uploads
- **Group Chat Support** - Multi-user robot control
- **Command Scheduling** - Delayed command execution
- **Advanced AI Features** - Image recognition and analysis

### 11.2 Scalability Considerations
- **Database Integration** - Store chat history and user preferences
- **Multi-Robot Support** - Handle multiple robots from single bot
- **Load Balancing** - Distribute bot load across multiple instances
- **Caching** - Cache frequent responses for better performance

---

This documentation provides a comprehensive overview of the Telegram bot integration for your thesis. The system demonstrates effective integration of modern messaging platforms with robotic systems, enabling intuitive remote interaction through natural language interfaces.
