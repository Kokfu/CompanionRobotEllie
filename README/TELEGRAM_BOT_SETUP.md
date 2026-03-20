# 🤖 Telegram Bot Integration Setup Guide

Your TurtleBot3 Web UI now includes a fully integrated Telegram bot with interactive AI chat capabilities!

## 🚀 Quick Start

### 1. Set Up Your Telegram Bot

1. **Create Bot**:
   - Open Telegram and search for `@BotFather`
   - Send `/newbot` command
   - Follow instructions to create your bot
   - Save the bot token (looks like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

2. **Get Chat ID**:
   - Start a chat with your bot
   - Send any message to the bot
   - Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
   - Find your chat ID in the response (looks like: `123456789`)

### 2. Configure Environment Variables

Add these to your `.env` file:

```env
# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Optional: Webhook Configuration
TELEGRAM_WEBHOOK_SECRET=your_webhook_secret
TELEGRAM_ALLOWED_USERS=user1,user2,user3
```

### 3. Start Your Application

```bash
python app.py
```

### 4. Access Bot Management

- Open your browser to `http://localhost:5000`
- Click on **"Telegram Bot"** in the navigation menu
- Use the management interface to test and configure your bot

## 📱 Available Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and introduction |
| `/help` | Show available commands |
| `/status` | Get robot status (battery, connection, camera) |
| `/photo` | Capture and send current photo |
| `/chat` | Start interactive chat with AI |
| `/test` | Test bot connectivity |

## 💬 Interactive AI Chat

Users can send **any text message** (not just commands) to chat with the AI assistant! The bot will:

- Use Gemini AI for intelligent responses
- Include robot context (battery, connection status, etc.)
- Provide helpful information about robot capabilities
- Respond naturally to questions and conversations

## 🔧 Bot Management Interface

Access the bot management page at `/telegram-bot` to:

- **Test Bot**: Send test messages to verify functionality
- **Check Status**: View bot configuration and connection status
- **Set Webhook**: Configure webhook for real-time message handling
- **Send Commands**: Manually trigger bot functions

## 🌐 Webhook Setup (Optional)

For real-time message handling, set up a webhook:

1. **Get your public URL** (use ngrok, cloudflare tunnel, or similar)
2. **Set webhook URL**: `https://yourdomain.com/api/telegram/webhook`
3. **Use the management interface** to configure the webhook

### Using ngrok (for testing):
```bash
# Install ngrok
npm install -g ngrok

# Expose your local server
ngrok http 5000

# Use the https URL for webhook
```

## 🔒 Security Features

- **User Authorization**: Restrict bot access to specific users
- **Command Validation**: All commands are validated before execution
- **Error Handling**: Comprehensive error handling and logging
- **Rate Limiting**: Built-in protection against spam

## 🎯 Key Features

### ✅ **Interactive Commands**
- All basic robot functions accessible via Telegram
- Real-time status updates
- Photo capture and sharing

### ✅ **AI-Powered Chat**
- Natural language conversations with Gemini AI
- Robot context awareness
- Intelligent responses about robot capabilities

### ✅ **Seamless Integration**
- No impact on existing features
- Uses existing camera and status systems
- Integrates with current STT/TTS infrastructure

### ✅ **Professional Management**
- Web-based management interface
- Real-time testing and monitoring
- Easy webhook configuration

## 🧪 Testing

### Test Bot Connection
1. Go to `/telegram-bot` in your web interface
2. Click **"Test Bot"** button
3. Check your Telegram chat for the test message

### Test Commands
1. Send `/start` to your bot
2. Try `/status` to get robot information
3. Send `/photo` to capture an image
4. Type any message to chat with AI

### Test AI Chat
1. Send `/chat` to enable chat mode
2. Type any question or message
3. Get intelligent responses from Gemini AI

## 🔄 Integration Details

The Telegram bot is fully integrated into your existing system:

- **Camera System**: Uses existing `get_latest_jpeg()` function
- **Status System**: Accesses real-time telemetry data
- **AI System**: Uses existing Gemini integration from STT/TTS
- **Logging**: All interactions are logged with existing logging system
- **Configuration**: Uses existing environment variable system

## 🛠️ Troubleshooting

### Common Issues

1. **"Bot not responding"**
   - Check `TELEGRAM_BOT_TOKEN` is set correctly
   - Verify bot token is valid
   - Ensure bot is not blocked

2. **"Chat ID not working"**
   - Verify `TELEGRAM_CHAT_ID` is correct
   - Make sure you've sent a message to the bot first
   - Check the chat ID is numeric

3. **"AI chat not working"**
   - Ensure `GOOGLE_API_KEY` is configured
   - Check STT/TTS system is working
   - Verify `test_speech.py` is accessible

4. **"Webhook not working"**
   - Ensure webhook URL is publicly accessible
   - Check SSL certificate (HTTPS required)
   - Verify webhook secret is set

### Debug Mode

Enable debug logging by setting:
```python
logging.basicConfig(level=logging.DEBUG)
```

## 📞 Support

If you encounter issues:
1. Check the troubleshooting section above
2. Review the application logs
3. Test individual components using the management interface
4. Verify all environment variables are set correctly

## 🎉 You're Ready!

Your TurtleBot3 now has a fully functional Telegram bot with AI chat capabilities! Users can:

- Get real-time robot status updates
- Capture and view photos from the robot camera
- Chat with an intelligent AI assistant
- Control basic robot functions remotely

The bot is designed to be user-friendly and provides a natural way to interact with your robot through Telegram.

---

**Happy robot controlling! 🤖✨**
