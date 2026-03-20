#!/usr/bin/env python3
"""
Simple and robust meditation schedule system
"""

import json
import threading
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SimpleMeditationSchedule:
    """Simple meditation schedule representation"""
    
    def __init__(self, schedule_id: str, title: str, time: str, duration: int = 15, 
                 enabled: bool = True, repeat_days: List[str] = None, 
                 notification_sent: bool = False, created_at: str = None,
                 last_notification: str = None, notification_count: int = 0):
        self.schedule_id = schedule_id
        self.title = title
        self.time = time  # Format: "HH:MM"
        self.duration = duration  # Duration in minutes
        self.enabled = enabled
        self.repeat_days = repeat_days or []  # List of days: ['monday', 'tuesday', etc.]
        self.notification_sent = notification_sent
        self.created_at = created_at or datetime.now().isoformat()
        self.last_notification = last_notification
        self.notification_count = notification_count
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'schedule_id': self.schedule_id,
            'title': self.title,
            'time': self.time,
            'duration': self.duration,
            'enabled': self.enabled,
            'repeat_days': self.repeat_days,
            'notification_sent': self.notification_sent,
            'created_at': self.created_at,
            'last_notification': self.last_notification,
            'notification_count': self.notification_count
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SimpleMeditationSchedule':
        """Create from dictionary"""
        return cls(
            schedule_id=data.get('schedule_id', ''),
            title=data.get('title', ''),
            time=data.get('time', ''),
            duration=data.get('duration', 15),
            enabled=data.get('enabled', True),
            repeat_days=data.get('repeat_days', []),
            notification_sent=data.get('notification_sent', False),
            created_at=data.get('created_at', ''),
            last_notification=data.get('last_notification'),
            notification_count=data.get('notification_count', 0)
        )

class SimpleMeditationManager:
    """Simple and robust meditation schedule manager"""
    
    def __init__(self, data_file: str = 'meditation_schedules.json'):
        self.data_file = Path(data_file)
        self.schedules: Dict[str, SimpleMeditationSchedule] = {}
        self.lock = threading.Lock()
        self.telegram_send_func = None
        self.running = False
        self.check_thread = None
        
        # Load existing schedules
        self.load_schedules()
        logger.info(f"Simple meditation manager initialized with {len(self.schedules)} schedules")
        
        # Start monitoring thread
        self.start_monitoring()
    
    def load_schedules(self) -> None:
        """Load schedules from JSON file"""
        try:
            if not self.data_file.exists():
                logger.info("No existing meditation schedules file found, starting fresh")
                self.schedules = {}
                return
            
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.schedules = {}
            for schedule_data in data.get('schedules', []):
                try:
                    schedule = SimpleMeditationSchedule.from_dict(schedule_data)
                    self.schedules[schedule.schedule_id] = schedule
                except Exception as e:
                    logger.warning(f"Error loading schedule {schedule_data.get('schedule_id', 'unknown')}: {e}")
            
            logger.info(f"Loaded {len(self.schedules)} meditation schedules")
            
        except Exception as e:
            logger.error(f"Error loading meditation schedules: {e}")
            self.schedules = {}
    
    def save_schedules(self) -> None:
        """Save schedules to JSON file"""
        try:
            data = {
                'schedules': [schedule.to_dict() for schedule in self.schedules.values()],
                'last_updated': datetime.now().isoformat(),
                'version': '1.0'
            }
            
            # Write directly to the file (simpler approach)
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved {len(self.schedules)} meditation schedules")
            
        except Exception as e:
            logger.error(f"Error saving meditation schedules: {e}")
            import traceback
            traceback.print_exc()
    
    def add_schedule(self, title: str, time: str, duration: int = 15, 
                    repeat_days: List[str] = None) -> str:
        """Add a new meditation schedule"""
        try:
            schedule_id = f"meditation_{int(datetime.now().timestamp())}"
            schedule = SimpleMeditationSchedule(
                schedule_id=schedule_id,
                title=title,
                time=time,
                duration=duration,
                repeat_days=repeat_days or []
            )
            
            with self.lock:
                self.schedules[schedule_id] = schedule
            
            self.save_schedules()
            logger.info(f"Added meditation schedule: {title} at {time}")
            return schedule_id
            
        except Exception as e:
            logger.error(f"Error adding meditation schedule: {e}")
            raise
    
    def update_schedule(self, schedule_id: str, **kwargs) -> bool:
        """Update an existing meditation schedule"""
        try:
            if schedule_id not in self.schedules:
                logger.warning(f"Schedule not found for update: {schedule_id}")
                return False
            
            schedule = self.schedules[schedule_id]
            
            # Update fields
            for key, value in kwargs.items():
                if hasattr(schedule, key):
                    setattr(schedule, key, value)
            
            self.save_schedules()
            logger.info(f"Updated meditation schedule: {schedule_id}")
            return True
                
        except Exception as e:
            logger.error(f"Error updating meditation schedule: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def delete_schedule(self, schedule_id: str) -> bool:
        """Delete a meditation schedule"""
        try:
            if schedule_id not in self.schedules:
                logger.warning(f"Schedule not found: {schedule_id}")
                return False
            
            del self.schedules[schedule_id]
            self.save_schedules()
            logger.info(f"Deleted meditation schedule: {schedule_id}")
            return True
                
        except Exception as e:
            logger.error(f"Error deleting meditation schedule: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_schedule(self, schedule_id: str) -> Optional[SimpleMeditationSchedule]:
        """Get a specific meditation schedule"""
        return self.schedules.get(schedule_id)
    
    def get_all_schedules(self) -> List[SimpleMeditationSchedule]:
        """Get all meditation schedules"""
        return list(self.schedules.values())
    
    def get_today_schedules(self) -> List[SimpleMeditationSchedule]:
        """Get meditation schedules for today"""
        today = datetime.now().strftime('%A').lower()
        today_schedules = []
        
        for schedule in self.schedules.values():
            if not schedule.enabled:
                continue
            
            # Check if it's a repeating schedule for today
            if schedule.repeat_days and today in [day.lower() for day in schedule.repeat_days]:
                today_schedules.append(schedule)
            # Or if it's a one-time schedule created today
            elif not schedule.repeat_days:
                try:
                    created_date = datetime.fromisoformat(schedule.created_at).date()
                    if created_date == datetime.now().date():
                        today_schedules.append(schedule)
                except:
                    pass
        
        return today_schedules
    
    def get_schedule_stats(self) -> Dict:
        """Get meditation schedule statistics"""
        try:
            total_schedules = len(self.schedules)
            enabled_schedules = sum(1 for s in self.schedules.values() if s.enabled)
            today_schedules = len(self.get_today_schedules())
            
            # Count notifications sent today
            today_notifications = 0
            for schedule in self.schedules.values():
                if schedule.last_notification:
                    try:
                        last_notif_date = datetime.fromisoformat(schedule.last_notification).date()
                        if last_notif_date == datetime.now().date():
                            today_notifications += 1
                    except:
                        pass
            
            return {
                'total_schedules': total_schedules,
                'enabled_schedules': enabled_schedules,
                'today_schedules': today_schedules,
                'today_notifications': today_notifications,
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting schedule stats: {e}")
            return {
                'total_schedules': 0,
                'enabled_schedules': 0,
                'today_schedules': 0,
                'today_notifications': 0,
                'error': str(e)
            }
    
    def set_telegram_function(self, telegram_func):
        """Set the telegram function for sending notifications"""
        self.telegram_send_func = telegram_func
        logger.info("Telegram function set for meditation notifications")
    
    def _send_meditation_notification(self, schedule: SimpleMeditationSchedule):
        """Send meditation notification"""
        try:
            message = f"🧘‍♀️ Meditation Reminder\n\n"
            message += f"Time: {schedule.time}\n"
            message += f"Duration: {schedule.duration} minutes\n"
            message += f"Title: {schedule.title}\n\n"
            message += f"Time to meditate! 🧘‍♂️"
            
            if self.telegram_send_func:
                logger.info(f"Sending meditation notification for: {schedule.title}")
                result = self.telegram_send_func(message)
                if result:
                    logger.info(f"✅ Successfully sent meditation notification for: {schedule.title}")
                else:
                    logger.warning(f"❌ Failed to send meditation notification for: {schedule.title}")
            else:
                logger.warning("No telegram function set, cannot send notification")
                
        except Exception as e:
            logger.error(f"Error sending meditation notification: {e}")
            import traceback
            traceback.print_exc()
    
    def reset_daily_notifications(self):
        """Reset daily notification flags"""
        try:
            with self.lock:
                for schedule in self.schedules.values():
                    schedule.notification_sent = False
                
                self.save_schedules()
                logger.info("Reset daily meditation notifications")
                
        except Exception as e:
            logger.error(f"Error resetting daily notifications: {e}")
    
    def start_monitoring(self):
        """Start the background monitoring thread"""
        if self.running:
            return
        
        self.running = True
        self.check_thread = threading.Thread(target=self._monitor_schedules, daemon=True)
        self.check_thread.start()
        logger.info("Started meditation schedule monitoring thread")
    
    def stop_monitoring(self):
        """Stop the background monitoring thread"""
        self.running = False
        if self.check_thread and self.check_thread.is_alive():
            self.check_thread.join(timeout=1)
        logger.info("Stopped meditation schedule monitoring thread")
    
    def _monitor_schedules(self):
        """Background thread to monitor schedules and send notifications"""
        logger.info("Meditation monitoring thread started")
        
        while self.running:
            try:
                current_time = datetime.now()
                current_time_str = current_time.strftime('%H:%M')
                today = current_time.strftime('%A').lower()
                
                # Log monitoring status every 10 minutes
                if current_time.minute % 10 == 0:
                    logger.info(f"Meditation monitoring: {current_time_str}, {today}, {len(self.schedules)} schedules")
                
                with self.lock:
                    for schedule in self.schedules.values():
                        if not schedule.enabled:
                            continue
                        
                        # Check if it's time to send notification
                        if schedule.time == current_time_str:
                            logger.info(f"Found scheduled meditation: {schedule.title} at {schedule.time}")
                            
                            # Check if notification should be sent today
                            should_notify = False
                            
                            # For repeating schedules
                            if schedule.repeat_days and today in [day.lower() for day in schedule.repeat_days]:
                                should_notify = True
                                logger.info(f"Repeating schedule match: {schedule.title} for {today}")
                            # For one-time schedules created today
                            elif not schedule.repeat_days:
                                try:
                                    created_date = datetime.fromisoformat(schedule.created_at).date()
                                    if created_date == current_time.date():
                                        should_notify = True
                                        logger.info(f"One-time schedule match: {schedule.title} created today")
                                except:
                                    pass
                            
                            # Send notification if needed and not already sent today
                            if should_notify and not schedule.notification_sent:
                                logger.info(f"Triggering notification for: {schedule.title}")
                                self._send_meditation_notification(schedule)
                                
                                # Mark as sent
                                schedule.notification_sent = True
                                schedule.last_notification = current_time.isoformat()
                                schedule.notification_count += 1
                                
                                # Save changes
                                self.save_schedules()
                                
                                logger.info(f"✅ Completed meditation notification for: {schedule.title}")
                            elif schedule.notification_sent:
                                logger.info(f"Notification already sent today for: {schedule.title}")
                            else:
                                logger.info(f"Notification not needed for: {schedule.title} (not today's schedule)")
                
                # Check every minute
                threading.Event().wait(60)
                
            except Exception as e:
                logger.error(f"Error in meditation monitoring thread: {e}")
                import traceback
                traceback.print_exc()
                threading.Event().wait(60)  # Wait before retrying
        
        logger.info("Meditation monitoring thread stopped")

# Create global instance
simple_meditation_manager = SimpleMeditationManager()

# For backward compatibility
meditation_manager = simple_meditation_manager
MeditationSchedule = SimpleMeditationSchedule
MeditationScheduleManager = SimpleMeditationManager
