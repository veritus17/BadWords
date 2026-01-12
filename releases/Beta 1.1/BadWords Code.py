#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#Copyright (c) 2026 Szymon Wolarz
#Licensed under the MIT License. See LICENSE file in the project root for full license information.

import sys
import os
import time
import subprocess
import json
import shutil
import re
import threading
import difflib
import zipfile
import logging 
import tkinter as tk
import platform 
import traceback 
import urllib.request # FIX: Dodane do ręcznego pobierania modelu
from tkinter import messagebox, font, ttk, filedialog
import xml.etree.ElementTree as ET

# ==========================================
# STAŁE WYMIARY OKNA KONFIGURACYJNEGO
# ==========================================
CFG_WINDOW_W = 400
CFG_WINDOW_H = 750

# ==========================================
# KONFIGURACJA ŚRODOWISKA (CROSS-PLATFORM)
# ==========================================
APP_NAME = "BadWords"
IS_WIN = platform.system() == "Windows"
HOME_DIR = os.path.expanduser("~")

if IS_WIN:
    INSTALL_DIR = os.path.join(os.environ.get("APPDATA", HOME_DIR), APP_NAME)
else:
    INSTALL_DIR = os.path.join(HOME_DIR, ".local", "share", APP_NAME)

LOG_FILE = os.path.join(INSTALL_DIR, "badwords.log")

if not os.path.exists(INSTALL_DIR):
    try: os.makedirs(INSTALL_DIR, exist_ok=True)
    except: pass

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='w'
)

def log_info(msg):
    logging.info(msg)
    try: print(f"[INFO] {msg}")
    except: pass

def log_error(msg):
    logging.error(msg)
    try: print(f"[ERROR] {msg}")
    except: pass

log_info(f"Uruchomiono BadWords Core. OS: {platform.system()}. Install Dir: {INSTALL_DIR}")

# --- HELPER DLA WINDOWS SUBPROCESS (UKRYWANIE OKNA) ---
def get_startup_info():
    if IS_WIN:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return si
    return None

# ==========================================
# FIX 1: NAPRAWA KONSOLI DAVINCI
# ==========================================
class ResolveStreamProxy:
    def __init__(self, stream, log_func):
        self.stream = stream
        self.log_func = log_func
    def write(self, data):
        try:
            if data.strip(): self.log_func(f"[STDOUT/ERR] {data.strip()}")
            self.stream.write(data)
        except: pass 
    def flush(self):
        try:
            if hasattr(self.stream, 'flush'): self.stream.flush()
        except: pass 
    def __getattr__(self, attr):
        return getattr(self.stream, attr)

if sys.stderr: sys.stderr = ResolveStreamProxy(sys.stderr, logging.error)
if sys.stdout: sys.stdout = ResolveStreamProxy(sys.stdout, logging.info)

# 1. Autodetekcja bibliotek systemowych
try:
    import site
    user_site = site.getusersitepackages()
    if user_site not in sys.path:
        sys.path.insert(0, user_site)
except Exception as e:
    log_error(f"Błąd konfiguracji site-packages: {e}")

# 2. Patch API Resolve (CROSS-PLATFORM)
if IS_WIN:
    RESOLVE_SCRIPT_API = os.path.join(os.environ.get("PROGRAMDATA", "C:\\ProgramData"), 
                                      "Blackmagic Design", "DaVinci Resolve", "Support", 
                                      "Developer", "Scripting", "Modules")
else:
    RESOLVE_SCRIPT_API = "/opt/resolve/Developer/Scripting/Modules/"

if os.path.exists(RESOLVE_SCRIPT_API) and RESOLVE_SCRIPT_API not in sys.path:
    sys.path.append(RESOLVE_SCRIPT_API)

try:
    import DaVinciResolveScript as dvr_script # type: ignore
    log_info("Zaimportowano DaVinciResolveScript pomyślnie.")
except ImportError:
    dvr_script = None
    log_error("Nie udało się zaimportować DaVinciResolveScript.")

# 3. Patch Czcionek
def get_system_font():
    system = platform.system()
    if system == "Windows": return "Segoe UI"
    if system == "Darwin": return "Helvetica Neue"
    try:
        available = font.families()
        for f in ["Noto Sans", "Ubuntu", "Liberation Sans", "DejaVu Sans", "FreeSans", "Arial"]:
            if f in available: return f
    except: pass
    return "TkDefaultFont" 

UI_FONT_NAME = get_system_font()

DOCUMENTS_DIR = os.path.join(HOME_DIR, "Documents")
if not os.path.exists(DOCUMENTS_DIR): DOCUMENTS_DIR = HOME_DIR
TEMP_DIR = os.path.join(DOCUMENTS_DIR, "BadWords_Temp")

FFMPEG_CMD = "ffmpeg" 

# 1.1 INITIAL FILLER WORDS
DEFAULT_BAD_WORDS = ["yyy", "eee", "aaa", "umm", "uh", "ah", "mhm"]
SIMILARITY_THRESHOLD = 0.45 

# --- HELPER: REKURENCYJNE SZUKANIE TIMELINE W MEDIA POOL ---
def find_timeline_item_recursive(folder, timeline_name):
    try:
        for clip in folder.GetClipList():
            if clip.GetClipProperty("Type") == "Timeline" and clip.GetName() == timeline_name:
                return clip
        for sub in folder.GetSubFolderList():
            found = find_timeline_item_recursive(sub, timeline_name)
            if found: return found
    except Exception as e:
        log_error(f"Błąd w find_timeline_item_recursive: {e}")
    return None

# --- READER DOCX / PDF ---
def read_docx_text(path):
    try:
        with zipfile.ZipFile(path) as z:
            xml_content = z.read('word/document.xml')
        tree = ET.fromstring(xml_content)
        text_parts = []
        for elem in tree.iter():
            if elem.tag.endswith('}t'):
                if elem.text: text_parts.append(elem.text)
        return "\n".join(text_parts)
    except Exception as e:
        log_error(f"Błąd odczytu DOCX: {e}")
        return f"[Error reading .docx] {e}"

def read_pdf_text(path):
    try:
        import pypdf  # type: ignore
        reader = pypdf.PdfReader(path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except ImportError:
        return "[Error] pypdf library missing. Please reinstall dependencies."
    except Exception as e:
        log_error(f"Błąd odczytu PDF: {e}")
        return f"[Error reading PDF] {e}"

# --- TŁUMACZENIA / TRANSLATIONS ---
TRANS = {
    "en": {
        "title": "BadWords",
        "header_main": "BadWords Config",
        "sec_whisper": "WHISPER & MODEL",
        "lbl_lang": "Language:",
        "lbl_model": "Model:",
        "lbl_device": "Device:",
        "lbl_fillers": "Filler Words:",
        "btn_edit_fillers": "Edit list...",
        "title_edit_fillers": "Filler Words Editor",
        "lbl_fillers_instr": "Edit filler words (comma separated):",
        "sec_sync": "AUDIO SYNC (FRAMES)",
        "lbl_offset": "Offset (frames):",
        "lbl_pad": "Padding (frames):",
        "lbl_snap": "Snap Max (frames):",
        "lbl_thresh": "Silence Thresh (dB):",
        "chk_reviewer": "Enable Script Reviewer",
        "chk_compound": "Compound Clip Fix (use if timeline has cuts)",
        "hint_compound": "   (Fixes audio sync issues by nesting timeline)",
        "btn_analyze": "ANALYZE",
        "btn_cancel": "Cancel",
        "btn_quit": "Quit",
        "btn_apply": "Apply",
        "btn_generate": "GENERATE",
        "header_rev_script": "Original Script (Yellow = Missing in Audio)",
        "header_rev_trans": "Transcribed Audio (Work Area)",
        "header_rev_tools": "Tools",
        "lbl_mark_color": "Marking Mode:",
        "rb_mark_red": "RED (Cut/Filler)",
        "rb_mark_blue": "BLUE (Repeat/Bad Take)",
        "rb_mark_green": "GREEN (Typo)",
        "rb_mark_white": "ERASER (Clear)",
        "chk_auto_filler": "Mark filler words automatically",
        "chk_auto_del": "Delete red clips automatically (may be imprecise)",
        "btn_import": "Import Script",
        "btn_compare": "Analyze (Compare)",
        "btn_standalone": "Analyze (Standalone)",
        "status_ready": "Ready.",
        "status_nesting": "Nesting Timeline (Compound Fix)...",
        "status_render": "Rendering audio...",
        "status_norm": "Normalizing audio...",
        "status_silence": "Detecting silence...",
        "status_whisper_run": "Running Whisper ({model})...",
        "status_whisper_dl": "Downloading model (First run)...",
        "status_processing": "Processing data...",
        "status_loaded": "Loaded {count} words. Auto-marked: {bad}",
        "status_generating": "Generating timeline...",
        "status_cleanup": "Cleaning temporary files...",
        "status_done": "Done!",
        "status_comparing": "Comparing script with audio...",
        "status_reps": "Analyzing takes & gaps (Context Aware)...",
        "status_standalone": "Running standalone analysis...",
        "status_compared": "Analysis done. Found {diffs} discrepancies.",
        "msg_success": "Timeline generated successfully!",
        "msg_confirm_cancel": "Discard changes?",
        "msg_confirm_apply": "Save changes?",
        "msg_confirm_quit": "Are you sure you want to quit?\nUnsaved progress will be lost.",
        "title_confirm": "Confirm",
        "err_resolve": "DaVinci Resolve API not found.",
        "err_timeline": "Open Timeline before running.",
        "err_render": "Render failed.",
        "err_whisper": "Whisper failed. Ensure 'pipx install openai-whisper' was run.",
        "err_nowords": "No words detected.",
        "err_tl_create": "Failed to create Timeline.",
        "err_nesting": "Could not find current timeline in Media Pool for nesting.",
        "err_num": "Invalid numbers in settings.",
        "err_noscript": "Please paste or import a script first.",
        "ph_script": "Paste script directly here or import using button...",
        "disclaimer": "DISCLAIMER: Transcriptions and timeline markings may be imprecise. This application is in development.",
        "file_types": "Text / Word / PDF",
        "err_dep": "Missing dependency: {dep}. Please install it.",
        "lbl_page": "Page {current}/{total}",
        "btn_prev": "< Prev",
        "btn_next": "Next >",
        "lbl_inaudible_tag": "inaudible",
        "chk_silence_cut": "Detect and cut out silence (may be imprecise)",
        "chk_silence_mark": "Detect and mark silence (tan)", # ZMIANA
        "chk_show_inaudible": "Show inaudible fragments"
    },
    "pl": {
        "title": "BadWords",
        "header_main": "Konfiguracja BadWords",
        "sec_whisper": "WHISPER I MODEL",
        "lbl_lang": "Język:",
        "lbl_model": "Model:",
        "lbl_device": "Urządzenie:",
        "lbl_fillers": "Wypełniacze:",
        "btn_edit_fillers": "Edytuj listę...",
        "title_edit_fillers": "Edytor Słów-Wypełniaczy",
        "lbl_fillers_instr": "Edytuj słowa oddzielone przecinkami:",
        "sec_sync": "SYNCHRONIZACJA (KLATKI)",
        "lbl_offset": "Przesunięcie (klatki):",
        "lbl_pad": "Margines (klatki):",
        "lbl_snap": "Przyciąganie (klatki):",
        "lbl_thresh": "Próg Ciszy (dB):",
        "chk_reviewer": "Włącz Script Reviewer",
        "chk_compound": "Napraw Timeline (użyj jeśli masz pocięty montaż)",
        "hint_compound": "   (Zagnieżdża timeline, naprawia synchronizację)",
        "btn_analyze": "ANALIZUJ",
        "btn_cancel": "Anuluj",
        "btn_quit": "Wyjdź",
        "btn_apply": "Zastosuj",
        "btn_generate": "GENERUJ",
        "header_rev_script": "Oryginalny Scenariusz (Żółty = Brak w Audio)",
        "header_rev_trans": "Transkrypcja Audio (Robocza)",
        "header_rev_tools": "Narzędzia",
        "lbl_mark_color": "Tryb zaznaczania:",
        "rb_mark_red": "CZERWONY (Złe/Wypełniacz)",
        "rb_mark_blue": "NIEBIESKI (Bad Take/Powtórka)",
        "rb_mark_green": "ZIELONY (Literówka)",
        "rb_mark_white": "GUMKA (Usuń)",
        "chk_auto_filler": "Oznaczaj wypełniacze automatycznie",
        "chk_auto_del": "Usuwaj czerwone klipy automatycznie (może być niedokładne)",
        "btn_import": "Importuj Scenariusz",
        "btn_compare": "Analizuj zgodność (Compare)",
        "btn_standalone": "Analizuj (Bez Skryptu)",
        "status_ready": "Gotowy.",
        "status_nesting": "Zagnieżdżanie (Compound Fix)...",
        "status_render": "Renderowanie audio...",
        "status_norm": "Normalizacja audio...",
        "status_silence": "Wykrywanie ciszy...",
        "status_whisper_run": "Uruchamianie Whisper ({model})...",
        "status_whisper_dl": "Brak modelu. Pobieranie {model} (Czekaj cierpliwie)...",
        "status_processing": "Przetwarzanie danych...",
        "status_loaded": "Wczytano {count} słów. Automat zaznaczył: {bad}",
        "status_generating": "Generowanie timeline...",
        "status_cleanup": "Czyszczenie plików tymczasowych...",
        "status_done": "Zakończono!",
        "status_comparing": "Porównywanie tekstu...",
        "status_reps": "Analiza powtórek i wersji (Smart Context)...",
        "status_standalone": "Uruchamianie analizy bez skryptu...",
        "status_compared": "Zakończono analizę. Znaleziono {diffs} rozbieżności.",
        "msg_success": "Timeline wygenerowany pomyślnie!",
        "msg_confirm_cancel": "Porzucić zmiany?",
        "msg_confirm_apply": "Zapisać zmiany?",
        "msg_confirm_quit": "Czy na pewno chcesz wyjść?\nNiezapisany postęp zostanie utracony.",
        "title_confirm": "Potwierdź",
        "err_resolve": "Nie wykryto API DaVinci Resolve.",
        "err_timeline": "Otwórz Timeline przed uruchomieniem.",
        "err_render": "Renderowanie nie powiodło się.",
        "err_whisper": "Błąd Whisper. Sprawdź logi w ~/.local/share/BadWords/badwords.log",
        "err_nowords": "Nie wykryto żadnych słów.",
        "err_tl_create": "Nie udało się utworzyć Timeline.",
        "err_nesting": "Nie znaleziono obecnego timeline w Media Pool (dla nesting).",
        "err_num": "Nieprawidłowe liczby w ustawieniach.",
        "err_noscript": "Najpierw wklej lub zaimportuj scenariusz.",
        "ph_script": "Wklej skrypt bezpośrednio tutaj lub zaimportuj przyciskiem...",
        "disclaimer": "UWAGA: Transkrypcje i zaznaczenia mogą być nieprecyzyjne lub zawierać błędy/braki. Aplikacja w fazie rozwoju.",
        "file_types": "Tekst / Word / PDF",
        "err_dep": "Brak zależności: {dep}. Proszę ją zainstalować.",
        "lbl_page": "Strona {current}/{total}",
        "btn_prev": "< Poprz.",
        "btn_next": "Nast. >",
        "lbl_inaudible_tag": "niezrozumiałe",
        "chk_silence_cut": "Wykryj i WYTNIJ ciszę (może być niedokładne)",
        "chk_silence_mark": "Wykryj i ZAZNACZ ciszę (beżowy)", # ZMIANA
        "chk_show_inaudible": "Pokaż fragmenty niezrozumiałe"
    }
}

# --- KOLORYSTYKA ---
BG_COLOR     = "#36393f"
FOOTER_COLOR = "#2f3136"
FG_COLOR     = "#dcddde"
INPUT_BG     = "#40444b"
INPUT_FG     = "#ffffff"
BTN_BG       = "#5865F2"
BTN_FG       = "#ffffff"
CANCEL_BG    = "#ed4245"
NOTE_COL     = "#72767d"
GEAR_COLOR   = "#b9bbbe"
MENU_BG      = "#2f3136"
MENU_FG      = "#ffffff"
MENU_HOVER   = "#5865F2"
SIDEBAR_BG   = "#292b2f"
SEPARATOR_COL= "#40444b"
CHECKBOX_BG  = "white"
DISCLAIMER_FG= "#72767d"

PROGRESS_HEIGHT     = 24
PROGRESS_FILL_COLOR = "#4752c4"
PROGRESS_TRACK_COLOR= "#40444b"
STATUS_TEXT_COLOR   = "#00b0f4" 

# --- KOLORYSTYKA TEKSTU ---
WORD_NORMAL_FG = "#dcddde"
WORD_BAD_BG    = "#ed4245"
WORD_BAD_FG    = "#ffffff"
WORD_REPEAT_BG = "#2980b9"
WORD_REPEAT_FG = "#ffffff"
WORD_TYPO_BG   = "#27ae60"
WORD_TYPO_FG   = "#ffffff"
WORD_HOVER_BG  = "#4f545c"
WORD_MISSING_BG = "#f1c40f"
WORD_MISSING_FG = "#000000"

# GUI: Original Brown
WORD_INAUDIBLE_BG = "#8B4513" 
WORD_INAUDIBLE_FG = "#ffffff"

# --- CUSTOM MENU ---
class FlatMenu(tk.Toplevel):
    def __init__(self, parent, options, callback, x_anchor, y_anchor):
        super().__init__(parent)
        self.overrideredirect(True)
        self.configure(bg=MENU_BG)
        self.callback = callback
        
        self.ui_font = (UI_FONT_NAME, 10)
        
        container = tk.Frame(self, bg=MENU_BG, highlightthickness=1, highlightbackground="black")
        container.pack(fill="both", expand=True)
        for label, val in options:
            lbl = tk.Label(container, text=f"  {label}  ", bg=MENU_BG, fg=MENU_FG, 
                           font=self.ui_font, anchor="w", padx=15, pady=8, cursor="hand2")
            lbl.pack(fill="x")
            lbl.bind("<Enter>", lambda e, l=lbl: l.configure(bg=MENU_HOVER))
            lbl.bind("<Leave>", lambda e, l=lbl: l.configure(bg=MENU_BG))
            lbl.bind("<Button-1>", lambda e, v=val: self.on_click(v))
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        final_x = x_anchor - w
        final_y = y_anchor
        self.geometry(f"{w}x{h}+{final_x}+{final_y}")
        self.bind("<FocusOut>", lambda e: self.destroy())
        self.bind("<Escape>", lambda e: self.destroy())
        self.focus_set()
    def on_click(self, val):
        self.callback(val)
        self.destroy()

# --- KLASA GŁÓWNA ---
class BadWordsApp:
    def __init__(self, root):
        self.root = root
        self.lang = "en"
        self.menu_window = None 
        self.root.title(self.txt("title"))
        
        # Font init
        self.font_norm = (UI_FONT_NAME, 10)
        self.font_bold = (UI_FONT_NAME, 10, "bold")
        self.font_head = (UI_FONT_NAME, 16, "bold")
        self.font_small = (UI_FONT_NAME, 8)
        self.font_small_bold = (UI_FONT_NAME, 8, "bold")
        
        self.resolve = self.get_resolve()
        if not self.resolve:
            try: self.resolve = resolve # type: ignore
            except NameError: self.resolve = None
        
        if self.resolve:
            log_info("Połączono z API DaVinci Resolve.")
        else:
            log_error("Nie wykryto obiektu 'resolve'.")

        if shutil.which(FFMPEG_CMD) is None:
            log_error("Ostrzeżenie: Brak ffmpeg w PATH.")

        # UŻYCIE STAŁYCH WYMIARÓW OKNA
        self.center_window_force(CFG_WINDOW_W, CFG_WINDOW_H)
        self.root.configure(bg=BG_COLOR)
        
        self.root.bind("<Button-1>", self.close_menu_if_open)

        if self.resolve:
            self.project = self.resolve.GetProjectManager().GetCurrentProject()
            self.timeline = self.project.GetCurrentTimeline()
            if self.timeline:
                self.fps = float(self.timeline.GetSetting("timelineFrameRate"))
            else:
                self.fps = 24.0 
        else:
            self.project = None
            self.timeline = None
            self.fps = 24.0
        
        self.temp_nested_timeline = None
        self.generation_source_item = None
        
        # ADDED: Track last analysis mode
        self.last_analysis_mode = "standalone"

        self.filler_words = list(DEFAULT_BAD_WORDS)
        
        if not self.timeline and self.resolve:
            messagebox.showerror("Error", self.txt("err_timeline"))
            self.root.destroy()
            return
            
        self.words_data = []
        self.segments_data = [] 
        
        self.page_size = 25  
        self.current_page = 0
        self.total_pages = 1
        self.lbl_page_info = None
        
        self.separator_frames = []
        
        self.current_status_text = self.txt("status_ready")
        self.current_progress_val = 0.0
        
        self.var_lang = tk.StringVar(value="English")
        self.var_model = tk.StringVar(value="medium (Best for fillers)")
        self.var_device = tk.StringVar(value="Auto")
        
        self.var_threshold = tk.StringVar(value="-40")
        self.var_silence_dur = tk.StringVar(value="0.1")
        self.var_snap_margin = tk.StringVar(value="12") 
        self.var_offset = tk.StringVar(value="-2")      
        self.var_pad = tk.StringVar(value="2")          
        
        self.var_enable_reviewer = tk.BooleanVar(value=True)
        self.var_compound = tk.BooleanVar(value=False)

        # Silence vars
        self.var_silence_cut = tk.BooleanVar(value=False)
        self.var_silence_mark = tk.BooleanVar(value=False)
        self.var_show_inaudible = tk.BooleanVar(value=True)

        self.var_mark_tool = tk.StringVar(value="bad")
        self.var_auto_filler = tk.BooleanVar(value=True)
        self.var_auto_del = tk.BooleanVar(value=False)
        
        self.is_dragging = False
        self.drag_mode = True 
        self.last_dragged_id = -1
        self.current_frame = None
        self.current_stage_name = "config"
        
        self.status_canvas = None
        self.status_rect_id = None
        self.status_text_id = None

        self.setup_styles()
        self.show_config_stage()

    def txt(self, key, **kwargs):
        text = TRANS.get(self.lang, TRANS["en"]).get(key, key)
        if kwargs: return text.format(**kwargs)
        return text

    def set_language(self, lang_code):
        if self.lang == lang_code: return
        self.lang = lang_code
        self.root.title(self.txt("title"))
        if "Ready" in self.current_status_text or "Gotowy" in self.current_status_text:
             self.set_status(self.txt("status_ready"))
        if self.current_stage_name == "config": self.show_config_stage()
        elif self.current_stage_name == "reviewer": self.show_reviewer_stage()

    def close_menu_if_open(self, event=None):
        if self.menu_window and self.menu_window.winfo_exists():
            self.menu_window.destroy()
            self.menu_window = None

    def get_resolve(self):
        if dvr_script:
            return dvr_script.scriptapp("Resolve")
        try: return resolve # type: ignore
        except NameError: return None

    def center_window_force(self, w, h):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        try:
            self.root.warp_pointer(screen_w // 2, screen_h // 2)
            self.root.update_idletasks()
        except: pass
        mouse_x = self.root.winfo_pointerx()
        mouse_y = self.root.winfo_pointery()
        if mouse_x < 0: mouse_x = screen_w // 2
        if mouse_y < 0: mouse_y = screen_h // 2
        
        x = int(mouse_x - (w / 2))
        y = int(mouse_y - (h / 2))
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TCombobox", fieldbackground=INPUT_BG, background=BG_COLOR, foreground=INPUT_FG, arrowcolor="white", bordercolor=BG_COLOR, darkcolor=INPUT_BG, lightcolor=INPUT_BG, relief="flat")
        style.map("TCombobox", fieldbackground=[("readonly", INPUT_BG)], selectbackground=[("readonly", INPUT_BG)], selectforeground=[("readonly", INPUT_FG)], background=[("readonly", INPUT_BG)])
        
        style.configure("TCheckbutton", background=BG_COLOR, foreground=FG_COLOR, font=self.font_norm, 
                       indicatorbackground=CHECKBOX_BG, indicatorforeground="black", borderwidth=0, focuscolor=BG_COLOR)
        style.map("TCheckbutton", background=[('active', BG_COLOR)], foreground=[('active', "white")], 
                 indicatorbackground=[('selected', CHECKBOX_BG), ('active', CHECKBOX_BG)])
        
        style.configure("Sidebar.TCheckbutton", background=SIDEBAR_BG, foreground=FG_COLOR, font=self.font_norm, 
                       indicatorbackground=CHECKBOX_BG, indicatorforeground="black", borderwidth=0, focuscolor=SIDEBAR_BG)
        style.map("Sidebar.TCheckbutton", background=[('active', SIDEBAR_BG)], 
                 indicatorbackground=[('selected', CHECKBOX_BG), ('active', CHECKBOX_BG)])
        
        self.root.option_add('*TCombobox*Listbox.background', "#2f3136")
        self.root.option_add('*TCombobox*Listbox.foreground', 'white')
        self.root.option_add('*TCombobox*Listbox.selectBackground', BTN_BG)
        self.root.option_add('*TCombobox*Listbox.selectForeground', 'white')
        self.root.option_add('*TCombobox*Listbox.font', self.font_norm)

    def clear_window(self):
        if self.current_frame: self.current_frame.destroy()
        for widget in self.root.winfo_children(): widget.destroy()

    def cleanup_and_exit(self):
        self.set_status(self.txt("status_cleanup"))
        try:
            if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
        except Exception as e: 
            log_error(f"Cleanup Error: {e}")
        self.root.destroy()

    # --- STATUS BAR LOGIC ---
    def set_status(self, text):
        self.current_status_text = text
        self.root.after(0, self._update_status_ui)

    def set_progress(self, value):
        self.current_progress_val = value
        self.root.after(0, self._update_status_ui)

    def _update_status_ui(self):
        if self.status_canvas: 
            try:
                self.status_canvas.itemconfig(self.status_text_id, text=self.current_status_text)
                canvas_width = self.status_canvas.winfo_width()
                if canvas_width < 10: canvas_width = 400 
                new_width = (self.current_progress_val / 100.0) * canvas_width
                
                if self.current_progress_val <= 0:
                    self.status_canvas.configure(bg=BG_COLOR)
                    self.status_canvas.itemconfig(self.status_rect_id, fill=BG_COLOR, width=0)
                else:
                    self.status_canvas.configure(bg=PROGRESS_TRACK_COLOR)
                    self.status_canvas.coords(self.status_rect_id, 0, 0, new_width, PROGRESS_HEIGHT)
                    self.status_canvas.itemconfig(self.status_rect_id, fill=PROGRESS_FILL_COLOR, width=0)
            except: pass
        self._update_sidebar_status(force=True)

    def _update_sidebar_status(self, force=False):
        if not hasattr(self, 'sidebar_status_canvas') or not self.sidebar_status_canvas.winfo_exists(): return
        try:
            self.sidebar_status_canvas.itemconfig(self.sb_text_id, text=self.current_status_text)
            w = self.sidebar_status_canvas.winfo_width()
            if w < 10: w = 260
            new_w = (self.current_progress_val / 100.0) * w
            
            if self.current_progress_val <= 0:
                self.sidebar_status_canvas.configure(bg=SIDEBAR_BG)
                self.sidebar_status_canvas.itemconfig(self.sb_rect_id, fill=SIDEBAR_BG, width=0)
            else:
                self.sidebar_status_canvas.configure(bg=PROGRESS_TRACK_COLOR)
                self.sidebar_status_canvas.coords(self.sb_rect_id, 0, 0, new_w, 24)
                self.sidebar_status_canvas.itemconfig(self.sb_rect_id, fill=PROGRESS_FILL_COLOR, width=0)
        except: pass

    # --- UI BUILDING BLOCKS ---
    def build_header(self, parent, title_key, show_gear=True):
        header_frame = tk.Frame(parent, bg=BG_COLOR)
        header_frame.pack(fill="x", pady=(0, 15))
        tk.Label(header_frame, text=self.txt(title_key), font=self.font_head, 
                 bg=BG_COLOR, fg="white").pack(side="left", anchor="w")
        if show_gear: self._add_gear_button(header_frame, bg_color=BG_COLOR)

    def _add_gear_button(self, parent, bg_color):
        settings_btn = tk.Label(parent, text="⚙", font=(UI_FONT_NAME, 20), 
                                bg=bg_color, fg=GEAR_COLOR, cursor="hand2", bd=0)
        settings_btn.pack(side="right", anchor="center")
        def show_flat_menu(event):
            if self.menu_window and self.menu_window.winfo_exists():
                self.menu_window.destroy(); return
            x = settings_btn.winfo_rootx() - 10
            y = settings_btn.winfo_rooty()
            options = [("English", "en"), ("Polski", "pl")]
            self.menu_window = FlatMenu(self.root, options, self.set_language, x, y)
        settings_btn.bind("<Button-1>", lambda e: (show_flat_menu(e), "break")[1])

    # ==========================
    # STAGE 1: CONFIGURATION
    # ==========================
    def show_config_stage(self):
        self.current_stage_name = "config"
        self.clear_window()
        main_frame = tk.Frame(self.root, bg=BG_COLOR, padx=20, pady=20)
        main_frame.pack(fill="both", expand=True)
        self.current_frame = main_frame

        self.build_header(main_frame, "header_main")

        def create_input_row(parent, label, var, values=None, hint=""):
            container = tk.Frame(parent, bg=BG_COLOR)
            container.pack(fill="x", pady=(0, 8))
            lbl_fr = tk.Frame(container, bg=BG_COLOR)
            lbl_fr.pack(fill="x")
            tk.Label(lbl_fr, text=label, bg=BG_COLOR, fg=FG_COLOR, font=self.font_norm).pack(side="left")
            if hint: tk.Label(lbl_fr, text=f" {hint}", bg=BG_COLOR, fg=NOTE_COL, font=self.font_small).pack(side="left")
            if values:
                cb = ttk.Combobox(container, textvariable=var, values=values, state="readonly", font=self.font_norm)
                cb.pack(fill="x", ipady=3, pady=(2,0))
                cb.bind("<<ComboboxSelected>>", lambda e: self.close_menu_if_open())
            else:
                ent = tk.Entry(container, textvariable=var, bg=INPUT_BG, fg=INPUT_FG, 
                               relief="flat", bd=0, highlightthickness=0, insertbackground="white", font=self.font_norm)
                ent.pack(fill="x", ipady=4, pady=(2,0))
                ent.bind("<Button-1>", lambda e: self.close_menu_if_open())

        tk.Label(main_frame, text=self.txt("sec_whisper"), bg=BG_COLOR, fg=NOTE_COL, font=self.font_small_bold, anchor="w").pack(fill="x", pady=(0, 5))
        create_input_row(main_frame, self.txt("lbl_lang"), self.var_lang, ["English", "Polish", "Auto"])
        create_input_row(main_frame, self.txt("lbl_model"), self.var_model, ["tiny (Fast, no fillers)", "base (Fast, no fillers)", "small (Good, no fillers)", "medium (Best for fillers)", "large (Accurate, slow)"])
        create_input_row(main_frame, self.txt("lbl_device"), self.var_device, ["Auto", "GPU (cuda/rocm)", "CPU"], hint="(AMD users: select GPU)")

        fill_container = tk.Frame(main_frame, bg=BG_COLOR)
        fill_container.pack(fill="x", pady=(0, 8))
        
        fill_lbl_fr = tk.Frame(fill_container, bg=BG_COLOR)
        fill_lbl_fr.pack(fill="x")
        tk.Label(fill_lbl_fr, text=self.txt("lbl_fillers"), bg=BG_COLOR, fg=FG_COLOR, font=self.font_norm).pack(side="left")
        
        btn_fillers = tk.Button(fill_container, text=self.txt("btn_edit_fillers"), command=self.open_filler_editor,
                  bg=INPUT_BG, fg=INPUT_FG, activebackground=INPUT_BG, activeforeground="white",
                  font=self.font_norm, relief="flat", bd=0, highlightthickness=0, cursor="hand2", anchor="w", padx=5)
        btn_fillers.pack(fill="x", ipady=1, pady=(2,0))

        tk.Frame(main_frame, height=1, bg=INPUT_BG).pack(fill="x", pady=10)

        tk.Label(main_frame, text=self.txt("sec_sync"), bg=BG_COLOR, fg=NOTE_COL, font=self.font_small_bold, anchor="w").pack(fill="x", pady=(0, 5))
        grid_fr = tk.Frame(main_frame, bg=BG_COLOR)
        grid_fr.pack(fill="x", pady=0)
        col1 = tk.Frame(grid_fr, bg=BG_COLOR); col1.pack(side="left", fill="both", expand=True, padx=(0, 5))
        create_input_row(col1, self.txt("lbl_offset"), self.var_offset, hint="(-2)")
        create_input_row(col1, self.txt("lbl_pad"), self.var_pad, hint="(2)")
        col2 = tk.Frame(grid_fr, bg=BG_COLOR); col2.pack(side="left", fill="both", expand=True, padx=(5, 0))
        create_input_row(col2, self.txt("lbl_snap"), self.var_snap_margin, hint="(12)")
        create_input_row(col2, self.txt("lbl_thresh"), self.var_threshold, hint="(-40)")

        # CHECKBOXES
        chk_frame = tk.Frame(main_frame, bg=BG_COLOR)
        chk_frame.pack(fill="x", pady=(10, 5))
        
        ttk.Checkbutton(chk_frame, text=self.txt("chk_reviewer"), variable=self.var_enable_reviewer, style="TCheckbutton").pack(anchor="w", pady=(0,5))
        
        comp_row = tk.Frame(chk_frame, bg=BG_COLOR)
        comp_row.pack(anchor="w", fill="x")
        ttk.Checkbutton(comp_row, text=self.txt("chk_compound"), variable=self.var_compound, style="TCheckbutton").pack(side="left")
        
        hint_comp_row = tk.Frame(chk_frame, bg=BG_COLOR)
        hint_comp_row.pack(anchor="w", fill="x")
        tk.Label(hint_comp_row, text=self.txt("hint_compound"), bg=BG_COLOR, fg=NOTE_COL, font=self.font_small).pack(side="left")

        tk.Frame(main_frame, bg=BG_COLOR).pack(expand=True, fill="both")
        
        status_container = tk.Frame(main_frame, bg=BG_COLOR, height=PROGRESS_HEIGHT)
        status_container.pack(fill="x", side="bottom", pady=(0, 10))
        status_container.pack_propagate(False)
        self.status_canvas = tk.Canvas(status_container, bg=BG_COLOR, height=PROGRESS_HEIGHT, highlightthickness=0, relief="flat")
        self.status_canvas.pack(fill="both", expand=True)
        self.status_rect_id = self.status_canvas.create_rectangle(0, 0, 0, PROGRESS_HEIGHT, fill=BG_COLOR, width=0)
        self.status_text_id = self.status_canvas.create_text(0, PROGRESS_HEIGHT/2, text=self.current_status_text, fill=STATUS_TEXT_COLOR, font=(UI_FONT_NAME, 9))
        self.status_canvas.bind("<Configure>", lambda e: (self.status_canvas.coords(self.status_text_id, e.width/2, PROGRESS_HEIGHT/2), self._update_status_ui()))

        btn_frame = tk.Frame(self.root, bg=FOOTER_COLOR, pady=20)
        btn_frame.pack(side="bottom", fill="x")
        
        def run_analyze_click():
            self.close_menu_if_open()
            self.start_analysis_thread()
            
        self.btn_analyze = tk.Button(btn_frame, text=self.txt("btn_analyze"), command=run_analyze_click,
                  bg=BTN_BG, fg=BTN_FG, activebackground="#4752c4", activeforeground="white",
                  font=self.font_bold, relief="flat", bd=0, highlightthickness=0, padx=20, pady=5, cursor="hand2")
        self.btn_analyze.pack(side="right", padx=20)
        
        # --- ZMIANA: PRZYCISK QUIT Z DOUBLE CHECK ---
        def on_quit_click():
            if messagebox.askyesno(self.txt("title_confirm"), self.txt("msg_confirm_quit"), parent=self.root):
                self.root.destroy()

        tk.Button(btn_frame, text=self.txt("btn_quit"), command=on_quit_click,
                  bg=CANCEL_BG, fg="white", activebackground="#c03537", activeforeground="white",
                  font=self.font_bold, relief="flat", bd=0, highlightthickness=0, padx=20, pady=5, cursor="hand2").pack(side="right", padx=0)
        
        self._update_status_ui()

    def open_filler_editor(self):
        editor = tk.Toplevel(self.root)
        editor.configure(bg=BG_COLOR)
        editor.title(self.txt("title_edit_fillers"))
        
        w, h = 325, 600
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (w // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (h // 2)
        editor.geometry(f"{w}x{h}+{x}+{y}")
        editor.transient(self.root)
        editor.grab_set()
        
        lbl = tk.Label(editor, text=self.txt("lbl_fillers_instr"), bg=BG_COLOR, fg=FG_COLOR, font=(UI_FONT_NAME, 9))
        lbl.pack(pady=10, padx=10, anchor="w")
        
        txt_frame = tk.Frame(editor, bg=INPUT_BG)
        txt_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        text_widget = tk.Text(txt_frame, bg=INPUT_BG, fg="white", font=self.font_norm, bd=0, highlightthickness=0)
        text_widget.pack(fill="both", expand=True, padx=5, pady=5)
        
        current_text = ", ".join(self.filler_words)
        text_widget.insert("1.0", current_text)
        
        btn_frame = tk.Frame(editor, bg=BG_COLOR)
        btn_frame.pack(fill="x", pady=15, padx=10)
        
        def on_apply():
            if messagebox.askyesno(self.txt("title_confirm"), self.txt("msg_confirm_apply"), parent=editor):
                raw = text_widget.get("1.0", tk.END).strip()
                new_list = [w.strip() for w in raw.split(',') if w.strip()]
                self.filler_words = new_list
                editor.destroy()
            
        def on_cancel():
            if messagebox.askyesno(self.txt("title_confirm"), self.txt("msg_confirm_cancel"), parent=editor):
                editor.destroy()
        
        tk.Button(btn_frame, text=self.txt("btn_apply"), command=on_apply, 
                  bg=BTN_BG, fg="white", font=(UI_FONT_NAME, 9, "bold"), relief="flat", padx=15, cursor="hand2").pack(side="right", padx=5)
        tk.Button(btn_frame, text=self.txt("btn_cancel"), command=on_cancel, 
                  bg=CANCEL_BG, fg="white", font=(UI_FONT_NAME, 9, "bold"), relief="flat", padx=15, cursor="hand2").pack(side="right")

    # ==========================
    # STAGE 2: UNIFIED REVIEWER
    # ==========================
    def show_reviewer_stage(self):
        self.current_stage_name = "reviewer"
        self.root.after(0, self._build_reviewer_ui)

    def _build_reviewer_ui(self):
        self.clear_window()
        w, h = 1450, 850
        self.center_window_force(w, h)
        
        self.current_frame = tk.Frame(self.root, bg=BG_COLOR)
        self.current_frame.pack(fill="both", expand=True)

        content_area = tk.Frame(self.current_frame, bg=BG_COLOR)
        content_area.pack(fill="both", expand=True, padx=10, pady=10)

        # Right Col (Fixed Sidebar)
        frame_sidebar = tk.Frame(content_area, bg=SIDEBAR_BG, width=260) 
        frame_sidebar.pack(side="right", fill="y", padx=(5,0))
        frame_sidebar.pack_propagate(False)

        # Content (Script + Trans)
        frame_texts = tk.Frame(content_area, bg=BG_COLOR)
        frame_texts.pack(side="left", fill="both", expand=True)
        
        is_reviewer_mode = self.var_enable_reviewer.get()
        
        if is_reviewer_mode:
            frame_script = tk.Frame(frame_texts, bg=BG_COLOR)
            frame_script.pack(side="left", fill="y", padx=(0,5))
            tk.Label(frame_script, text=self.txt("header_rev_script"), bg=BG_COLOR, fg=NOTE_COL, font=self.font_bold).pack(anchor="w", pady=(0,5))
            self.script_area = tk.Text(frame_script, bg=INPUT_BG, fg=FG_COLOR, font=(UI_FONT_NAME, 11), width=50, wrap="word", relief="flat", padx=10, pady=10, bd=0, highlightthickness=0)
            self.script_area.pack(fill="both", expand=True)
            self.script_area.tag_configure("missing", background=WORD_MISSING_BG, foreground=WORD_MISSING_FG)
            self._setup_placeholder(self.script_area, self.txt("ph_script"))
        else:
            self.script_area = None

        frame_trans = tk.Frame(frame_texts, bg=BG_COLOR)
        frame_trans.pack(side="left", fill="both", expand=True, padx=(5,0))
        tk.Label(frame_trans, text=self.txt("header_rev_trans"), bg=BG_COLOR, fg=NOTE_COL, font=self.font_bold).pack(anchor="w", pady=(0,5))
        
        self.pagination_frame = tk.Frame(frame_trans, bg=BG_COLOR)
        self.pagination_frame.pack(side="bottom", fill="x", pady=5)
        
        self.btn_prev_page = tk.Button(self.pagination_frame, text=self.txt("btn_prev"), command=self.prev_page,
                                       bg=INPUT_BG, fg=FG_COLOR, relief="flat", bd=0, font=self.font_small, cursor="hand2")
        self.btn_prev_page.pack(side="left")
        
        self.lbl_page_info = tk.Label(self.pagination_frame, text=self.txt("lbl_page", current=1, total=1), 
                                      bg=BG_COLOR, fg=NOTE_COL, font=self.font_small)
        self.lbl_page_info.pack(side="left", padx=10)
        
        self.btn_next_page = tk.Button(self.pagination_frame, text=self.txt("btn_next"), command=self.next_page,
                                       bg=INPUT_BG, fg=FG_COLOR, relief="flat", bd=0, font=self.font_small, cursor="hand2")
        self.btn_next_page.pack(side="left")
        
        text_scroll = tk.Scrollbar(frame_trans)
        text_scroll.pack(side="right", fill="y")
        self.text_area = tk.Text(frame_trans, bg=INPUT_BG, fg=WORD_NORMAL_FG, insertbackground="white",
                                 relief="flat", bd=0, highlightthickness=0, font=(UI_FONT_NAME, 12), wrap="word", 
                                 padx=15, pady=15, cursor="arrow", yscrollcommand=text_scroll.set,
                                 selectbackground=INPUT_BG, selectforeground=WORD_NORMAL_FG, inactiveselectbackground=INPUT_BG)
        self.text_area.pack(fill="both", expand=True)
        text_scroll.config(command=self.text_area.yview)
        self._configure_text_tags()
        self.text_area.configure(state="disabled")

        # Sidebar Content
        sb_header = tk.Frame(frame_sidebar, bg=SIDEBAR_BG)
        sb_header.pack(fill="x", padx=15, pady=15)
        tk.Label(sb_header, text=self.txt("header_rev_tools"), bg=SIDEBAR_BG, fg="white", font=(UI_FONT_NAME, 12, "bold")).pack(side="left")
        self._add_gear_button(sb_header, bg_color=SIDEBAR_BG)

        # 1. Kolory
        tk.Label(frame_sidebar, text=self.txt("lbl_mark_color"), bg=SIDEBAR_BG, fg=NOTE_COL, font=(UI_FONT_NAME, 9)).pack(anchor="w", padx=15, pady=(5,5))
        
        style = ttk.Style()
        style.configure("TRadiobutton", background=SIDEBAR_BG, foreground="white", font=self.font_norm)
        
        def add_tool_rb(text_key, val, color, white_mode=False):
             tk.Radiobutton(frame_sidebar, text=self.txt(text_key), variable=self.var_mark_tool, value=val,
                       bg=SIDEBAR_BG, fg=color, selectcolor="black" if not white_mode else "gray", 
                       activebackground=SIDEBAR_BG, activeforeground=color,
                       font=self.font_bold, indicatoron=1, cursor="hand2", bd=0, highlightthickness=0).pack(anchor="w", padx=10, pady=2)

        add_tool_rb("rb_mark_red", "bad", WORD_BAD_BG)
        add_tool_rb("rb_mark_blue", "repeat", WORD_REPEAT_BG)
        add_tool_rb("rb_mark_green", "typo", WORD_TYPO_BG)
        add_tool_rb("rb_mark_white", "eraser", "#cccccc")

        tk.Frame(frame_sidebar, height=1, bg=SEPARATOR_COL).pack(fill="x", padx=10, pady=15)

        # 2. Przyciski Import / Analiza
        if is_reviewer_mode:
            def import_script_action():
                path = filedialog.askopenfilename(parent=self.root, filetypes=[(self.txt("file_types"), "*.txt *.docx *.pdf")])
                if path:
                    text_content = ""
                    if path.lower().endswith(".docx"):
                        text_content = read_docx_text(path)
                    elif path.lower().endswith(".pdf"):
                        text_content = read_pdf_text(path)
                    else:
                        try:
                            with open(path, 'r', encoding='utf-8') as f: text_content = f.read()
                        except Exception as e: text_content = str(e)
                    
                    self.script_area.delete("1.0", tk.END)
                    self.script_area.insert("1.0", text_content)
                    self.script_area.configure(fg=FG_COLOR) 

            tk.Button(frame_sidebar, text=self.txt("btn_import"), bg=INPUT_BG, fg="white", font=(UI_FONT_NAME, 9),
                      relief="flat", bd=0, highlightthickness=0, pady=5, cursor="hand2", command=import_script_action).pack(fill="x", padx=15, pady=5)
            
            def run_compare_click():
                self.close_menu_if_open()
                self.last_analysis_mode = "compare" # Track mode
                self.start_comparison_thread()

            tk.Button(frame_sidebar, text=self.txt("btn_compare"), bg=BTN_BG, fg="white", font=(UI_FONT_NAME, 9, "bold"),
                      relief="flat", bd=0, highlightthickness=0, pady=5, cursor="hand2", command=run_compare_click).pack(fill="x", padx=15, pady=5)

        def run_standalone_click():
            self.close_menu_if_open()
            self.last_analysis_mode = "standalone" # Track mode
            self.start_standalone_thread()

        lbl_standalone = self.txt("btn_analyze") if not is_reviewer_mode else self.txt("btn_standalone")
        
        tk.Button(frame_sidebar, text=lbl_standalone, bg=BTN_BG, fg="white", font=(UI_FONT_NAME, 9, "bold"),
                  relief="flat", bd=0, highlightthickness=0, pady=5, cursor="hand2", command=run_standalone_click).pack(fill="x", padx=15, pady=5)

        tk.Frame(frame_sidebar, height=1, bg=SEPARATOR_COL).pack(fill="x", padx=10, pady=15)

        # 3. Checkboxy Auto & Ciszy (Zorganizowane)
        def create_wrapped_checkbox(var, text_key, cmd=None):
            row = tk.Frame(frame_sidebar, bg=SIDEBAR_BG)
            row.pack(fill="x", padx=15, pady=5)
            cb = ttk.Checkbutton(row, variable=var, style="Sidebar.TCheckbutton", command=cmd)
            cb.pack(side="left", anchor="n")
            lbl = tk.Label(row, text=self.txt(text_key), bg=SIDEBAR_BG, fg=FG_COLOR, font=(UI_FONT_NAME, 9), justify="left", wraplength=200, anchor="w")
            lbl.pack(side="left", fill="x", expand=True, padx=(5,0))

        create_wrapped_checkbox(self.var_auto_filler, "chk_auto_filler", cmd=self.toggle_auto_fillers)
        create_wrapped_checkbox(self.var_auto_del, "chk_auto_del")

        def toggle_cut():
             if self.var_silence_cut.get(): self.var_silence_mark.set(False)
        def toggle_mark():
             if self.var_silence_mark.get(): self.var_silence_cut.set(False)

        create_wrapped_checkbox(self.var_silence_cut, "chk_silence_cut", cmd=toggle_cut)
        create_wrapped_checkbox(self.var_silence_mark, "chk_silence_mark", cmd=toggle_mark)
        
        # ZMIANA: Live toggle callback dla show_inaudible (RE-RUN ANALYSIS)
        def toggle_inaudible_live():
            # Refresh analysis based on last mode
            if self.last_analysis_mode == "compare" and self.script_area:
                 # Check if script area has text
                 if self.script_area.get("1.0", "end-1c").strip() != self.txt("ph_script"):
                      self.start_comparison_thread()
                 else:
                      self.start_standalone_thread()
            else:
                 self.start_standalone_thread()
            
        create_wrapped_checkbox(self.var_show_inaudible, "chk_show_inaudible", cmd=toggle_inaudible_live)

        tk.Frame(frame_sidebar, height=1, bg=SEPARATOR_COL).pack(fill="x", padx=10, pady=15)

        # 5. Cancel / Generate na dole
        tk.Frame(frame_sidebar, bg=SIDEBAR_BG).pack(fill="y", expand=True) 
        sb_status_frame = tk.Frame(frame_sidebar, bg=SIDEBAR_BG, height=24)
        sb_status_frame.pack(fill="x", padx=5, pady=(0, 10))
        sb_status_frame.pack_propagate(False)
        self.sidebar_status_canvas = tk.Canvas(sb_status_frame, bg=SIDEBAR_BG, height=24, highlightthickness=0, relief="flat")
        self.sidebar_status_canvas.pack(fill="both", expand=True)
        self.sb_rect_id = self.sidebar_status_canvas.create_rectangle(0, 0, 0, 24, fill=SIDEBAR_BG, width=0)
        self.sb_text_id = self.sidebar_status_canvas.create_text(0, 12, text=self.current_status_text, fill=STATUS_TEXT_COLOR, font=(UI_FONT_NAME, 8))
        self.sidebar_status_canvas.bind("<Configure>", lambda e: (self.sidebar_status_canvas.coords(self.sb_text_id, e.width/2, 12), self._update_sidebar_status()))

        def run_generate_click():
            self.close_menu_if_open()
            threading.Thread(target=self.generate_timeline, daemon=True).start()

        tk.Button(frame_sidebar, text=self.txt("btn_generate"), command=run_generate_click,
                  bg=BTN_BG, fg=BTN_FG, font=self.font_bold, relief="flat", bd=0, highlightthickness=0, pady=8, cursor="hand2").pack(fill="x", padx=15, pady=(0,10), side="bottom")
        
        # --- ZMIANA: PRZYCISK QUIT Z DOUBLE CHECK ---
        def on_quit_click():
            if messagebox.askyesno(self.txt("title_confirm"), self.txt("msg_confirm_quit"), parent=self.root):
                self.root.destroy()

        tk.Button(frame_sidebar, text=self.txt("btn_quit"), command=on_quit_click,
                  bg=CANCEL_BG, fg="white", font=self.font_bold, relief="flat", bd=0, highlightthickness=0, pady=8, cursor="hand2").pack(fill="x", padx=15, pady=(0,10), side="bottom")

        tk.Label(self.current_frame, text=self.txt("disclaimer"), bg=BG_COLOR, fg=DISCLAIMER_FG, font=(UI_FONT_NAME, 7), pady=5).pack(side="bottom", fill="x")

        self.populate_text_area()
        self._update_sidebar_status()

    def _setup_placeholder(self, text_widget, placeholder):
        text_widget.insert("1.0", placeholder)
        text_widget.configure(fg=NOTE_COL)
        
        def on_focus_in(event):
            current_text = text_widget.get("1.0", "end-1c")
            if current_text == placeholder:
                text_widget.delete("1.0", tk.END)
                text_widget.configure(fg=FG_COLOR)
        
        def on_focus_out(event):
            current_text = text_widget.get("1.0", "end-1c")
            if not current_text.strip():
                text_widget.insert("1.0", placeholder)
                text_widget.configure(fg=NOTE_COL)
                
        text_widget.bind("<FocusIn>", on_focus_in)
        text_widget.bind("<FocusOut>", on_focus_out)

    def toggle_auto_fillers(self):
        enabled = self.var_auto_filler.get()
        dynamic_bad = [w.lower().strip() for w in self.filler_words]
        
        for w in self.words_data:
            if w.get('is_inaudible') or w.get('type') == 'silence': continue
            
            txt_clean = re.sub(r'[^\w\s\'-]', '', w['text']).strip()
            if txt_clean.lower() in dynamic_bad:
                if enabled:
                    if w.get('status') is None or w.get('status') == 'bad':
                        w['status'] = 'bad'
                        w['selected'] = True
                else:
                    if w.get('status') == 'bad':
                        w['status'] = None
                        w['selected'] = False
        self.populate_text_area()

    def start_standalone_thread(self):
        self.set_status(self.txt("status_standalone"))
        self.set_progress(10)
        threading.Thread(target=self.run_standalone_logic, daemon=True).start()

    def run_standalone_logic(self):
        if self.var_auto_filler.get():
            self.toggle_auto_fillers()
        
        self.set_progress(40)
        self.analyze_structure_pure_audio(update_ui=False)
        self.absorb_inaudible_into_repeats() # NEW: Context Aware coloring
        self.set_progress(100)
        self.root.after(0, lambda: self.populate_text_area())
        self.set_status(self.txt("status_done"))
        self.root.after(2000, lambda: self.set_progress(0))

    def start_comparison_thread(self):
        raw_script = self.script_area.get("1.0", tk.END).strip()
        ph = self.txt("ph_script")
        if raw_script == ph or not raw_script:
            script_text = ""
        else:
            script_text = raw_script
            
        self.set_status(self.txt("status_reps"))
        self.set_progress(10)
        
        if script_text:
            threading.Thread(target=self.run_comparison_logic, args=(script_text,), daemon=True).start()
        else:
            threading.Thread(target=self.run_standalone_logic, daemon=True).start()

    def analyze_structure_pure_audio(self, update_ui=True):
        trans_tokens = []
        token_map = [] 
        
        for idx, w in enumerate(self.words_data):
            # ZMIANA: Jesli show_inaudible jest odznaczone, traktujemy inaudible jak normalny tekst i pozwalamy na analize
            should_skip = (w.get('is_inaudible') and self.var_show_inaudible.get()) or w.get('type') == 'silence'
            if not should_skip:
                trans_tokens.append(re.sub(r'[^\w\s]', '', w['text']).lower())
                token_map.append(idx)
        
        n = len(trans_tokens)
        diff_count = 0
        i = 0
        
        while i < n - 2:
            best_match = None
            for length in [6, 5, 4, 3]:
                if i + length > n: continue
                chunk = trans_tokens[i:i+length]
                search_end = min(n, i + length + 25)
                found_at = -1
                for k in range(i + length, search_end - length + 1):
                    if trans_tokens[k:k+length] == chunk:
                        found_at = k
                        break
                if found_at != -1:
                    best_match = (length, found_at)
                    break
            
            if best_match:
                length, match_idx = best_match
                context_len = 4
                start_1 = max(0, i - context_len)
                start_2 = max(0, match_idx - context_len)
                
                ctx1 = trans_tokens[start_1:i]
                ctx2 = trans_tokens[start_2:match_idx]
                
                similarity = 0.0
                if ctx1 and ctx2:
                    matcher = difflib.SequenceMatcher(None, ctx1, ctx2)
                    similarity = matcher.ratio()
                elif not ctx1 and not ctx2:
                    similarity = 1.0 
                
                if similarity > 0.5:
                    for k in range(i, match_idx + length):
                        real_idx = token_map[k]
                        self.words_data[real_idx]['status'] = 'repeat'
                        self.words_data[real_idx]['selected'] = False
                        diff_count += 1
                    i = match_idx 
                else:
                    i += 1
            else:
                i += 1

        if update_ui:
            self.set_progress(100)
            self.root.after(0, lambda: self.populate_text_area())
            self.set_status(self.txt("status_compared", diffs=diff_count))
            self.root.after(2000, lambda: self.set_progress(0))

    def run_comparison_logic(self, script_text):
        self.analyze_structure_pure_audio(update_ui=False) 
        self.set_status(self.txt("status_comparing"))
        self.set_progress(50)
        
        script_tokens = []
        script_spans = [] 
        pattern = re.compile(r'\S+')
        for m in pattern.finditer(script_text):
            token = re.sub(r'[^\w\s]', '', m.group()).lower()
            if token:
                script_tokens.append(token)
                start_idx = f"1.0 + {m.start()} chars"
                end_idx = f"1.0 + {m.end()} chars"
                script_spans.append((start_idx, end_idx))

        trans_tokens = []
        token_map = []
        for idx, w in enumerate(self.words_data):
            # ZMIANA: To samo co w standalone - pozwalamy inaudible wejsc do porownania jesli ukryte
            should_skip = (w.get('is_inaudible') and self.var_show_inaudible.get()) or w.get('type') == 'silence'
            if not should_skip:
                trans_tokens.append(re.sub(r'[^\w\s]', '', w['text']).lower())
                token_map.append(idx)

        matcher = difflib.SequenceMatcher(None, script_tokens, trans_tokens)
        diff_count = 0
        self.script_area.tag_remove("missing", "1.0", tk.END)

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                for j in range(j1, j2):
                    real_idx = token_map[j]
                    self.words_data[real_idx]['status'] = None
                    self.words_data[real_idx]['selected'] = False
                    
            elif tag == 'insert':
                for j in range(j1, j2):
                    real_idx = token_map[j]
                    current = self.words_data[real_idx].get('status')
                    if current != 'repeat' and current != 'typo':
                        self.words_data[real_idx]['status'] = 'bad'
                        self.words_data[real_idx]['selected'] = True
                        diff_count += 1
                        
            elif tag == 'replace':
                s_chunk = " ".join(script_tokens[i1:i2])
                t_chunk = " ".join(trans_tokens[j1:j2])
                s_squash = s_chunk.replace(" ", "")
                t_squash = t_chunk.replace(" ", "")
                is_perfect_match = (s_squash == t_squash)
                similarity = difflib.SequenceMatcher(None, s_chunk, t_chunk).ratio()
                
                for j in range(j1, j2):
                    real_idx = token_map[j]
                    current = self.words_data[real_idx].get('status')
                    if current == 'repeat': continue
                    if is_perfect_match:
                        if current == 'bad' or current == 'typo' or current is None:
                            self.words_data[real_idx]['status'] = None
                            self.words_data[real_idx]['selected'] = False
                    elif similarity > SIMILARITY_THRESHOLD:
                        self.words_data[real_idx]['status'] = 'typo'
                        self.words_data[real_idx]['selected'] = False 
                    else:
                        if current != 'typo':
                            self.words_data[real_idx]['status'] = 'bad'
                            self.words_data[real_idx]['selected'] = True
                    diff_count += 1
            elif tag == 'delete':
                for k in range(i1, i2):
                    if k < len(script_spans):
                        s_start, s_end = script_spans[k]
                        self.script_area.tag_add("missing", s_start, s_end)
                        diff_count += 1

        self.absorb_inaudible_into_repeats() # NEW: Context Aware coloring
        self.set_progress(100)
        self.root.after(0, lambda: self.populate_text_area())
        self.set_status(self.txt("status_compared", diffs=diff_count))
        self.root.after(2000, lambda: self.set_progress(0))

    # --- ZMIANA: NOWA FUNKCJA DO ZAMIANY INAUDIBLE NA REPEAT JEŚLI SĄ "W KANAPCE" ---
    def absorb_inaudible_into_repeats(self):
        n = len(self.words_data)
        if n < 3: return

        # Status REPEAT (Blue)
        target_status = 'repeat'
        
        # Helper to get effective left neighbor index (skipping silence)
        def get_prev_effective_index(start_i):
            idx = start_i - 1
            while idx >= 0:
                if self.words_data[idx].get('type') != 'silence':
                    return idx
                idx -= 1
            return -1

        # Helper to get effective right neighbor index
        def get_next_effective_index(start_i):
            idx = start_i
            while idx < n:
                if self.words_data[idx].get('type') != 'silence':
                    return idx
                idx += 1
            return -1

        i = 0
        while i < n:
            # Skip silence
            if self.words_data[i].get('type') == 'silence':
                i += 1
                continue

            # Start of inaudible block?
            if self.words_data[i].get('is_inaudible'):
                start_idx = i
                
                # Find end of inaudible block (allowing silence gaps inside the block logic is tricky, 
                # better to treat contiguous inaudible+silence+inaudible as one block)
                
                curr = i
                while curr < n:
                    w = self.words_data[curr]
                    if w.get('is_inaudible') or w.get('type') == 'silence':
                        curr += 1
                    else:
                        break
                
                end_idx = curr # Index of first Non-Inaudible/Non-Silence element after block
                
                # Check Left Neighbor
                left_idx = get_prev_effective_index(start_idx)
                prev_ok = False
                if left_idx >= 0 and self.words_data[left_idx].get('status') == target_status:
                    prev_ok = True
                
                # Check Right Neighbor (end_idx is already the next effective index if we stopped at non-silence)
                next_ok = False
                if end_idx < n and self.words_data[end_idx].get('status') == target_status:
                    next_ok = True
                
                if prev_ok and next_ok:
                    # Transform items in [start_idx, end_idx)
                    for k in range(start_idx, end_idx):
                        if self.words_data[k].get('is_inaudible'):
                            self.words_data[k]['status'] = 'repeat'
                            self.words_data[k]['selected'] = False
                
                i = end_idx
            else:
                i += 1

    def _configure_text_tags(self):
        self.text_area.tag_configure("normal", foreground=WORD_NORMAL_FG, background=INPUT_BG)
        self.text_area.tag_configure("bad", background=WORD_BAD_BG, foreground=WORD_BAD_FG)
        self.text_area.tag_configure("repeat", background=WORD_REPEAT_BG, foreground=WORD_REPEAT_FG)
        self.text_area.tag_configure("typo", background=WORD_TYPO_BG, foreground=WORD_TYPO_FG)
        self.text_area.tag_configure("inaudible", background=WORD_INAUDIBLE_BG, foreground=WORD_INAUDIBLE_FG)
        self.text_area.tag_configure("hover", background=WORD_HOVER_BG) 
        self.text_area.tag_configure("timestamp_style", foreground=NOTE_COL, font=(UI_FONT_NAME, 9, "bold"))

    # --- PAGINATION LOGIC & RENDERING ---
    def update_pagination_ui(self):
        if self.lbl_page_info:
            self.lbl_page_info.config(text=self.txt("lbl_page", current=self.current_page + 1, total=self.total_pages))
            
            if self.current_page > 0: self.btn_prev_page.config(state="normal")
            else: self.btn_prev_page.config(state="disabled")
            
            if self.current_page < self.total_pages - 1: self.btn_next_page.config(state="normal")
            else: self.btn_next_page.config(state="disabled")

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.populate_text_area()

    def next_page(self):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.populate_text_area()

    def format_seconds(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def populate_text_area(self):
        total_segments = len(self.segments_data)
        if total_segments == 0:
            self.total_pages = 1
        else:
            self.total_pages = (total_segments + self.page_size - 1) // self.page_size
            
        if self.current_page >= self.total_pages: self.current_page = self.total_pages - 1
        if self.current_page < 0: self.current_page = 0
        
        self.update_pagination_ui()
        self.separator_frames = []
        
        start_seg_idx = self.current_page * self.page_size
        end_seg_idx = start_seg_idx + self.page_size
        current_batch_segments = self.segments_data[start_seg_idx:end_seg_idx]
        current_batch_words = [w for seg in current_batch_segments for w in seg]
        
        self.text_area.configure(state="normal")
        self.text_area.delete("1.0", tk.END)
        
        # ZMIANA: Live toggle INAUDIBLE
        show_inaudible = self.var_show_inaudible.get()
        
        batch_len = len(current_batch_words)
        i = 0
        while i < batch_len:
            w_obj = current_batch_words[i]
            
            # Skip silence in editor
            if w_obj.get('type') == 'silence': 
                i += 1
                continue

            # ZMIANA: Live Toggle - skip inaudible if unchecked
            if w_obj.get('is_inaudible') and not show_inaudible:
                i += 1
                continue

            if w_obj.get('is_segment_start'):
                if self.text_area.index("end-1c") != "1.0":
                    self.text_area.insert(tk.END, "\n\n")
                
                start_str = self.format_seconds(w_obj.get('seg_start', 0))
                end_str = self.format_seconds(w_obj.get('seg_end', 0))
                header_text = f"[{start_str}] - [{end_str}]"
                tag_time = f"time_{w_obj['id']}"
                
                self.text_area.insert(tk.END, header_text, ("timestamp_style", tag_time))
                self.text_area.insert(tk.END, "  ") 
                
                sep_frame = tk.Frame(self.text_area, bg=NOTE_COL, height=1, width=1)
                self.text_area.window_create(tk.END, window=sep_frame)
                self.separator_frames.append(sep_frame)
                self.text_area.insert(tk.END, "\n")
                
                self.text_area.tag_bind(tag_time, "<Button-1>", lambda e, t=w_obj.get('seg_start', 0): self.jump_to_seconds(t))
                self.text_area.tag_bind(tag_time, "<Enter>", lambda e: self.text_area.config(cursor="hand2"))
                self.text_area.tag_bind(tag_time, "<Leave>", lambda e: self.text_area.config(cursor="arrow"))

            # ZMIANA: MERGING VISUAL INAUDIBLE (Looking ahead skipping silence)
            if w_obj.get('is_inaudible'):
                # Look ahead to count total items to skip (including inter-leaved silence)
                k = i + 1
                count_to_skip = 1 # We skip at least current 'i'
                
                while k < batch_len:
                    next_w = current_batch_words[k]
                    if next_w.get('type') == 'silence':
                        # Silence is invisible, keep looking
                        k += 1
                        count_to_skip += 1
                    elif next_w.get('is_inaudible'):
                        # If show_inaudible is False, we skip individual ones, so merge logic not needed actually
                        # But if True, merge.
                        k += 1
                        count_to_skip += 1
                    else:
                        # Found a real word, stop
                        break
                
                tag_name = f"w_{w_obj['id']}"
                state = w_obj.get('status')
                display_text = self.txt("lbl_inaudible_tag")
                
                if w_obj.get('selected') and not state: 
                     state = "inaudible"
                
                state_tag = state if state else "normal"
                self.text_area.insert(tk.END, display_text, (tag_name, "normal", state_tag))
                
                if state:
                    self.text_area.tag_add(state, f"{tag_name}.first", f"{tag_name}.last")
                
                # Determine space color based on what comes AFTER the group
                space_tag = "normal"
                if k < batch_len:
                    # k is the index of the first NON-silence, NON-inaudible item found
                    # OR it is silence/inaudible but we hit batch_len? No, logic above stops at real word or end.
                    # Wait, k loop stops if it's NOT silence AND NOT inaudible.
                    # So current_batch_words[k] is the next real word.
                    
                    real_next_w = current_batch_words[k]
                    # But wait, what if the loop finished? Then no next word.
                    
                    next_state = real_next_w.get('status')
                    if real_next_w.get('selected') and not next_state: 
                        if real_next_w.get('is_inaudible'): next_state = "inaudible"
                        else: next_state = "bad"
                    
                    if state and next_state: space_tag = state_tag 
                
                self.text_area.insert(tk.END, " ", (tag_name, "normal", space_tag))
                
                i += count_to_skip
                continue 

            else:
                # Normal word rendering
                tag_name = f"w_{w_obj['id']}"
                state = w_obj.get('status', None)
                
                if w_obj.get('selected') and not state: 
                     state = "bad"
                     w_obj['status'] = "bad"
                
                state_tag = state if state else "normal"
                self.text_area.insert(tk.END, w_obj['text'], (tag_name, "normal", state_tag))
                
                if state:
                    self.text_area.tag_add(state, f"{tag_name}.first", f"{tag_name}.last")
                
                space_tag = "normal"
                if state: 
                    if i + 1 < batch_len:
                        next_idx = i + 1
                        while next_idx < batch_len and current_batch_words[next_idx].get('type') == 'silence':
                            next_idx += 1
                        
                        # ZMIANA: Skip hidden inaudible for space coloring
                        while next_idx < batch_len and current_batch_words[next_idx].get('is_inaudible') and not show_inaudible:
                            next_idx += 1
                        
                        if next_idx < batch_len:
                            next_w = current_batch_words[next_idx]
                            next_state = next_w.get('status')
                            if next_w.get('selected') and not next_state: 
                                if next_w.get('is_inaudible'): next_state = "inaudible"
                                else: next_state = "bad"
                                
                            if next_state: space_tag = state_tag 
                
                self.text_area.insert(tk.END, " ", (tag_name, "normal", space_tag))
                i += 1

        self.setup_bindings()
        self.text_area.configure(state="disabled")
        
        self.text_area.update_idletasks()
        current_w = self.text_area.winfo_width()
        if current_w > 1:
            new_w = current_w - 160
            if new_w < 10: new_w = 10
            for frame in self.separator_frames:
                try: frame.config(width=new_w)
                except: pass
        
        self.text_area.bind("<Configure>", self.on_text_resize)

    def on_text_resize(self, event):
        new_w = event.width - 160 
        if new_w < 10: new_w = 10
        for frame in self.separator_frames:
            try: frame.config(width=new_w)
            except: pass

    def setup_bindings(self):
        self.text_area.bind("<Button-1>", lambda e: (self.close_menu_if_open(), self.on_click_start(e)))
        self.text_area.bind("<B1-Motion>", self.on_drag)
        self.text_area.bind("<ButtonRelease-1>", self.on_click_end)

    def get_word_id_at_index(self, index):
        tags = self.text_area.tag_names(index)
        for t in tags:
            if t.startswith("w_"): return int(t.split("_")[1])
        return None

    def on_click_start(self, event):
        index = self.text_area.index(f"@{event.x},{event.y}")
        tags = self.text_area.tag_names(index)
        for t in tags:
            if t.startswith("time_"): return "break" 

        wid = self.get_word_id_at_index(index)
        if (event.state & 0x4) != 0 and wid is not None: 
            self.jump_to_word(wid)
            return "break"
        self.is_dragging = True
        if wid is not None:
            current_tool = self.var_mark_tool.get()
            if current_tool == "eraser":
                new_status = None
            else:
                new_status = current_tool
                
            self.update_word_status(wid, new_status)
            self.last_dragged_id = wid
        return "break"

    def on_drag(self, event):
        if not self.is_dragging: return "break"
        index = self.text_area.index(f"@{event.x},{event.y}")
        wid = self.get_word_id_at_index(index)
        if wid is not None and wid != self.last_dragged_id:
            current_tool = self.var_mark_tool.get()
            if current_tool == "eraser":
                self.update_word_status(wid, None)
            else:
                self.update_word_status(wid, current_tool)
            self.last_dragged_id = wid
        return "break"

    def on_click_end(self, event):
        self.is_dragging = False
        self.last_dragged_id = -1
        return "break"

    # --- ZMIANA: UPDATE STATUSU GRUPY INAUDIBLE (IGNORING SILENCE) ---
    def update_word_status(self, word_id, status):
        if word_id < 0 or word_id >= len(self.words_data): return
        
        target_w = self.words_data[word_id]
        
        if target_w.get('is_inaudible'):
            # Szukamy początku grupy (przerywając na SŁOWACH, ale ignorując CISZĘ)
            start = word_id
            while start > 0:
                prev = self.words_data[start-1]
                if prev.get('is_inaudible') or prev.get('type') == 'silence':
                    start -= 1
                else:
                    break
            
            # Szukamy końca
            end = word_id
            while end < len(self.words_data)-1:
                nxt = self.words_data[end+1]
                if nxt.get('is_inaudible') or nxt.get('type') == 'silence':
                    end += 1
                else:
                    break
            
            # Aplikujemy status dla inaudible w zakresie
            for i in range(start, end + 1):
                w = self.words_data[i]
                if w.get('is_inaudible'):
                    final_status = status
                    if final_status is None: 
                        final_status = 'inaudible'
                    
                    w['status'] = final_status
                    w['selected'] = (final_status == 'bad' or final_status == 'inaudible')
        
        else:
            w_obj = target_w
            if status is None:
                if w_obj.get('is_inaudible'):
                    status = 'inaudible'
            w_obj['status'] = status
            w_obj['selected'] = (status == 'bad' or status == 'inaudible')
        
        start_seg_idx = self.current_page * self.page_size
        end_seg_idx = start_seg_idx + self.page_size
        
        try:
            first_seg = self.segments_data[start_seg_idx]
            last_seg = self.segments_data[min(len(self.segments_data)-1, end_seg_idx-1)]
            min_id = first_seg[0]['id']
            max_id = last_seg[-1]['id']
            if min_id <= word_id <= max_id:
                self.populate_text_area()
        except: pass

    def jump_to_seconds(self, seconds):
        if not self.timeline: return
        
        tc_display = self.format_seconds(seconds)
        self.set_status(f"Jumping to {tc_display}...")
        
        if self.resolve and self.project and self.timeline:
             curr = self.project.GetCurrentTimeline()
             if curr and curr.GetName() != self.timeline.GetName():
                 self.project.SetCurrentTimeline(self.timeline)
        
        frame = int(seconds * self.fps)
        start_tc = self.timeline.GetStartFrame()
        target_frame = start_tc + frame
        
        total_seconds = target_frame / self.fps
        h = int(total_seconds // 3600)
        m = int((total_seconds % 3600) // 60)
        s = int(total_seconds % 60)
        f = int(round((total_seconds - int(total_seconds)) * self.fps))
        tc_str = f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"
        self.timeline.SetCurrentTimecode(tc_str)

    def jump_to_word(self, word_id):
        w = self.words_data[word_id]
        self.jump_to_seconds(w['start'])

    # --- CORE PROCESSING ---
    def start_analysis_thread(self):
        self.btn_analyze.config(state="disabled", bg=INPUT_BG)
        thread = threading.Thread(target=self.run_analysis_pipeline, daemon=True)
        thread.start()

    def normalize_audio(self, input_path):
        self.set_status(self.txt("status_norm"))
        norm_path = input_path.replace(".wav", "_norm.wav")
        cmd = [FFMPEG_CMD, "-y", "-i", input_path, "-af", "loudnorm=I=-23:LRA=7:tp=-2.0", "-ar", "48000", "-ac", "1", norm_path]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, startupinfo=get_startup_info())
            return norm_path
        except: return input_path 

    def detect_silence(self, audio_path, threshold_db, min_dur):
        self.set_status(self.txt("status_silence"))
        cmd = [FFMPEG_CMD, "-i", audio_path, "-af", f"silencedetect=noise={threshold_db}dB:d={min_dur}", "-f", "null", "-"]
        try:
            res = subprocess.run(cmd, stderr=subprocess.PIPE, text=True, startupinfo=get_startup_info())
            output = res.stderr
            starts = [float(x) for x in re.findall(r'silence_start: (\d+\.?\d*)', output)]
            ends = [float(x) for x in re.findall(r'silence_end: (\d+\.?\d*)', output)]
            silence_ranges = []
            count = min(len(starts), len(ends))
            for i in range(count): silence_ranges.append({'s': starts[i], 'e': ends[i]})
            if len(starts) > len(ends): silence_ranges.append({'s': starts[-1], 'e': 999999.0})
            return silence_ranges
        except Exception as e:
            log_error(f"Błąd detekcji ciszy: {e}")
            return []

    def get_clean_model_name(self):
        val = self.var_model.get()
        return val.split()[0]

    def run_analysis_pipeline(self):
        try:
            lang = self.var_lang.get()
            model = self.get_clean_model_name()
            device_mode = self.var_device.get()
            
            if lang == "Auto": lang = None
            verbatim = True
            try:
                threshold = float(self.var_threshold.get())
                fps = self.fps
            except ValueError: 
                self.root.after(0, lambda: messagebox.showerror("Error", self.txt("err_num")))
                return
            
            mp = self.project.GetMediaPool()
            self.temp_nested_timeline = None
            self.generation_source_item = None
            
            if self.var_compound.get():
                self.set_status(self.txt("status_nesting"))
                root_folder = mp.GetRootFolder()
                original_tl_name = self.timeline.GetName()
                
                original_tl_item = find_timeline_item_recursive(root_folder, original_tl_name)
                
                if not original_tl_item:
                    self.root.after(0, lambda: messagebox.showerror("Error", self.txt("err_nesting")))
                    return
                
                timestamp = int(time.time())
                nested_tl_name = f"BW_Compound_{original_tl_name}_{timestamp}"
                new_tl = mp.CreateEmptyTimeline(nested_tl_name)
                
                if new_tl:
                    if mp.AppendToTimeline([original_tl_item]):
                        self.temp_nested_timeline = new_tl
                        self.generation_source_item = original_tl_item
                        self.project.SetCurrentTimeline(new_tl)
                        time.sleep(0.5)
                    else:
                        print("Failed to append original timeline to compound wrapper.")
            else:
                clips = self.timeline.GetItemListInTrack("video", 1)
                if clips:
                    self.generation_source_item = clips[0].GetMediaPoolItem()
                else:
                    self.generation_source_item = None

            unique_id = f"BW_{int(time.time())}"
            self.set_progress(5)
            
            if not os.path.exists(TEMP_DIR):
                os.makedirs(TEMP_DIR, exist_ok=True)

            wav_path = self.render_audio(unique_id)
            if not wav_path or not os.path.exists(wav_path): 
                self.root.after(0, lambda: messagebox.showerror("Error", self.txt("err_render")))
                return
            self.set_progress(40)
            
            self.set_status(self.txt("status_whisper_dl", model=model)) 
            
            try:
                self.download_whisper_model_manually(model)
            except Exception as e:
                log_error(f"Manual download failed: {e}")

            json_path = self.run_whisper(wav_path, model, lang, verbatim, device_mode)
            
            if not json_path: 
                return
            self.set_progress(70)
            
            norm_wav = self.normalize_audio(wav_path)
            
            # ZMIANA: ZASTOSOWANIE LOGIKI SILENCE KILLERA (Znormalizowane audio, próg -45dB, 0.3s)
            # Próg -45dB jest bezpieczny dla znormalizowanego audio
            silence_ranges = self.detect_silence(norm_wav, -45, 0.3) 
            
            self.set_progress(85)
            if norm_wav != wav_path: 
                try: os.remove(norm_wav)
                except: pass

            self.set_status(self.txt("status_processing"))
            
            try:
                with open(json_path, 'r', encoding='utf-8') as f: data = json.load(f)
            except json.JSONDecodeError:
                log_error("Błąd: Pusty lub uszkodzony plik JSON z Whispera.")
                self.root.after(0, lambda: messagebox.showerror("Whisper Error", "Otrzymano pusty wynik z Whispera (VRAM issue?)."))
                return
                
            temp_words = []
            auto_mark_count = 0
            dynamic_bad = [w.lower().strip() for w in self.filler_words]
            
            for seg in data.get('segments', []):
                seg_start = seg.get('start', 0)
                seg_end = seg.get('end', 0)
                is_first_word_in_seg = True
                
                for w in seg.get('words', []):
                    clean_word = w['word'].strip()
                    clean_word = re.sub(r'[^\w\s\'-]', '', clean_word)
                    if clean_word:
                        is_bad = False
                        if clean_word.lower() in dynamic_bad:
                            is_bad = True
                            auto_mark_count += 1
                        
                        w_obj = {
                            "text": clean_word, 
                            "start": w['start'], 
                            "end": w['end'], 
                            "selected": is_bad,
                            "status": "bad" if is_bad else None,
                            "seg_start": seg_start,
                            "seg_end": seg_end,
                            "is_segment_start": False,
                            "type": "word"
                        }
                        
                        if is_first_word_in_seg:
                            w_obj['is_segment_start'] = True
                            is_first_word_in_seg = False
                            
                        temp_words.append(w_obj)

            final_words = []
            
            # Wstawienie pierwszej ciszy
            if silence_ranges and temp_words and silence_ranges[0]['e'] < temp_words[0]['start']:
                 # Dodajemy ciszę na początek
                 s_start = silence_ranges[0]['s']
                 s_end = silence_ranges[0]['e']
                 
                 # Snap margins logic here too? Or keep it simple
                 margin_sec = 7.0 / self.fps
                 s_start += margin_sec
                 s_end -= margin_sec
                 
                 if s_end > s_start:
                     final_words.append({
                         "start": s_start,
                         "end": s_end,
                         "text": "[SILENCE]",
                         "type": "silence", "status": "silence", "selected": False,
                         "seg_start": 0, "seg_end": 0, "is_segment_start": False
                     })

            if temp_words:
                final_words.append(temp_words[0])
                
                for i in range(1, len(temp_words)):
                    prev_w = temp_words[i-1]
                    curr_w = temp_words[i]
                    
                    gap_start = prev_w['end']
                    gap_end = curr_w['start']
                    
                    # 3. Wypełnianie luki (Inaudible vs Silence) - METODA LINIOWA
                    relevant_silences = [s for s in silence_ranges if s['e'] > gap_start and s['s'] < gap_end]
                    relevant_silences.sort(key=lambda x: x['s'])
                    
                    current_pos = gap_start
                    
                    # Asymmetric Margins
                    margin_end_speech = 7.0 / self.fps  # Tail (End of speech)
                    margin_start_speech = 7.0 / self.fps # Attack (Start of speech)
                    
                    whisper_guard_sec = 0.1 # Safety buffer before word start

                    if not relevant_silences:
                        if gap_end - gap_start > 0.1:
                             # CHANGE HERE: Check duration for noise (Inaudible)
                             if (gap_end - gap_start) >= 0.5:
                                 final_words.append({
                                    "start": gap_start, "end": gap_end,
                                    "text": self.txt("lbl_inaudible_tag"),
                                    "type": "inaudible", "status": "inaudible", "selected": True, "is_inaudible": True,
                                    "seg_start": curr_w['seg_start'], "seg_end": curr_w['seg_end'], "is_segment_start": False
                                })
                    else:
                        for s in relevant_silences:
                            # Apply margin to silence block
                            sil_start_raw = s['s']
                            sil_end_raw = s['e']
                            
                            # Asymmetric adjustments
                            adj_start = sil_start_raw + margin_end_speech
                            adj_end = sil_end_raw - margin_start_speech
                            
                            # Whisper Guard Clamp
                            max_sil_end = gap_end - whisper_guard_sec
                            
                            # Clamp adjusted silence to gap
                            valid_sil_start = max(current_pos, adj_start)
                            valid_sil_end = min(adj_end, max_sil_end)
                            
                            # Ensure validity within the gap (mostly redundant with max/min logic but safe)
                            valid_sil_end = min(valid_sil_end, gap_end)

                            # 1. Check space before silence (Inaudible vs Margin)
                            if valid_sil_start > current_pos:
                                if current_pos < sil_start_raw:
                                    # Add Inaudible block
                                    noise_end = min(valid_sil_start, sil_start_raw)
                                    # CHANGE HERE: Check duration
                                    if noise_end > current_pos and (noise_end - current_pos) >= 0.5:
                                        final_words.append({
                                            "start": current_pos, "end": noise_end,
                                            "text": self.txt("lbl_inaudible_tag"),
                                            "type": "inaudible", "status": "inaudible", "selected": True, "is_inaudible": True,
                                            "seg_start": curr_w['seg_start'], "seg_end": curr_w['seg_end'], "is_segment_start": False
                                        })
                                    current_pos = noise_end
                                
                                # Now current_pos is at least sil_start_raw.
                                # Any gap until valid_sil_start is Margin (skip).
                                current_pos = valid_sil_start

                            # 2. Add Silence Block
                            if valid_sil_end > valid_sil_start:
                                final_words.append({
                                    "start": valid_sil_start, "end": valid_sil_end,
                                    "text": "[SILENCE]",
                                    "type": "silence", "status": "silence", "selected": False,
                                    "seg_start": curr_w['seg_start'], "seg_end": curr_w['seg_end'],
                                    "is_segment_start": False
                                })
                                current_pos = valid_sil_end
                            
                        # 3. Remaining gap after last silence
                        if current_pos < gap_end:
                            # Check if we are still inside the last raw silence (Margin)
                            last_raw_end = relevant_silences[-1]['e']
                            
                            if current_pos < last_raw_end:
                                # We are in margin -> Skip to end of raw silence
                                current_pos = last_raw_end
                            
                            if current_pos < gap_end:
                                # Real noise - CHANGE HERE: Check duration
                                if (gap_end - current_pos) >= 0.5:
                                    final_words.append({
                                        "start": current_pos, "end": gap_end,
                                        "text": self.txt("lbl_inaudible_tag"),
                                        "type": "inaudible", "status": "inaudible", "selected": True, "is_inaudible": True,
                                        "seg_start": curr_w['seg_start'], "seg_end": curr_w['seg_end'], "is_segment_start": False
                                    })
                    
                    final_words.append(curr_w)

            for i, w in enumerate(final_words):
                w['id'] = i

            self.segments_data = []
            current_segment = []
            
            for w in final_words:
                if w.get('is_segment_start') and current_segment:
                    self.segments_data.append(current_segment)
                    current_segment = []
                current_segment.append(w)
                
            if current_segment: self.segments_data.append(current_segment)

            self.words_data = final_words

            try: os.remove(wav_path)
            except: pass
            
            self.set_progress(100)
            if not self.words_data: 
                self.root.after(0, lambda: messagebox.showinfo("Info", self.txt("err_nowords")))
                return
            
            self.set_status(self.txt("status_loaded", count=len(self.words_data), bad=auto_mark_count))
            self.show_reviewer_stage()
            self.root.after(2000, lambda: self.set_progress(0))
            
        except Exception as e:
            error_msg = traceback.format_exc()
            log_error(f"Error in pipeline: {error_msg}")
            self.set_status(f"Error: See log file.")
            self.root.after(0, lambda: messagebox.showerror("Critical Error", f"Wystąpił błąd:\n{e}\n\nSzczegóły zapisano w {LOG_FILE}"))

    def render_audio(self, unique_name):
        self.set_status(self.txt("status_render"))
        try:
            self.resolve.OpenPage("deliver")
            self.project.DeleteAllRenderJobs()
            preset_loaded = self.project.LoadRenderPreset("Audio Only")
            self.project.SetRenderSettings({
                "TargetDir": TEMP_DIR, "CustomName": unique_name, "UniqueFilename": False,
                "ExportVideo": False, "ExportAudio": True
            })
            if not preset_loaded: self.project.SetRenderSettings({"AudioCodec": "pcm_s16le", "Format": "wav"})
            pid = self.project.AddRenderJob()
            self.project.StartRendering(pid)
            
            # Loop to check status
            while True:
                job_status = self.project.GetRenderJobStatus(pid)
                status = job_status.get('JobStatus')
                
                if status == "Complete":
                    return os.path.join(TEMP_DIR, unique_name + ".wav")
                elif status == "Failed" or status == "Cancelled":
                    log_error(f"Render failed. Job Status: {job_status}")
                    return None
                
                time.sleep(0.5)

        except Exception as e:
            log_error(f"Render Exception: {e}")
            return None

    def download_whisper_model_manually(self, model_name):
        # Mapowanie nazw modeli na URL (oficjalne linki Whisper)
        model_urls = {
            "tiny": "https://openaipublic.azureedge.net/main/whisper/models/65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce831d/tiny.pt",
            "base": "https://openaipublic.azureedge.net/main/whisper/models/ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt",
            "small": "https://openaipublic.azureedge.net/main/whisper/models/9ecf779972d90ba4920f7118aa1e3c914d8619bce941e0a197d215132d22df31/small.pt",
            "medium": "https://openaipublic.azureedge.net/main/whisper/models/345ae4da62f9b3d594138363380909b5294130922b053a29168136893b9835df/medium.pt",
            "large": "https://openaipublic.azureedge.net/main/whisper/models/e5b1a55b89c12a951d76f2d12bb234eb3eb72f523400912089c976a0523b1968/large-v3.pt",
        }
        
        url = model_urls.get(model_name)
        if not url: return # Nieznany model, niech whisper radzi sobie sam
        
        user_home = os.environ.get("HOME", os.path.expanduser("~"))
        cache_dir = os.path.join(user_home, ".cache", "whisper")
        os.makedirs(cache_dir, exist_ok=True)
        
        filename = os.path.basename(url)
        target_path = os.path.join(cache_dir, filename)
        
        # Sprawdzamy czy plik już jest (proste sprawdzenie, whisper sprawdza hash ale my zaufamy obecności)
        if os.path.exists(target_path):
            log_info(f"Model {model_name} found in cache: {target_path}")
            return

        log_info(f"Downloading {model_name} model manually to {target_path}")
        self.set_status(f"Downloading model {model_name} ({filename})...")
        
        try:
            # Download with urllib (no external dep)
            with urllib.request.urlopen(url) as response, open(target_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
            log_info("Download complete.")
        except Exception as e:
            log_error(f"Manual download failed: {e}")
            # If manual fail, maybe partial file exists, remove it
            if os.path.exists(target_path):
                os.remove(target_path)

    def run_whisper(self, audio_path, model, lang, verbatim, device_mode):
        self.set_status(self.txt("status_whisper_run", model=model))
        unique_name = os.path.splitext(os.path.basename(audio_path))[0]
        output_dir = TEMP_DIR
        
        # --- LINUX FIX: Pancerna konfiguracja środowiska ---
        env = os.environ.copy()
        
        vars_to_remove = ["PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH", "LIBPATH", "LD_PRELOAD"]
        for k in vars_to_remove:
            if k in env:
                del env[k]
        
        # FIX CODE -11 (SegFault): Limit threads to avoid OpenMP conflicts with Resolve
        env["OMP_NUM_THREADS"] = "1"
        
        user_home = os.environ.get("HOME", os.path.expanduser("~"))
        local_bin = os.path.join(user_home, ".local", "bin")
        
        if "PATH" in env:
            env["PATH"] = f"{local_bin}{os.pathsep}{env['PATH']}"
        else:
            env["PATH"] = local_bin

        if not IS_WIN and device_mode != "CPU":
            rocm_path = "/opt/rocm/lib"
            if os.path.exists(rocm_path):
                log_info(f"[AMD Fix] Detected ROCm path at {rocm_path}, adding to environment.")
                if "LD_LIBRARY_PATH" in env:
                    env["LD_LIBRARY_PATH"] = f"{rocm_path}:{env['LD_LIBRARY_PATH']}"
                else:
                    env["LD_LIBRARY_PATH"] = rocm_path

        whisper_executable = None
        
        possible_paths = []
        if IS_WIN:
             possible_paths.append(shutil.which("whisper.exe"))
             possible_paths.append(shutil.which("whisper"))
             try:
                 import sysconfig
                 scripts_path = sysconfig.get_path("scripts")
                 possible_paths.append(os.path.join(scripts_path, "whisper.exe"))
             except: pass
        else:
             possible_paths.append(os.path.join(local_bin, "whisper"))
             possible_paths.append(os.path.join(user_home, ".local/share/pipx/venvs/openai-whisper/bin/whisper"))
             possible_paths.append("/usr/local/bin/whisper")
             possible_paths.append("/usr/bin/whisper")

        for path in possible_paths:
            if path and os.path.exists(path) and os.access(path, os.X_OK):
                whisper_executable = path
                log_info(f"Znalazłem Whisper tutaj: {path}")
                break
        
        if not whisper_executable:
            log_info("Nie znaleziono pełnej ścieżki, próbuję komendy 'whisper' z PATH...")
            whisper_executable = "whisper" 

        # --- BUILD COMMAND HELPER ---
        def build_cmd(force_cpu=False):
            c = [whisper_executable, audio_path, "--model", model, "--output_format", "json", "--output_dir", output_dir, "--word_timestamps", "True", "--fp16", "False"]
            
            if force_cpu:
                c.extend(["--device", "cpu"])
            elif device_mode == "GPU (cuda/rocm)":
                c.extend(["--device", "cuda"]) 
            elif device_mode == "CPU":
                c.extend(["--device", "cpu"])
            
            if lang and lang != "Auto": c.extend(["--language", lang])
            if verbatim: 
                prompt_str = ", ".join(self.filler_words)
                if prompt_str.strip():
                    c.extend(["--initial_prompt", prompt_str])
            c.extend(["--condition_on_previous_text", "False"])
            return c

        cmd = build_cmd()
        log_info(f"Running (Attempt 1): {' '.join(cmd)}")
        self.set_status(self.txt("status_whisper_run", model=model))
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, env=env, startupinfo=get_startup_info())
            
            if result.returncode != 0:
                err_msg = result.stderr.lower()
                gpu_failure_keywords = ["cuda", "driver", "gpu", "kernel", "torch", "initialization", "hsa", "hip", "segmentation fault", "code -11"]
                
                if device_mode != "CPU" and (result.returncode == -11 or any(k in err_msg for k in gpu_failure_keywords)):
                    log_error(f"GPU Failed (Code {result.returncode}): {result.stderr}")
                    self.set_status("GPU Error. Retrying on CPU (Slower)...")
                    
                    cmd_cpu = build_cmd(force_cpu=True)
                    log_info(f"Running (Fallback): {' '.join(cmd_cpu)}")
                    result = subprocess.run(cmd_cpu, capture_output=True, text=True, env=env, startupinfo=get_startup_info())

            if result.returncode != 0:
                log_error(f"!!! BŁĄD WHISPERA (Kod {result.returncode}) !!!")
                log_error(f"STDERR: {result.stderr}")
                self.root.after(0, lambda: messagebox.showerror("Whisper Error", f"Whisper failed (Code {result.returncode}).\n\nLog: {LOG_FILE}"))
                return None
            
            json_file = os.path.join(output_dir, unique_name + ".json")
            if not os.path.exists(json_file):
                log_error(f"Whisper finished but NO JSON: {json_file}")
                return None
                
            return json_file

        except Exception as e:
            log_error(f"Python Exception in run_whisper: {e}")
            traceback.print_exc()
            return None

    def generate_timeline(self):
        try:
            self.set_status(self.txt("status_generating"))
            
            source_item = self.generation_source_item
            if not source_item:
                clips = self.timeline.GetItemListInTrack("video", 1)
                if clips: source_item = clips[0].GetMediaPoolItem()
                
            if not source_item:
                self.root.after(0, lambda: messagebox.showerror("Error", "No source item found."))
                return

            total_duration_sec = self.words_data[-1]['end'] + 5.0
            total_frames = int(total_duration_sec * self.fps)
            sorted_words = sorted(self.words_data, key=lambda x: x['start'])
            boundaries = [0] 
            for i in range(len(sorted_words) - 1):
                curr_w = sorted_words[i]
                next_w = sorted_words[i+1]
                cut_point = int(round(next_w['start'] * self.fps))
                next_start_f = int(round(next_w['start'] * self.fps))
                
                # ZMIANA: Obsługa ciszy w generatorze
                is_silence_curr = (curr_w.get('type') == 'silence')
                is_silence_next = (next_w.get('type') == 'silence')
                
                if is_silence_curr or is_silence_next:
                     cut_point = next_start_f
                else:
                    is_marked_curr = (curr_w.get('status') is not None)
                    is_marked_next = (next_w.get('status') is not None)
                    if is_marked_next: cut_point = next_start_f
                    elif is_marked_curr: cut_point = next_start_f
                
                if cut_point < boundaries[-1]: cut_point = boundaries[-1]
                boundaries.append(cut_point)
            boundaries.append(total_frames)
            
            final_operations = []
            for i in range(len(sorted_words)):
                start_f = boundaries[i]
                end_f = boundaries[i+1]
                
                w = sorted_words[i]
                seg_type = "normal"
                
                if w.get('type') == 'silence':
                    if self.var_silence_cut.get():
                        seg_type = "silence_cut" # Skip (cut)
                    elif self.var_silence_mark.get():
                        seg_type = "silence_mark" # Mark Tan
                    else:
                        seg_type = "normal" # Leave as normal audio
                else:
                    status = w.get('status')
                    if status: seg_type = status
                
                if end_f > start_f:
                    if final_operations and final_operations[-1]['type'] == seg_type: 
                        final_operations[-1]['e'] = end_f
                    else: 
                        final_operations.append({"s": start_f, "e": end_f, "type": seg_type})

            mp = self.project.GetMediaPool()
            timestamp = int(time.time())
            base_name = self.timeline.GetName()
            if self.var_compound.get() and self.temp_nested_timeline:
                 base_name = self.generation_source_item.GetName()
                 
            new_tl_name = f"{base_name}_BW_{timestamp}"
            new_tl = mp.CreateEmptyTimeline(new_tl_name)
            if not new_tl: 
                self.root.after(0, lambda: messagebox.showerror("Error", self.txt("err_tl_create")))
                return

            should_delete_bad = self.var_auto_del.get()
            clips_to_append = []
            ops_map = [] 

            for op in final_operations:
                t = op['type']
                # Skip if bad/inaudible/silence_cut
                if should_delete_bad and (t == 'bad' or t == 'inaudible'): continue
                if t == 'silence_cut': continue
                
                # ZMIANA: Usunięto wymuszanie 'normal' dla ukrytych inaudible
                # Dzięki temu zachowują swój status (Chocolate/Red/Blue)
                # i są generowane na timeline zgodnie z analizą.

                clips_to_append.append({
                    "mediaPoolItem": source_item,
                    "startFrame": int(op['s']),
                    "endFrame": int(op['e'])
                })
                ops_map.append(op)

            if clips_to_append:
                mp.AppendToTimeline(clips_to_append)
                self.resolve.OpenPage("edit")
                time.sleep(1.0)
                video_items = sorted(new_tl.GetItemListInTrack("video", 1) or [], key=lambda x: x.GetStart())
                audio_items = sorted(new_tl.GetItemListInTrack("audio", 1) or [], key=lambda x: x.GetStart())
                for i, op in enumerate(ops_map):
                    st = op['type']
                    color = None
                    if st == "bad": color = "Violet"
                    elif st == "repeat": color = "Navy"
                    elif st == "typo": color = "Olive"
                    elif st == "inaudible": color = "Chocolate" 
                    elif st == "silence_mark": color = "Tan"
                    
                    if color:
                        if i < len(video_items): video_items[i].SetClipColor(color)
                        if i < len(audio_items): audio_items[i].SetClipColor(color)
            
            # --- CLEANUP TEMP COMPOUND TIMELINE ---
            if self.temp_nested_timeline:
                 self.set_status(self.txt("status_cleanup"))
                 try:
                     self.project.SetCurrentTimeline(new_tl)
                     root_folder = mp.GetRootFolder()
                     temp_item = find_timeline_item_recursive(root_folder, self.temp_nested_timeline.GetName())
                     if temp_item:
                         mp.DeleteClips([temp_item])
                 except Exception as e:
                     log_error(f"Cleanup warning: {e}")

            self.set_status(self.txt("status_done"))
            self.set_progress(0)
            self.root.after(0, lambda: messagebox.showinfo("Success", self.txt("msg_success")))
            
        except Exception as e:
            error_msg = traceback.format_exc()
            log_error(f"Gen Error: {error_msg}")
            self.set_status(f"Gen Error: Check log")
            self.root.after(0, lambda: messagebox.showerror("Error", f"Błąd generowania timeline: {e}"))

if __name__ == "__main__":
    try:
        root = tk.Tk()
        default_font = font.nametofont("TkDefaultFont")
        default_font.configure(family=UI_FONT_NAME, size=10)
        app = BadWordsApp(root)
        root.mainloop()
    except Exception as e:
        log_error(f"CRITICAL APP ERROR: {e}")
        traceback.print_exc()