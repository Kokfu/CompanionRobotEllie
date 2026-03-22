/**
 * Shared JavaScript functionality for TurtleBot Web UI
 * Provides common utilities and state management
 */

class TurtleBotApp {
    constructor() {
        this.config = {};
        this.state = {};
        this.eventListeners = new Map();
        this.init();
    }

    async init() {
        await this.loadConfig();
        await this.loadState();
        this.setupEventListeners();
    }

    async loadConfig() {
        try {
            const response = await fetch('/api/config');
            if (response.ok) {
                this.config = await response.json();
                console.log('Configuration loaded:', this.config);
            } else {
                throw new Error('Failed to load configuration');
            }
        } catch (error) {
            console.error('Error loading configuration:', error);
            this.showMessage('Error loading configuration: ' + error.message, 'error');
        }
    }

    async loadState() {
        try {
            const response = await fetch('/api/state');
            if (response.ok) {
                this.state = await response.json();
                console.log('State loaded:', this.state);
            } else {
                throw new Error('Failed to load state');
            }
        } catch (error) {
            console.error('Error loading state:', error);
        }
    }

    async saveConfig(type, data) {
        try {
            const response = await fetch(`/api/config/${type}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            });

            if (response.ok) {
                this.showMessage('Configuration saved successfully!', 'success');
                await this.loadConfig();
                return true;
            } else {
                const error = await response.text();
                throw new Error(error);
            }
        } catch (error) {
            console.error(`Error saving ${type} configuration:`, error);
            this.showMessage(`Error saving configuration: ${error.message}`, 'error');
            return false;
        }
    }

    async saveState(key, value) {
        try {
            const response = await fetch('/api/state/speed', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ [key]: value })
            });

            if (response.ok) {
                this.state[key] = value;
                return true;
            } else {
                throw new Error('Failed to save state');
            }
        } catch (error) {
            console.error(`Error saving state ${key}:`, error);
            return false;
        }
    }

    showMessage(message, type = 'info', duration = 3000) {
        // Remove existing messages
        const existingMessages = document.querySelectorAll('.turtlebot-message');
        existingMessages.forEach(msg => msg.remove());

        // Create message element
        const messageDiv = document.createElement('div');
        messageDiv.className = `turtlebot-message turtlebot-message-${type}`;
        messageDiv.textContent = message;
        
        // Style the message
        messageDiv.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 1rem 1.5rem;
            border-radius: 8px;
            color: white;
            font-weight: 500;
            z-index: 10000;
            max-width: 300px;
            word-wrap: break-word;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            animation: slideIn 0.3s ease-out;
            ${type === 'success' ? 'background-color: #16a34a;' : ''}
            ${type === 'error' ? 'background-color: #dc2626;' : ''}
            ${type === 'warning' ? 'background-color: #f59e0b;' : ''}
            ${type === 'info' ? 'background-color: #2563eb;' : ''}
        `;

        // Add animation styles
        if (!document.getElementById('turtlebot-message-styles')) {
            const style = document.createElement('style');
            style.id = 'turtlebot-message-styles';
            style.textContent = `
                @keyframes slideIn {
                    from {
                        transform: translateX(100%);
                        opacity: 0;
                    }
                    to {
                        transform: translateX(0);
                        opacity: 1;
                    }
                }
                @keyframes slideOut {
                    from {
                        transform: translateX(0);
                        opacity: 1;
                    }
                    to {
                        transform: translateX(100%);
                        opacity: 0;
                    }
                }
            `;
            document.head.appendChild(style);
        }

        document.body.appendChild(messageDiv);

        // Remove message after duration
        setTimeout(() => {
            if (messageDiv.parentNode) {
                messageDiv.style.animation = 'slideOut 0.3s ease-in';
                setTimeout(() => {
                    if (messageDiv.parentNode) {
                        messageDiv.parentNode.removeChild(messageDiv);
                    }
                }, 300);
            }
        }, duration);
    }

    setupEventListeners() {
        // Global keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            // Escape key to close messages
            if (e.key === 'Escape') {
                const messages = document.querySelectorAll('.turtlebot-message');
                messages.forEach(msg => msg.remove());
            }
        });
    }

    // Utility methods
    formatSpeed(speed) {
        return `${Math.round(speed * 100)}%`;
    }

    validateIP(ip) {
        const ipRegex = /^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;
        return ipRegex.test(ip);
    }

    validatePort(port) {
        const portNum = parseInt(port);
        return portNum >= 1 && portNum <= 65535;
    }

    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    throttle(func, limit) {
        let inThrottle;
        return function() {
            const args = arguments;
            const context = this;
            if (!inThrottle) {
                func.apply(context, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    }
}

// Global app instance
window.turtlebotApp = new TurtleBotApp();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TurtleBotApp;
}
