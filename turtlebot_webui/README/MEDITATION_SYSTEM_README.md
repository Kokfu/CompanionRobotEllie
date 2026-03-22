# 🧘‍♀️ Meditation Schedule System

A comprehensive meditation scheduling and notification system integrated with the TurtleBot Web UI.

## 🌟 Features

- **Schedule Management**: Create, edit, and delete meditation schedules
- **Flexible Timing**: Set specific times and durations for meditation sessions
- **Repeat Options**: Configure daily, weekly, or one-time schedules
- **Telegram Notifications**: Automatic reminders via Telegram bot
- **Web UI Interface**: Beautiful, responsive web interface for management
- **JSON Persistence**: All schedules stored in JSON format for reliability
- **Status Tracking**: Track notification status and meditation history
- **Background Monitoring**: Continuous monitoring for scheduled times

## 📁 Files Created

### Core System Files
- `meditation_schedule.py` - Main meditation schedule system
- `templates/meditation.html` - Web interface for schedule management
- `test_meditation_system.py` - Test suite for the system
- `demo_meditation.py` - Demonstration script
- `MEDITATION_SYSTEM_README.md` - This documentation

### Data Files (Created at Runtime)
- `meditation_schedules.json` - Stores all meditation schedules
- `app_backup_*.py` - Backup of original app.py before modifications

## 🚀 Quick Start

### 1. Start the Application
```bash
cd /home/kokfu/turtlebot_webui/v3
python3 app.py
```

### 2. Access the Meditation Interface
Open your browser and navigate to:
```
http://localhost:5000/meditation
```

### 3. Create Your First Schedule
1. Click "Add Schedule" button
2. Enter a title (e.g., "Morning Meditation")
3. Set the time (e.g., "08:00")
4. Choose duration (5-60 minutes)
5. Select repeat days (optional)
6. Click "Add Schedule"

### 4. Set Up Telegram Notifications (Optional)
1. Configure your Telegram bot token and chat ID
2. The system will automatically send notifications at scheduled times

## 📋 API Endpoints

### Schedule Management
- `GET /api/meditation/schedules` - Get all schedules
- `POST /api/meditation/schedules` - Create new schedule
- `GET /api/meditation/schedules/<id>` - Get specific schedule
- `PUT /api/meditation/schedules/<id>` - Update schedule
- `DELETE /api/meditation/schedules/<id>` - Delete schedule

### Today's Schedules
- `GET /api/meditation/today` - Get today's scheduled sessions

### Statistics
- `GET /api/meditation/stats` - Get system statistics

### Testing
- `POST /api/meditation/test-notification` - Send test notification
- `POST /api/meditation/reset-notifications` - Reset daily notifications

## 🔧 Configuration

### Environment Variables
The system uses existing Telegram configuration:
- `TELEGRAM_BOT_TOKEN` - Your Telegram bot token
- `TELEGRAM_CHAT_ID` - Your Telegram chat ID

### Schedule Configuration
Each meditation schedule includes:
- **Title**: Name of the meditation session
- **Time**: Scheduled time (HH:MM format)
- **Duration**: Length in minutes (1-120)
- **Repeat Days**: Days of the week to repeat (optional)
- **Enabled**: Whether the schedule is active

## 📊 JSON Data Structure

```json
{
  "schedules": [
    {
      "schedule_id": "meditation_1234567890",
      "title": "Morning Meditation",
      "time": "08:00",
      "duration": 15,
      "enabled": true,
      "repeat_days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
      "notification_sent": false,
      "created_at": "2024-01-15T10:30:00",
      "last_notification": null,
      "notification_count": 0
    }
  ],
  "last_updated": "2024-01-15T10:30:00",
  "version": "1.0"
}
```

## 🔔 Notification System

### How It Works
1. Background thread monitors current time every second
2. Checks if any schedules should trigger at current time
3. Sends Telegram notification if conditions are met
4. Marks notification as sent to prevent duplicates
5. Resets notification status daily

### Notification Message Format
```
🧘 **Meditation Reminder**

📅 **Morning Meditation**
⏰ **Time**: 08:00
⏱️ **Duration**: 15 minutes
📅 **Date**: Monday, January 15, 2024

✨ Time to find your inner peace! 

Take a moment to breathe and center yourself. Your meditation session is ready to begin. 🙏
```

## 🧪 Testing

### Run the Test Suite
```bash
python3 test_meditation_system.py
```

### Run the Demo
```bash
python3 demo_meditation.py
```

### Manual Testing
1. Create a schedule for current time + 1 minute
2. Wait for notification
3. Check Telegram for message
4. Verify notification status in web UI

## 🛠️ Troubleshooting

### Common Issues

#### 1. Meditation System Not Available
- Check that `meditation_schedule.py` is in the same directory as `app.py`
- Verify Python imports are working

#### 2. Telegram Notifications Not Working
- Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set
- Test with the "Test Notification" button
- Check Telegram bot permissions

#### 3. Schedules Not Triggering
- Ensure schedules are enabled
- Check that current day matches repeat days
- Verify time format is HH:MM (24-hour format)

#### 4. Web Interface Not Loading
- Check that Flask app is running
- Verify `/meditation` route is accessible
- Check browser console for JavaScript errors

### Debug Mode
Enable debug logging by setting:
```python
logging.basicConfig(level=logging.DEBUG)
```

## 🔄 Integration with Existing System

### Backward Compatibility
- All existing functionality remains unchanged
- Meditation system is optional and can be disabled
- No impact on robot control, telemetry, or other features

### File Modifications
- `app.py`: Added meditation API endpoints and route
- No other existing files were modified

### Threading
- Meditation monitoring runs in a separate daemon thread
- Does not interfere with existing ROS or Telegram threads

## 📈 Future Enhancements

### Potential Features
- Meditation session tracking and statistics
- Integration with meditation apps (Headspace, Calm)
- Voice-guided meditation sessions
- Progress tracking and streaks
- Custom meditation themes and sounds
- Integration with smart home devices

### API Extensions
- Meditation session logging
- Progress analytics
- Export/import schedules
- Bulk schedule operations

## 🤝 Contributing

To extend the meditation system:

1. **Add New Features**: Extend the `MeditationScheduleManager` class
2. **New API Endpoints**: Add routes in `app.py`
3. **UI Improvements**: Modify `templates/meditation.html`
4. **Testing**: Add tests to `test_meditation_system.py`

## 📝 License

This meditation system is part of the TurtleBot Web UI project and follows the same licensing terms.

## 🙏 Acknowledgments

- Built for mindfulness and well-being
- Integrates seamlessly with existing robot control system
- Designed for ease of use and reliability

---

**Happy Meditating! 🧘‍♀️✨**

For support or questions, please refer to the main TurtleBot Web UI documentation.

