#!/bin/bash
set -e

# --- COLORS ---
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

APP_NAME="BadWordsCutter"
INSTALL_DIR="$HOME/.local/share/$APP_NAME"
SCRIPT_SOURCE="main.py" 
WRAPPER_NAME="BadWords (Linux Distro).py"

echo -e "${BLUE}=================================================${NC}"
echo -e "${BLUE}   BadWords - ULTIMATE INSTALLER (STABLE V2)     ${NC}"
echo -e "${BLUE}=================================================${NC}"

# 1. Source File Check
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SOURCE_PATH="$DIR/$SCRIPT_SOURCE"

if [ ! -f "$SOURCE_PATH" ]; then
    if [ -f "$DIR/BadWords_Core_Final.py" ]; then
        SOURCE_PATH="$DIR/BadWords_Core_Final.py"
    else
        echo -e "${RED}[ERROR] File '$SCRIPT_SOURCE' missing!${NC}"
        echo "Please verify the main python file is present."
        exit 1
    fi
fi

# 2. System Dependencies
echo -e "${YELLOW}[INFO] Checking system dependencies...${NC}"
if [ -f /etc/os-release ]; then
    . /etc/os-release
    if [[ "$ID_LIKE" == *"debian"* || "$ID" == "debian" ]]; then
        sudo apt update && sudo apt install -y python3-tk ffmpeg python3-pip pipx curl python3-venv
    elif [[ "$ID" == "fedora" || "$ID" == "rhel" ]]; then
        # Fedora often has Python 3.12/3.13. We try to ensure compatibility.
        sudo dnf install -y python3-tkinter ffmpeg pipx curl
    elif [[ "$ID_LIKE" == *"arch"* ]]; then
        sudo pacman -S --noconfirm python-tk ffmpeg python-pipx curl
    fi
fi

pipx ensurepath > /dev/null

# 3. GPU ENGINE INSTALLATION
echo -e "\n${CYAN}--- AI ENGINE SETUP ---${NC}"
echo "Select your GPU type for hardware acceleration:"
echo ""
echo "1) NVIDIA (Standard - CUDA 12.x)"
echo "2) NVIDIA (Compatibility - CUDA 11.8)"
echo "3) AMD RADEON (ROCm 6.1 - Most Compatible)"
echo "4) CPU Only (Slow but Safe)"
read -p "Select [1-4]: " gpu_choice

echo -e "${YELLOW}[INFO] Installing base Whisper...${NC}"

# Clean old env
pipx uninstall openai-whisper > /dev/null 2>&1 || true

# TIP: PyTorch for ROCm often lags behind latest Python versions (e.g. 3.13).
# We attempt to install using default python first.
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
    echo "Note: This downloads large files (~2-3GB). Please wait."
    
    pipx runpip openai-whisper uninstall torch torchvision torchaudio -y
    
    # FIX: Use ROCm 6.1 which has broader support than 6.2 for now
    # Also removing '--index-url' exclusivity might help pip find partial matches, but let's stick to official repo first.
    # If this fails on Python 3.13, user needs Python 3.12/3.11 installed.
    
    if ! pipx runpip openai-whisper install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.1; then
        echo -e "${RED}[ERROR] Installation failed. It seems your Python version might be too new for ROCm PyTorch.${NC}"
        echo -e "${YELLOW}[TRYING FALLBACK] Attempting CPU version installation for safety...${NC}"
        pipx runpip openai-whisper install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
    fi

else
    echo -e "${YELLOW}[CPU] Keeping standard installation.${NC}"
fi

# 4. Helper Libraries
echo -e "${YELLOW}[INFO] Installing helper libraries (pypdf)...${NC}"
pip3 install --user --upgrade pypdf --break-system-packages || pip3 install --user pypdf

# 5. File Setup
echo -e "${YELLOW}[INFO] Updating script files...${NC}"
mkdir -p "$INSTALL_DIR"
cp "$SOURCE_PATH" "$INSTALL_DIR/main_script.py"

# 6. DaVinci Resolve Integration
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

cat > "$WRAPPER_PATH" <<EOF
import sys
import os
import traceback

MAIN_SCRIPT = "$INSTALL_DIR/main_script.py"

if os.path.exists(MAIN_SCRIPT):
    try:
        with open(MAIN_SCRIPT, "r", encoding="utf-8") as f:
            code = f.read()
        exec(code, globals())
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
else:
    print(f"CRITICAL: Script not found at {MAIN_SCRIPT}")
EOF

chmod +x "$WRAPPER_PATH"

echo -e "${GREEN}=================================================${NC}"
echo -e "${GREEN}   DONE! Please restart DaVinci Resolve.${NC}"
echo -e "${GREEN}=================================================${NC}"

# Verification log
export PATH="$HOME/.local/bin:$PATH"
if command -v whisper &> /dev/null; then
    echo "Dependency Check:"
    pipx runpip openai-whisper list | grep torch
    echo -e "${CYAN}Check above: '+cu' = Nvidia, '+rocm' = AMD.${NC}"
fi

read -p "Press Enter to exit..."