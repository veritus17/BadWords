# **BadWords – Cleaner Timelines, Faster.**

Automatically detect and/or remove **filler words**, **silence**, and **bad takes** in DaVinci Resolve using OpenAI Whisper. Designed specifically for **Linux**.

### **🐧 Linux SIMPLE Setup Instructions Down Below**

**💡 Other OS versions coming soon\!** 

## **🚀 Features**

* **Smart Detection** — Finds filler words (umm, ahh), silence, and repeated sentences using AI.  
* **DaVinci Integrated** — Runs directly inside Resolve as a Workflow Script.  
* **Safe & Clean** — Uses pipx for an isolated environment, keeping your system packages clean.  
* **GPU Accelerated** — Utilizes your GPU for fast transcription (via Torch/CUDA/ROCm).  
* **Interactive Review** — Review cuts before applying them to the timeline.

## **⭐ Core Capabilities**

* **Filler Word Removal**: Auto-cut "yyy", "eee", "umm" and custom words.  
* **Silence Removal**: Detects silence based on dB threshold.  
* **Script Comparison**: Paste your script to find deviations or missing lines.  
* **Non-Destructive**: Creates a new timeline with cuts, preserving your original edit.

## **Quick Start (Linux)**

### **1\) Download**

Click 👉️ [here](https://github.com/veritus17/BadWords/releases/download/BadWords-v1.0.2/BadWords.1.0.2.zip) 👈️ to download the latest release .zip package, and extract it into a folder

### **2\) Run the Installer**

Open the folder in your terminal and run the setup script:

**Make it executable**  
chmod \+x setup-linux-nvidia-amd.sh

**Run the installer**  
./setup-linux-nvidia-amd.sh

The script will:

* Ask for sudo to install minimal dependencies (ffmpeg, python3-tk, pipx).  
* Install OpenAI Whisper in a safe, isolated environment.  
* Configure the script in DaVinci Resolve.

### **3\) Launch in DaVinci Resolve**

1. Open **DaVinci Resolve**.  
2. Open your Project and Timeline.  
3. Go to **Workspace → Scripts → BadWords**  
4. Enjoy easier editing\!

## **🛠️ Requirements**

* **OS**: Linux (Ubuntu, Mint, Fedora, Arch, etc.)  
* **App**: DaVinci Resolve (Free or Studio)  
* **Internet**: Required for initial setup to download AI models and required packages.  
* **GPU**: Both **NVIDIA** and **AMD** cards supported\!

## **🤝 Contribute**

This is an open-source project. Feel free to open issues or pull requests to improve the tool\!

Contact me here: <br>
[![Reddit](https://img.shields.io/badge/Reddit-FF4500?style=for-the-badge&logo=reddit&logoColor=white)](https://www.reddit.com/message/compose/?to=KoxSwYT)

**Note:** This tool is not affiliated with Blackmagic Design. Use at your own risk.
