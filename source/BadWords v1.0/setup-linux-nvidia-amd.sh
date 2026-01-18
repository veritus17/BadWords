#!/bin/bash
set -e

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
if [ -f /etc/os-release ]; then
    . /etc/os-release
    if [[ "$ID_LIKE" == *"debian"* || "$ID" == "debian" ]]; then
        sudo apt update && sudo apt install -y python3-tk ffmpeg python3-pip pipx curl python3-venv
    elif [[ "$ID" == "fedora" || "$ID" == "rhel" ]]; then
        sudo dnf install -y python3-tkinter ffmpeg pipx curl
    elif [[ "$ID_LIKE" == *"arch"* ]]; then
        sudo pacman -S --noconfirm python-tk ffmpeg python-pipx curl
    fi
fi

pipx ensurepath > /dev/null

# 3. AI Engine Installation (GPU)
echo -e "\n${CYAN}--- AI ENGINE SETUP ---${NC}"
echo "Select GPU type for hardware acceleration:"
echo ""
echo "1) NVIDIA (Standard - CUDA 12.x)"
echo "2) NVIDIA (Compatibility - CUDA 11.8)"
echo "3) AMD RADEON (ROCm 6.1 - Best Compatibility)"
echo "4) CPU Only (Slow but Safe)"
read -p "Select [1-4]: " gpu_choice

echo -e "${YELLOW}[INFO] Installing Whisper base...${NC}"

# Clean old env
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

else
    echo -e "${YELLOW}[CPU] Keeping standard installation.${NC}"
fi

# 4. Helper Libraries
echo -e "${YELLOW}[INFO] Installing helper libraries (pypdf)...${NC}"
# Use pip3 install --user because the script runs as a Python module,
# so it needs libraries in the user path, not in the Whisper venv (Whisper runs as subprocess)
pip3 install --user --upgrade pypdf --break-system-packages || pip3 install --user pypdf

# 5. File Copying (Modules)
echo -e "${YELLOW}[INFO] Installing application files...${NC}"
mkdir -p "$INSTALL_DIR"
# Clean old installation to avoid conflicts
rm -rf "$INSTALL_DIR/"*.py
# Copy source folder content
cp -r "$SOURCE_PATH/"* "$INSTALL_DIR/"

echo "Installed modules: $(ls "$INSTALL_DIR" | grep .py | xargs)"

# 6. DaVinci Resolve Integration (Wrapper)
RESOLVE_SCRIPT_DIR=""
POTENTIAL_PATHS=(
    "$HOME/.local/share/DaVinciResolve/Fusion/Scripts/Utility"
    "$HOME/.local/share/DaVinciResolve/Support/Fusion/Scripts/Utility"
    "/opt/resolve/Fusion/Scripts/Utility"
)

for path in "${POTENTIAL_PATHS[@]}"; do
    PARENT_DIR="$(dirname "$(dirname "$path")")"
    if [ -d "$PARENT_DIR" ]; then
        RESOLVE_SCRIPT_DIR="$path"
        break
    fi
done

if [ -z "$RESOLVE_SCRIPT_DIR" ]; then
    RESOLVE_SCRIPT_DIR="$HOME/.local/share/DaVinciResolve/Fusion/Scripts/Utility"
fi
mkdir -p "$RESOLVE_SCRIPT_DIR"
WRAPPER_PATH="$RESOLVE_SCRIPT_DIR/$WRAPPER_NAME"

# Create wrapper setting sys.path so main.py can see its modules (gui, api, engine)
cat > "$WRAPPER_PATH" <<EOF
import sys
import os
import traceback

# Install Directory
INSTALL_DIR = "$INSTALL_DIR"
MAIN_SCRIPT = os.path.join(INSTALL_DIR, "main.py")

# Append dir to sys.path so imports (import gui, import config) work correctly
if INSTALL_DIR not in sys.path:
    sys.path.append(INSTALL_DIR)

if os.path.exists(MAIN_SCRIPT):
    try:
        with open(MAIN_SCRIPT, "r", encoding="utf-8") as f:
            code = f.read()
        
        # Set __file__ to main.py path for relative logic to work
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
    echo "Dependency Check:"
    pipx runpip openai-whisper list | grep torch
    echo -e "${CYAN}Check above: '+cu' = Nvidia, '+rocm' = AMD.${NC}"
fi

read -p "Press Enter to exit..."