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

### 2. Guidance for Images & Assets
To make the page look modern, you should upload the following files to an `/assets` or `/images` folder in your repo:

* **Web Dashboard:** Take a screenshot of the main monitoring page and the navigation page.
* **Telegram Alerts:** Take a screenshot of a "Fall Detected" notification on your phone.
* **The Robot:** A high-quality photo of your physical TurtleBot3 with the Pan-Tilt kit and camera attached.
* **System Architecture:** Export the system flow diagram from your report as a `.png`.

---

### 3. Building Your GitHub Profile
Since you mentioned your interest in **AI, Robotics, and Firmware Engineering**, I recommend setting up a **GitHub Profile README**:
1. Create a new repository with the exact same name as your GitHub username (e.g., `Kokfu/Kokfu`).
2. Add a bio: "Bachelor of Information Technology (Honours) Communications and Networking graduate with a focus on AI and Robotics."
3. **Pin Project Ellie:** This ensures it’s the first project recruiters see.

---

### 4. What additional information is required?
To make this documentation 100% complete, I need the following from you:
1.  **Dependencies:** Do you have a `requirements.txt` or a list of specific Python libraries (e.g., `opencv-python`, `flask-socketio`) that need to be installed?
2.  **License Preference:** Do you want to license this as **MIT** (open for anyone to use) or keep it private/restricted?
3.  **Video Demo:** Do you have a video of the robot navigating or detecting a fall? I can show you how to embed a GIF or a link to a YouTube demo in the README.
4.  **Specific Repositories:** Is your code split across multiple repos (e.g., one for the robot, one for the web dashboard), or is it all in one?
