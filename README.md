# Project Ellie: Smart Companion Robot for Elderly Care

Project Ellie is a multi-functional companion robot built on the **TurtleBot3 Burger** platform. It leverages AI, IoT, and Robotics to provide autonomous monitoring, fall detection, and voice companionship for the elderly living alone.

## 🚀 Key Features

* **Autonomous Navigation & Mapping:** Utilizes **SLAM** (Simultaneous Localization and Mapping) to map home environments and navigate rooms effectively without blind spots.
* **AI-Powered Fall Detection:** Implements real-time human pose estimation using **PoseNet** and **OpenPifPaf** to detect accidents and immediately alert caregivers.
* **Intelligent Voice Interaction:** Features hands-free communication powered by **Whisper (STT)**, **Gemini AI (NLP)**, and **Google TTS** for natural conversation.
* **Comprehensive Web Dashboard:** A **Flask-based** interface designed for remote monitoring, viewing live video feeds, and manual robot control.
* **Telegram Integration:** Automated emergency alerts for falls and scheduled meditation reminders sent directly to mobile devices.

## 🛠️ Technical Stack

| Category | Technology |
| :--- | :--- |
| **Robotics Framework** | ROS2 Humble |
| **Operating System** | Ubuntu Server 22.04 (SBC) & Desktop (Remote PC) |
| **Languages** | Python, JavaScript, HTML/CSS |
| **AI/ML** | PoseNet, OpenPifPaf, Whisper AI, Gemini API |
| **Backend/Web** | Flask, ROSBridge WebSocket |

## 🏗️ Hardware Components

* **Chassis:** TurtleBot3 Burger
* **Processing:** Raspberry Pi 3B+ (SBC)
* **Vision/Sensing:** LDS-01 LiDAR, RPi Camera V2, USB Microphone
* **Motion/Audio:** Dynamixel Motors, Pan-Tilt Servos, USB Speaker

## 🔧 Installation & Setup

### 1. Network Configuration
* Connect all devices to a dedicated local network (e.g., SSID: "FYP").
* Assign static IPs: 
    * **Turtlebot3 (SBC):** `192.168.1.100`
    * **Remote PC:** `192.168.1.102`
* Synchronize the environment variable: `export ROS_DOMAIN_ID=30` on all devices.

### 2. Robot Deployment (SBC)
```bash
# Source the workspace
source ~/turtlebot3_ws/install/setup.bash

# Execute the automated startup script
./robot_start.sh
```

### 3. Remote Dashboard (PC)
```bash
# Navigate to the web directory and launch the Flask app
python3 app.py

Access the dashboard at http://192.168.1.102:5000.

```

### 4. Telegram Alert Setup
1. Message @BotFather on Telegram to generate an API Token.

2. Input your Chat ID and API Token into the Web UI’s Telegram Management settings to enable real-time notifications.


---

### Images & Assets
# Refer to /images directory to check for related images
---

