"""
Shared state management for TurtleBot Web UI
Handles synchronization of settings across different components
"""
import threading
import json
from typing import Dict, Any, Callable, Optional
from datetime import datetime
from .logger import log_app

class StateManager:
    """Manages shared application state with persistence and synchronization"""
    
    def __init__(self):
        self._state = {
            'speed': 0.1,
            'rosbridge_ip': '192.168.68.201',
            'rosbridge_port': 9090,
            'connected': False,
            'last_update': None,
            'settings': {
                'base_speed': 0.2,
                'turn_speed': 0.5,
                'dark_mode': False,
                'keyboard_control': True,
                'mouse_control': False,
                'show_fps': True
            }
        }
        self._lock = threading.Lock()
        self._subscribers = {}
        self._persistence_file = 'state.json'
    
    def get_state(self, key: Optional[str] = None) -> Any:
        """Get state value(s)"""
        with self._lock:
            if key is None:
                return self._state.copy()
            return self._state.get(key)
    
    def set_state(self, key: str, value: Any, notify: bool = True) -> bool:
        """Set state value and notify subscribers"""
        try:
            with self._lock:
                old_value = self._state.get(key)
                self._state[key] = value
                self._state['last_update'] = datetime.now().isoformat()
            
            if notify and old_value != value:
                self._notify_subscribers(key, value, old_value)
                self._persist_state()
            
            log_app(f"State updated: {key} = {value}")
            return True
        except Exception as e:
            log_app(f"Error setting state {key}: {e}", level=40)  # ERROR level
            return False
    
    def update_settings(self, settings: Dict[str, Any]) -> bool:
        """Update multiple settings at once"""
        try:
            with self._lock:
                old_settings = self._state['settings'].copy()
                self._state['settings'].update(settings)
                self._state['last_update'] = datetime.now().isoformat()
            
            # Notify for each changed setting
            for key, value in settings.items():
                if old_settings.get(key) != value:
                    self._notify_subscribers(f'settings.{key}', value, old_settings.get(key))
            
            self._persist_state()
            log_app(f"Settings updated: {settings}")
            return True
        except Exception as e:
            log_app(f"Error updating settings: {e}", level=40)
            return False
    
    def subscribe(self, key: str, callback: Callable[[Any, Any], None]) -> str:
        """Subscribe to state changes for a specific key"""
        subscription_id = f"{key}_{datetime.now().timestamp()}"
        if key not in self._subscribers:
            self._subscribers[key] = {}
        self._subscribers[key][subscription_id] = callback
        log_app(f"Subscribed to {key} with ID {subscription_id}")
        return subscription_id
    
    def unsubscribe(self, key: str, subscription_id: str) -> bool:
        """Unsubscribe from state changes"""
        try:
            if key in self._subscribers and subscription_id in self._subscribers[key]:
                del self._subscribers[key][subscription_id]
                if not self._subscribers[key]:
                    del self._subscribers[key]
                log_app(f"Unsubscribed {subscription_id} from {key}")
                return True
        except Exception as e:
            log_app(f"Error unsubscribing {subscription_id} from {key}: {e}", level=40)
        return False
    
    def _notify_subscribers(self, key: str, new_value: Any, old_value: Any):
        """Notify all subscribers of a state change"""
        if key in self._subscribers:
            for subscription_id, callback in self._subscribers[key].items():
                try:
                    callback(new_value, old_value)
                except Exception as e:
                    log_app(f"Error in subscriber {subscription_id}: {e}", level=40)
    
    def _persist_state(self):
        """Persist current state to file"""
        try:
            with open(self._persistence_file, 'w') as f:
                json.dump(self._state, f, indent=2)
        except Exception as e:
            log_app(f"Error persisting state: {e}", level=40)
    
    def load_state(self) -> bool:
        """Load state from file"""
        try:
            with open(self._persistence_file, 'r') as f:
                loaded_state = json.load(f)
            
            with self._lock:
                self._state.update(loaded_state)
            
            log_app("State loaded from file")
            return True
        except FileNotFoundError:
            log_app("No state file found, using defaults")
            return True
        except Exception as e:
            log_app(f"Error loading state: {e}", level=40)
            return False
    
    def reset_to_defaults(self) -> bool:
        """Reset state to default values"""
        try:
            with self._lock:
                self._state = {
                    'speed': 0.1,
                    'rosbridge_ip': '192.168.68.201',
                    'rosbridge_port': 9090,
                    'connected': False,
                    'last_update': datetime.now().isoformat(),
                    'settings': {
                        'base_speed': 0.2,
                        'turn_speed': 0.5,
                        'dark_mode': False,
                        'keyboard_control': True,
                        'mouse_control': False,
                        'show_fps': True
                    }
                }
            
            self._persist_state()
            log_app("State reset to defaults")
            return True
        except Exception as e:
            log_app(f"Error resetting state: {e}", level=40)
            return False

# Global state manager instance
state_manager = StateManager()

# Convenience functions
def get_state(key: Optional[str] = None) -> Any:
    """Get state value(s)"""
    return state_manager.get_state(key)

def set_state(key: str, value: Any, notify: bool = True) -> bool:
    """Set state value"""
    return state_manager.set_state(key, value, notify)

def update_settings(settings: Dict[str, Any]) -> bool:
    """Update multiple settings"""
    return state_manager.update_settings(settings)

def subscribe_to_state(key: str, callback: Callable[[Any, Any], None]) -> str:
    """Subscribe to state changes"""
    return state_manager.subscribe(key, callback)

def unsubscribe_from_state(key: str, subscription_id: str) -> bool:
    """Unsubscribe from state changes"""
    return state_manager.unsubscribe(key, subscription_id)
