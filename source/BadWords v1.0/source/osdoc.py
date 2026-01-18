#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#Copyright (c) 2026 Szymon Wolarz
#Licensed under the MIT License. See LICENSE file in the project root for full license information.

"""
MODULE: osdoc.py
ROLE: Tool Layer / System Abstraction (Docker-like)
DESCRIPTION:
Detects the operating system (Linux/Mint, Windows, macOS).
Provides universal methods for system operations (paths, shell commands),
manages error logging, and captures DaVinci console output.
Also performs dependency checks and system health diagnostics.
"""

import os
import sys
import platform
import shutil
import logging
import subprocess
import tempfile
import datetime

# ==========================================
# 1. LOGGING & STREAM PROXY
# ==========================================

class ResolveStreamProxy:
    """
    Captures stdout/stderr streams so error messages
    go both to the DaVinci console and the log file.
    """
    def __init__(self, stream, log_func):
        self.stream = stream
        self.log_func = log_func
    
    def write(self, data):
        try:
            if data.strip(): 
                self.log_func(f"[STDOUT/ERR] {data.strip()}")
            self.stream.write(data)
        except: 
            pass 
    
    def flush(self):
        try:
            if hasattr(self.stream, 'flush'): 
                self.stream.flush()
        except: 
            pass 
            
    def __getattr__(self, attr):
        return getattr(self.stream, attr)

def log_info(msg):
    logging.info(msg)
    try:
        print(f"[INFO] {msg}")
    except:
        pass

def log_error(msg):
    logging.error(msg)
    try:
        print(f"[ERROR] {msg}", file=sys.__stderr__)
    except:
        pass

# ==========================================
# 2. OS DOCTOR CLASS
# ==========================================

class OSDoctor:
    def __init__(self):
        """
        Initializes the system doctor.
        Detects OS, sets up paths, logging, and checks environment.
        """
        self.os_type = platform.system()
        self.is_win = (self.os_type == "Windows")
        self.is_mac = (self.os_type == "Darwin")
        self.is_linux = (self.os_type == "Linux")
        
        # Restore home_dir required by engine.py
        self.home_dir = os.path.expanduser("~")
        
        # Paths setup
        self.app_data_dir = self._init_app_data()
        self.log_file = os.path.join(self.app_data_dir, "badwords.log")
        self.temp_dir = os.path.join(self.app_data_dir, "temp")
        self.saves_dir = os.path.join(self.app_data_dir, "saves")
        
        # Initialize logging subsystem
        self._setup_logging()
        
        # Initial diagnostics
        self._log_system_info()

    def _init_app_data(self):
        """
        Creates and returns the application data directory 
        following OS conventions.
        """
        if self.is_win:
            base = os.getenv('APPDATA')
            if not base:
                base = os.path.expanduser("~\\AppData\\Roaming")
        elif self.is_mac:
            base = os.path.expanduser("~/Library/Application Support")
        else:
            # Linux (XDG standard or fallback to home config)
            base = os.getenv('XDG_CONFIG_HOME', os.path.expanduser("~/.config"))
            
        path = os.path.join(base, "BadWords")
        
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            print(f"CRITICAL: Cannot create app data dir: {e}")
            # Fallback to temp if main config fails
            path = os.path.join(tempfile.gettempdir(), "BadWords_Fallback")
            os.makedirs(path, exist_ok=True)
            
        return path

    def _setup_logging(self):
        """Configures logging to file and stream redirection."""
        # Reset logging handlers if re-initialized
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
            
        logging.basicConfig(
            filename=self.log_file,
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Redirect stdout/stderr to capture internal errors
        sys.stdout = ResolveStreamProxy(sys.__stdout__, logging.info)
        sys.stderr = ResolveStreamProxy(sys.__stderr__, logging.error)

    def _log_system_info(self):
        """Logs detailed system information for debugging."""
        log_info("="*30)
        log_info(f"BadWords Session Started")
        log_info(f"OS: {self.os_type} {platform.release()} ({platform.version()})")
        log_info(f"Python: {sys.version}")
        log_info(f"App Data Dir: {self.app_data_dir}")
        log_info("="*30)

    # ==========================
    # PATHS & RESOLVE API
    # ==========================

    def get_resolve_api_path(self):
        """Returns the standard path for DaVinci Resolve Scripting API modules."""
        if self.is_win:
            # Typical path on Windows
            program_data = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
            return os.path.join(
                program_data,
                "Blackmagic Design", "DaVinci Resolve", "Support",
                "Developer", "Scripting", "Modules", ""
            )
        elif self.is_mac:
            return "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/"
        else:
            # Linux default
            return "/opt/resolve/Developer/Scripting/Modules/"

    def get_ffmpeg_cmd(self):
        """
        Returns OS-specific FFmpeg command suggestion.
        Prioritizes local binaries for portable installs.
        """
        # 1. Check local directory (common for portable builds)
        local_ffmpeg_win = "ffmpeg.exe"
        if self.is_win and os.path.exists(local_ffmpeg_win):
            return os.path.abspath(local_ffmpeg_win)
            
        local_ffmpeg_nix = "./ffmpeg"
        if not self.is_win and os.path.exists(local_ffmpeg_nix):
            return os.path.abspath(local_ffmpeg_nix)

        # 2. Linux specific user bin check
        if self.is_linux:
            local_bin = os.path.expanduser("~/.local/bin/ffmpeg")
            if os.path.exists(local_bin):
                return local_bin
                
        # 3. System PATH fallback
        if shutil.which("ffmpeg"):
            return "ffmpeg"
            
        return None

    def get_startup_info(self):
        """
        Returns subprocess configuration for Windows,
        to hide popup console windows (FFmpeg/Whisper).
        """
        if self.is_win:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            return si
        return None

    # ==========================
    # FILE MANAGEMENT
    # ==========================

    def get_temp_folder(self):
        """Returns path to the temporary folder, creating it if needed."""
        try:
            os.makedirs(self.temp_dir, exist_ok=True)
        except Exception as e:
            log_error(f"Failed to create temp dir: {e}")
        return self.temp_dir
        
    def get_saves_folder(self):
        """Returns path to the saves folder, creating it if needed."""
        try:
            os.makedirs(self.saves_dir, exist_ok=True)
        except Exception as e:
            log_error(f"Failed to create saves dir: {e}")
        return self.saves_dir

    def cleanup_temp(self):
        """Removes the temporary directory and its contents."""
        log_info("Cleaning temporary files...")
        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                # Re-create empty dir for next use
                os.makedirs(self.temp_dir, exist_ok=True)
        except Exception as e:
            log_error(f"Cleanup Error: {e}")

    # ==========================
    # DEPENDENCY CHECKS
    # ==========================

    def check_dependencies(self):
        """
        Checks if critical dependencies (FFmpeg, Whisper) are available.
        Returns a list of missing dependency names.
        """
        missing = []
        
        # Check FFmpeg
        if not self.get_ffmpeg_cmd():
            missing.append("FFmpeg")
            
        # Check Whisper (Python module)
        try:
            import whisper
        except ImportError:
            # Often handled by virtualenv, but good to check
            missing.append("openai-whisper (python module)")
            
        return missing

    # ==========================
    # GUI & LOGIC FLAGS (NEW)
    # ==========================

    def needs_manual_model_install(self):
        """
        Determines if the GUI should show the 'Download Model' button.
        
        Logic:
        - Windows: False (Whisper auto-download works reliably in pipeline)
        - Linux/Mac: True (Manual download/verification often safer/needed)
        """
        return not self.is_win