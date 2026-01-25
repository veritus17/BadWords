#!/bin/bash
set -e

# --- TRAP: ZATRZYMANIE OKNA NA KONIEC ---
function finish {
    echo ""
    echo -e "${GREEN}Script execution completed successfully!${NC}"
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
# [SECURE CHANGE] Lokalny folder na biblioteki Pythona (pypdf itp.)
LIBS_DIR="$INSTALL_DIR/libs"

SOURCE_FOLDER_NAME="source"
WRAPPER_NAME="BadWords (Linux).py"
EXTRA_ENV_VARS=""

echo -e "${BLUE}========================================================${NC}"
echo -e "${BLUE}              BadWords - INSTALLER (Linux)              ${NC}"
echo -e "${BLUE}       (Secure Pipx & Local Libs Implementation)        ${NC}"
echo -e "${BLUE}========================================================${NC}"

# 1. Weryfikacja folderu źródłowego
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SOURCE_PATH="$DIR/$SOURCE_FOLDER_NAME"

if [ ! -d "$SOURCE_PATH" ]; then
    echo -e "${RED}[ERROR] Folder '$SOURCE_FOLDER_NAME' not found!${NC}"
    exit 1
fi

if [ ! -f "$SOURCE_PATH/main.py" ]; then
    echo -e "${RED}[ERROR] Missing 'main.py' in '$SOURCE_FOLDER_NAME'!${NC}"
    exit 1
fi

# 2. Zależności systemowe i sprawdzanie wersji Pythona
echo -e "${YELLOW}[INFO] Checking system dependencies...${NC}"

TARGET_PYTHON="python3" # Domyślny systemowy

if [ -f /etc/os-release ]; then
    . /etc/os-release
    
    # Sprawdź wersję Pythona
    IS_TOO_NEW=$(python3 -c "import sys; print(1 if sys.version_info >= (3, 13) else 0)")
    
    if [ "$IS_TOO_NEW" -eq 1 ]; then
        PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        echo -e "${RED}[WARNING] Python $PY_VER detected (Too new for stable GPU libraries).${NC}"
        echo -e "${YELLOW}[FIX] Attempting to install Python 3.11 parallel environment...${NC}"
        
        if [[ "$ID" == "fedora" || "$ID" == "rhel" || "$ID_LIKE" == *"fedora"* ]]; then
            sudo dnf install -y python3.11 python3.11-tkinter
            TARGET_PYTHON="/usr/bin/python3.11"
        elif [[ "$ID_LIKE" == *"debian"* || "$ID" == "debian" ]]; then
            sudo apt update
            sudo apt install -y python3.11 python3.11-venv python3.11-tk
            TARGET_PYTHON="/usr/bin/python3.11"
        fi
        
        if [ -f "$TARGET_PYTHON" ]; then
            echo -e "${GREEN}[SUCCESS] Will use $TARGET_PYTHON for Whisper environment.${NC}"
        else
            echo -e "${RED}[ERROR] Failed to install Python 3.11. Whisper might fail on CPU/GPU.${NC}"
            TARGET_PYTHON="python3"
        fi
    else
        echo -e "${GREEN}[OK] System Python is compatible.${NC}"
    fi

    # Instalacja pakietów systemowych (niezbędne do działania pipx i buildów)
    if [[ "$ID_LIKE" == *"debian"* || "$ID" == "debian" ]]; then
        sudo apt update
        sudo apt install -y python3-tk ffmpeg python3-pip pipx curl python3-venv
    elif [[ "$ID" == "fedora" || "$ID" == "rhel" || "$ID_LIKE" == *"fedora"* ]]; then
        sudo dnf install -y python3-tkinter ffmpeg pipx curl
    elif [[ "$ID_LIKE" == *"arch"* ]]; then
        sudo pacman -S --noconfirm python-tk ffmpeg python-pipx curl
    fi
fi

# Ensure pipx path is available
pipx ensurepath > /dev/null 2>&1 || true

# 3. Przygotowanie katalogów (Czysta instalacja)
echo -e "${YELLOW}[INFO] Preparing installation directory: $INSTALL_DIR${NC}"

if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
fi
mkdir -p "$INSTALL_DIR"
mkdir -p "$LIBS_DIR"

# 4. Konfiguracja Silnika AI (GPU)
echo -e "\n${CYAN}------------ AI ENGINE SETUP ------------${NC}"
echo -e "\n${CYAN}Select GPU type for hardware acceleration:${NC}"
echo ""
echo -e "${GREEN}1) NVIDIA (Standard - CUDA 12.x)${NC}"
echo -e "${GREEN}2) NVIDIA (Compatibility - CUDA 11.8)${NC}"
echo -e "${RED}3) AMD RADEON (Stable - ROCm 6.1)${NC}"
echo -e "${YELLOW}4) CPU Only (Slow but Safe)${NC}"
echo ""
read -p "Select [1-4]: " gpu_choice

echo ""
echo -e "${YELLOW}[INFO] Verifying Whisper environment (via pipx)...${NC}"

# --- SMART WHISPER INSTALL (PIPX) ---
# Używamy pipx, aby zainstalować whisper w całkowicie odizolowanym środowisku.
# To jest 'bezpieczny' sposób instalacji aplikacji Pythonowych.
NEED_BASE_INSTALL=true

if pipx list | grep -q "package openai-whisper"; then
    # Pobieramy wersję pythona wewnątrz venv whispera
    CUR_ENV_PY=$(pipx runpip openai-whisper --version | awk '{print $NF}' | tr -d ')')
    TARGET_ENV_PY=$($TARGET_PYTHON --version 2>&1 | awk '{print $2}')
    
    if [[ "$CUR_ENV_PY" == "$TARGET_ENV_PY"* ]]; then
        echo -e "${GREEN}[OK] Whisper base is already installed on Python $CUR_ENV_PY.${NC}"
        NEED_BASE_INSTALL=false
    else
        echo -e "${YELLOW}[UPDATE] Python mismatch ($CUR_ENV_PY vs $TARGET_ENV_PY). Reinstalling base...${NC}"
    fi
fi

if [ "$NEED_BASE_INSTALL" = true ]; then
    # Instalujemy whisper używając konkretnego interpretera pythona
    pipx reinstall openai-whisper --python $TARGET_PYTHON
fi

# --- SMART LIBRARY SWAP (TORCH) ---
ensure_torch_version() {
    local required_tag="$1"
    local index_url="$2"
    local full_reinstall="$3"

    echo "Checking Torch version inside pipx environment..."
    local current_ver=$(pipx runpip openai-whisper show torch 2>/dev/null | grep Version)
    
    if [[ "$current_ver" == *"$required_tag"* ]]; then
        echo -e "${GREEN}[OK] Correct Torch version detected ($current_ver).${NC}"
    else
        echo -e "${YELLOW}[UPDATE] Installing optimized Torch ($required_tag)...${NC}"
        # Bezpieczne odinstalowanie wewnątrz venv pipx
        pipx runpip openai-whisper uninstall -y torch torchvision torchaudio || true
        
        local install_cmd="pipx runpip openai-whisper install torch torchvision torchaudio --index-url $index_url"
        if [ "$full_reinstall" = "true" ]; then install_cmd="$install_cmd --force-reinstall"; fi
        
        echo "Running: $install_cmd"
        eval $install_cmd
    fi
}

if [ "$gpu_choice" == "1" ]; then
    echo -e "${BLUE}[NVIDIA] Ensuring CUDA 12.x libraries...${NC}"
    ensure_torch_version "+cu121" "https://download.pytorch.org/whl/cu121" "false"
    
elif [ "$gpu_choice" == "2" ]; then
    echo -e "${BLUE}[NVIDIA] Ensuring CUDA 11.8 libraries...${NC}"
    ensure_torch_version "+cu118" "https://download.pytorch.org/whl/cu118" "false"

elif [ "$gpu_choice" == "3" ]; then
    echo -e "${BLUE}[AMD] Ensuring ROCm 6.1 libraries...${NC}"
    ensure_torch_version "rocm" "https://download.pytorch.org/whl/rocm6.1" "false"

    echo ""
    echo -e "${YELLOW}AMD CONFIGURATION:${NC}"
    read -p "Apply HSA_OVERRIDE_GFX_VERSION=10.3.0? (Recommended for RX 6000/7000) [Y/n]: " amd_override
    amd_override=${amd_override:-y}
    if [[ "$amd_override" =~ ^[Yy]$ ]]; then
        EXTRA_ENV_VARS="os.environ['HSA_OVERRIDE_GFX_VERSION'] = '10.3.0'"
    fi
else
    echo -e "${YELLOW}[CPU] Using standard installation.${NC}"
fi

# 4b. Biblioteki Pomocnicze (pypdf) - SECURE LOCAL INSTALL
# [SECURE CHANGE] Zamiast używać niebezpiecznego --break-system-packages lub mieszać pipx z bibliotekami,
# instalujemy pypdf bezpośrednio do folderu 'libs' wewnątrz aplikacji.
echo -e "${YELLOW}[INFO] Installing helper libraries locally into: $LIBS_DIR${NC}"
# Używamy -t (target) aby wskazać folder. --no-user zapobiega instalacji w ~/.local/lib
pip3 install pypdf -t "$LIBS_DIR" --no-user --upgrade --no-warn-script-location

# 5. Kopiowanie Plików Aplikacji
echo -e "${YELLOW}[INFO] Copying application files...${NC}"
cp -r "$SOURCE_PATH/"* "$INSTALL_DIR/"

echo ""
echo -e "${GREEN}=======================================================${NC}"
echo -e "${GREEN}        DONE! Please restart DaVinci Resolve${NC}"
echo -e "${GREEN}       Find the script in Workspace -> Script.${NC}"
echo -e "${GREEN}=======================================================${NC}"
echo ""

# 6. Tworzenie Wrappera dla DaVinci
RESOLVE_SCRIPT_DIR=""
# Standardowa ścieżka Resolve na Linuxie
if [ -d "/opt/resolve/Developer/Scripting/Modules/" ]; then
    RESOLVE_SCRIPT_DIR="$HOME/.local/share/DaVinciResolve/Configs/Scripts/Utility"
    mkdir -p "$RESOLVE_SCRIPT_DIR"
fi

# Fallback
if [ -z "$RESOLVE_SCRIPT_DIR" ] || [ ! -d "$RESOLVE_SCRIPT_DIR" ]; then
    RESOLVE_SCRIPT_DIR="$DIR"
fi
echo -e "${CYAN}[INFO] Installing Wrapper to: $RESOLVE_SCRIPT_DIR${NC}"

WRAPPER_PATH="$RESOLVE_SCRIPT_DIR/$WRAPPER_NAME"

# --- GENEROWANIE WRAPPERA ---
# To tutaj dzieje się magia łączenia kodu.
# Dodajemy LIBS_DIR do sys.path, dzięki czemu 'import pypdf' zadziała w głównym kodzie.
cat > "$WRAPPER_PATH" <<EOF
import sys
import os
import traceback

# --- GPU COMPATIBILITY INJECTION ---
$EXTRA_ENV_VARS
# -----------------------------------

# Paths
INSTALL_DIR = "$INSTALL_DIR"
LIBS_DIR = "$LIBS_DIR"
MAIN_SCRIPT = os.path.join(INSTALL_DIR, "main.py")

# 1. Add Install Dir to sys.path (for api.py, engine.py etc.)
if INSTALL_DIR not in sys.path:
    sys.path.append(INSTALL_DIR)

# 2. Add Local Libs to sys.path (for pypdf)
if LIBS_DIR not in sys.path:
    sys.path.append(LIBS_DIR)

# 3. Execute Main Script
if os.path.exists(MAIN_SCRIPT):
    try:
        with open(MAIN_SCRIPT, "r", encoding="utf-8") as f:
            code = f.read()
        
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

# Verification
export PATH="$HOME/.local/bin:$PATH"
if command -v whisper &> /dev/null; then
    echo -e "${CYAN}[VERIFICATION] Whisper installed via pipx correctly.${NC}"
    echo -e "${CYAN}[DEBUG] Location: $(which whisper)${NC}"
    echo ""
    pipx runpip openai-whisper list | grep torch || echo "Torch not found?" 
    echo -e "${YELLOW}Check above: '+cu' = Nvidia, '+rocm' = AMD.${NC}"
fi