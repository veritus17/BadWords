#!/bin/bash
set -e

# --- TRAP: ZATRZYMANIE OKNA NA KONIEC ---
function finish {
    echo ""
    echo "-------------------------------------------------"
    echo "Script execution finished."
    read -p "Press Enter to close this window..."
}
trap finish EXIT

# --- COLORS ---
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

APP_NAME="BadWords"
INSTALL_DIR="$HOME/.local/share/$APP_NAME"
SOURCE_FOLDER_NAME="source"
WRAPPER_NAME="BadWords (Linux).py"
EXTRA_ENV_VARS="" # Stores GPU-specific env vars for the wrapper

echo -e "${BLUE}=================================================${NC}"
echo -e "${BLUE}           BadWords - INSTALLER (Linux)          ${NC}"
echo -e "${BLUE}=================================================${NC}"

# 1. Source Folder Verification
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SOURCE_PATH="$DIR/$SOURCE_FOLDER_NAME"

if [ ! -d "$SOURCE_PATH" ]; then
    echo -e "${RED}[ERROR] Folder '$SOURCE_FOLDER_NAME' not found!${NC}"
    echo "Ensure the file structure looks like this:"
    echo "  - $0 (this script)"
    echo "  - $SOURCE_FOLDER_NAME/ (folder containing main.py, gui.py, etc.)"
    exit 1
fi

if [ ! -f "$SOURCE_PATH/main.py" ]; then
    echo -e "${RED}[ERROR] Missing 'main.py' in '$SOURCE_FOLDER_NAME'!${NC}"
    exit 1
fi

# 2. System Dependencies
echo -e "${YELLOW}[INFO] Checking system dependencies...${NC}"

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[ERROR] Python 3 could not be found.${NC}"
    echo "Please install Python 3 (e.g., sudo dnf install python3 or sudo apt install python3)"
    exit 1
fi

# Check for FFmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo -e "${RED}[ERROR] FFmpeg could not be found.${NC}"
    echo "Please install FFmpeg (e.g., sudo dnf install ffmpeg or sudo apt install ffmpeg)"
    exit 1
fi

# Check for pipx
if ! command -v pipx &> /dev/null; then
    echo -e "${YELLOW}[INFO] pipx not found. Installing pipx...${NC}"
    
    if command -v dnf &> /dev/null; then
        sudo dnf install -y pipx
    elif command -v apt-get &> /dev/null; then
        sudo apt-get update && sudo apt-get install -y pipx
    elif command -v pacman &> /dev/null; then
        sudo pacman -S --noconfirm python-pipx
    else
        python3 -m pip install --user pipx
        python3 -m pipx ensurepath
    fi
    
    export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v pipx &> /dev/null; then
    echo -e "${RED}[ERROR] Failed to install pipx. Please install it manually.${NC}"
    exit 1
fi

# 3. Clean Install & Create Directory
echo -e "${YELLOW}[INFO] Preparing installation directory: $INSTALL_DIR${NC}"

if [ -d "$INSTALL_DIR" ]; then
    echo -e "${CYAN}[CLEANUP] Removing old version at $INSTALL_DIR...${NC}"
    rm -rf "$INSTALL_DIR"
fi

mkdir -p "$INSTALL_DIR"

# 4. AI Engine Installation (GPU)
echo -e "\n${CYAN}--- AI ENGINE SETUP ---${NC}"
echo "Select GPU type for hardware acceleration:"
echo ""
echo "1) NVIDIA (Standard - CUDA 12.x)"
echo "2) NVIDIA (Compatibility - CUDA 11.8)"
echo "3) AMD RADEON (ROCm 6.1 - Best Compatibility)"
echo "4) CPU Only (Slow but Safe)"
read -p "Select [1-4]: " gpu_choice

echo -e "${YELLOW}[INFO] Installing Whisper base...${NC}"

pipx uninstall openai-whisper > /dev/null 2>&1 || true
pipx install openai-whisper --force

if [ "$gpu_choice" == "1" ]; then
    echo -e "${BLUE}[NVIDIA] Installing CUDA 12.x libraries...${NC}"
    pipx runpip openai-whisper uninstall torch torchvision torchaudio -y
    pipx runpip openai-whisper install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
    
elif [ "$gpu_choice" == "2" ]; then
    echo -e "${BLUE}[NVIDIA] Installing CUDA 11.8 libraries...${NC}"
    pipx runpip openai-whisper uninstall torch torchvision torchaudio -y
    pipx runpip openai-whisper install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

elif [ "$gpu_choice" == "3" ]; then
    echo -e "${BLUE}[AMD] Installing ROCm libraries...${NC}"
    echo "This may take a while (downloading ~2-3GB)..."
    
    pipx runpip openai-whisper uninstall torch torchvision torchaudio -y
    
    if ! pipx runpip openai-whisper install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.1; then
        echo -e "${RED}[ERROR] ROCm installation failed. Falling back to CPU...${NC}"
        pipx runpip openai-whisper install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
    fi

    # --- AMD COMPATIBILITY FIX ---
    echo ""
    echo -e "${YELLOW}AMD CONFIGURATION:${NC}"
    echo "Consumer cards (RX 6000/7000) often require a GFX version override to work with ROCm."
    echo "If you have an RX 6600/6700/6800/6900/7800/7900, type 'y'."
    read -p "Apply HSA_OVERRIDE_GFX_VERSION=10.3.0? [Y/n]: " amd_override
    amd_override=${amd_override:-y} # Default to yes
    
    if [[ "$amd_override" =~ ^[Yy]$ ]]; then
        # This injects the variable into the python wrapper script
        EXTRA_ENV_VARS="os.environ['HSA_OVERRIDE_GFX_VERSION'] = '10.3.0'"
        echo -e "${CYAN}[AMD] Override 10.3.0 applied to wrapper.${NC}"
    fi

else
    echo -e "${YELLOW}[CPU] Keeping standard installation.${NC}"
fi

# 5. Copy Application Files
echo -e "${YELLOW}[INFO] Copying application files...${NC}"
cp -r "$SOURCE_PATH/"* "$INSTALL_DIR/"

# 6. Create Resolve Script Wrapper
RESOLVE_SCRIPT_DIR=""

if [ -d "/opt/resolve/Developer/Scripting/Modules/" ]; then
    RESOLVE_SCRIPT_DIR="$HOME/.local/share/DaVinciResolve/Configs/Scripts/Utility"
    if [ ! -d "$RESOLVE_SCRIPT_DIR" ]; then
        mkdir -p "$RESOLVE_SCRIPT_DIR"
    fi
fi

if [ -z "$RESOLVE_SCRIPT_DIR" ] || [ ! -d "$RESOLVE_SCRIPT_DIR" ]; then
    echo -e "${RED}[WARNING] Could not find DaVinci Resolve Script folder.${NC}"
    echo "You may need to manually copy the wrapper script."
    RESOLVE_SCRIPT_DIR="$DIR"
else
    echo -e "${CYAN}[INFO] Found Resolve Script Dir: $RESOLVE_SCRIPT_DIR${NC}"
fi

WRAPPER_PATH="$RESOLVE_SCRIPT_DIR/$WRAPPER_NAME"

# Create wrapper setting sys.path AND environment variables
cat > "$WRAPPER_PATH" <<EOF
import sys
import os
import traceback

# --- GPU COMPATIBILITY INJECTION ---
$EXTRA_ENV_VARS
# -----------------------------------

# Install Directory
INSTALL_DIR = "$INSTALL_DIR"
MAIN_SCRIPT = os.path.join(INSTALL_DIR, "main.py")

# Append dir to sys.path
if INSTALL_DIR not in sys.path:
    sys.path.append(INSTALL_DIR)

if os.path.exists(MAIN_SCRIPT):
    try:
        with open(MAIN_SCRIPT, "r", encoding="utf-8") as f:
            code = f.read()
        
        # Set __file__ to main.py path
        global_vars = globals().copy()
        global_vars['__file__'] = MAIN_SCRIPT
        
        exec(code, global_vars)
    except Exception as e:
        print(f"Error executing BadWords: {e}")
        traceback.print_exc()
else:
    print(f"CRITICAL: Script not found at {MAIN_SCRIPT}")
EOF

chmod +x "$WRAPPER_PATH"

echo -e "${GREEN}=================================================${NC}"
echo -e "${GREEN}   DONE! Please restart DaVinci Resolve.${NC}"
echo -e "${GREEN}   Find the script in Workspace -> Scripts.${NC}"
echo -e "${GREEN}=================================================${NC}"

# Verification log
export PATH="$HOME/.local/bin:$PATH"
if command -v whisper &> /dev/null; then
    WHISPER_LOC=$(which whisper)
    echo -e "${CYAN}[DEBUG] Whisper found at: $WHISPER_LOC${NC}"
else
    echo -e "${RED}[WARNING] Whisper executable not found in PATH!${NC}"
    echo "You might need to restart your terminal or session."
fi