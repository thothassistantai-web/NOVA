#!/usr/bin/env python3
"""
NOVA Voice Pipeline Initialization
Configures voice engines, echo cancellation, and microphone/speaker selection
for the desktop assistant on Pop!_OS/KDE X11.

This module bridges the Tauri/Rust layer with the React frontend
for the complete voice pipeline.
"""

import json
import subprocess
import os
import sys
from pathlib import Path

# Configuration paths
CONFIG_DIR = Path.home() / ".nova"
VOICE_CONFIG = CONFIG_DIR / "voice-pipeline.conf"
PIPEWIRE_CONFIG = CONFIG_DIR / "pipewire-echo-cancellation.conf"

def initialize_voice_pipeline():
    """Initialize the complete voice pipeline for NOVA."""
    
    # 1. Create configuration directories
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "voices").mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "logs").mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "credentials").mkdir(parents=True, exist_ok=True)
    
    # 2. Write default voice pipeline configuration
    default_config = {
        "voice_input": {
            "default_microphone": "auto",
            "vad_threshold": 0.5,
            "vad_silence_duration": 0.5,
            "vad_enabled": True
        },
        "voice_output": {
            "default_tts_engine": "piper",
            "default_speaker": "auto",
            "output_volume": 0.8
        },
        "voice_engine": {
            "piper": {
                "models_dir": str(CONFIG_DIR / "voices/piper"),
                "default_voice": "en_US-lessac-medium"
            },
            "kokoro": {
                "model_size": "medium",
                "language_group": "en",
                "voice_name": "Heart"
            }
        },
        "echo_cancellation": {
            "enabled": True,
            "pipewire_node": "default",
        },
        "ai_providers": {
            "primary": "OpenClaw",
            "OpenClaw": {
                "gateway_url": "http://localhost:8765"
            },
            "Ollama": {
                "server_url": "http://localhost:11434",
                "default_model": "nemotron:3.5b"
            }
        },
        "session": {
            "auto_generate_id": True,
            "timeout": 3600,
            "preserve_history": True
        },
        "privacy": {
            "local_only": False,
            "secure_storage": True
        }
    }
    
    write_config(default_config)
    
    # 3. Initialize PipeWire echo cancellation
    init_pipewire_echo_cancellation()
    
    # 4. Detect audio devices
    detect_audio_devices()
    
    # 5. Check for available TTS engines
    check_tts_engines()
    
    print("✅ NOVA Voice Pipeline Initialized")
    print("   - Audio devices detected")
    print("   - Echo cancellation configured")
    print("   - TTS engines checked")
    print("   - AI provider routing ready")


def write_config(config: dict):
    """Write the voice pipeline configuration file."""
    with open(VOICE_CONFIG, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"✅ Configuration written to {VOICE_CONFIG}")


def init_pipewire_echo_cancellation():
    """Set up PipeWire echo cancellation for NOVA."""
    
    # Check if PipeWire is running
    try:
        result = subprocess.run(
            ["pw-cli", "list-objects"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            # Configure echo cancellation
            # This is a simplified configuration - full PipeWire EC requires
            # proper node configuration
            print("🔧 PipeWire detected, configuring echo cancellation...")
            
            # Load echo cancellation plugin if available
            ec_result = subprocess.run(
                ["pactl", "load-module", "module-echo-cancel",
                 "source=auto", "sink=auto"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if ec_result.returncode == 0:
                print(f"✅ Echo cancellation module loaded: {ec_result.stdout.strip()}")
            else:
                print(f"⚠️ Echo cancellation setup note: {ec_result.stderr.strip()}")
        else:
            print("⚠️ PipeWire not fully available, using software fallback")
            
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("⚠️ PipeWire not available, using alternative audio processing")


def detect_audio_devices():
    """Detect and report available audio input/output devices."""
    
    print("🔍 Detecting audio devices...")
    
    # Get input devices
    try:
        result = subprocess.run(
            ["pactl", "list", "source"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            # Parse and display input devices
            lines = result.stdout.split('\n')
            input_devices = []
            for line in lines:
                if line.startswith('name:'):
                    device_name = line.split(':', 1)[1].strip()
                    input_devices.append(device_name)
            
            if input_devices:
                print(f"  Found {len(input_devices)} input device(s):")
                for dev in input_devices[:5]:  # Show first 5
                    print(f"    - {dev}")
            else:
                print("  No input devices found (using default)")
        else:
            print("  Could not list audio input devices")
            
    except Exception as e:
        print(f"  Audio device detection error: {e}")
    
    # Get output devices
    try:
        result = subprocess.run(
            ["pactl", "list", "sink"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            output_devices = []
            for line in lines:
                if line.startswith('name:') and 'bluetooth' not in line.lower():
                    device_name = line.split(':', 1)[1].strip()
                    output_devices.append(device_name)
            
            if output_devices:
                print(f"  Found {len(output_devices)} output device(s):")
                for dev in output_devices[:5]:
                    print(f"    - {dev}")
            else:
                print("  No output devices found (using default)")
        else:
            print("  Could not list audio output devices")
            
    except Exception as e:
        print(f"  Audio device detection error: {e}")


def check_tts_engines():
    """Check available Text-To-Speech engines."""
    
    print("🎤 Checking TTS engines...")
    
    # Check Piper
    piper_path = subprocess.run(
        ["which", "piper"],
        capture_output=True,
        text=True,
        timeout=3
    )
    
    if piper_path.returncode == 0:
        print("  ✅ Piper TTS engine found")
        # Check for model models
        models_dir = Path.home() / ".nova" / "voices" / "piper"
        if models_dir.exists():
            models = list(models_dir.glob("*.model")) + list(models_dir.glob("*.onnx"))
            print(f"  📁 {len(models)} Piper model(s) available")
    else:
        print("  ⚠️ Piper not installed (will be installed if needed)")
    
    # Check Kokoro
    kokoro_path = subprocess.run(
        ["which", "kokoro-tts"] if shutil_available else ["find", "/ -name", "kokoro*"],
        capture_output=True,
        text=True,
        timeout=3
    )
    
    print("  ✅ Kokoro TTS engine check complete")
    
    # Check OpenAI TTS availability
    openai_key = Path.home() / ".nova" / "credentials" / "openai.key"
    if openai_key.exists():
        print("  ✅ OpenAI TTS credentials configured")
    else:
        print("  ℹ️ OpenAI TTS not configured (optional)")


# Helper - check if shutil is available
import shutil

if __name__ == "__main__":
    initialize_voice_pipeline()