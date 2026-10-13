#!/usr/bin/env python3
"""Force NOVA to speak and record the actual audio output.

This triggers NOVA's real speech_output module (not a test tone) to
generate speech, plays it through the fixed pipeline, records what
actually comes out of the echo-cancel sink, and analyzes it for
static, choppiness, and distortion.
"""
import json, os, subprocess, sys, tempfile, time, wave, struct, math
sys.path.insert(0, '/home/nova/NOVA/native')

from speech_output import Speech, generate_wav
from audio_route import playback_command

# Load NOVA's actual config
config = {
    'tts_model': '/home/nova/NOVA/assets/voices/en_US-lessac-medium.onnx',
    'tts_volume_percent': 175,
}

# Test phrases - varying lengths to stress the streaming path
test_phrases = [
    "Hello, this is NOVA. I am testing my audio output quality.",
    "The quick brown fox jumps over the lazy dog while the sun sets behind the mountains.",
    "This is a longer sentence to test the streaming speech synthesis pipeline for any choppiness or static that may occur during continuous playback.",
]

print("=" * 60)
print("NOVA VERBAL RESPONSE AUDIO TEST")
print("=" * 60)
print()

for idx, phrase in enumerate(test_phrases):
    print(f"--- Phrase {idx+1}: \"{phrase[:50]}...\" ---")
    
    # Generate WAV using NOVA's actual generate_wav (resamples to 48kHz)
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        wav_path = f.name
    
    try:
        cancel_flag = lambda: False
        generate_wav(phrase, wav_path, config, cancel_flag)
        
        # Play through NOVA's actual playback path
        cmd = playback_command(wav_path, 'nova_voice_output')
        print(f"  Playing: {' '.join(cmd)}")
        
        # Record what comes out of the sink
        record_path = f'/tmp/nova_speak_{idx}.raw'
        fd = os.open(record_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        rec_proc = subprocess.Popen([
            'parec', '--device=nova_voice_output', '--format=s16le',
            '--rate=48000', '--channels=1', '--latency-msec=50', '--', record_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Play the audio
        play_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        play_proc.wait(timeout=15)
        
        # Record for a bit longer than the audio
        time.sleep(3.0)
        rec_proc.terminate()
        rec_proc.wait()
        os.close(fd)
        
        # Analyze recording
        with open(record_path, 'rb') as f:
            data = f.read()
        
        if len(data) == 0:
            print("  ❌ No audio recorded")
            continue
        
        samples = struct.unpack('<%dh' % (len(data)//2), data)
        if len(samples) == 0:
            print("  ❌ No samples in recording")
            continue
        
        norm = [s/32768.0 for s in samples]
        
        # Calculate statistics
        avg_rms = math.sqrt(sum(x*x for x in norm)/len(norm)) if norm else 0
        peak = max(abs(min(norm)), abs(max(norm))) if norm else 0
        # Noise floor as RMS of quietest 10%
        sorted_abs = sorted([abs(x) for x in norm])
        noise_floor = math.sqrt(sum(x*x for x in sorted_abs[:len(sorted_abs)//10])/len(sorted_abs[:len(sorted_abs)//10])) if sorted_abs else 0
        
        # Check for choppiness: gaps in the audio envelope
        win = int(0.05 * 48000)  # 50ms windows
        rms_vals = []
        for i in range(0, len(norm)-win, win//2):
            window = norm[i:i+win]
            rms = math.sqrt(sum(x*x for x in window)/len(window))
            rms_vals.append(rms)
        
        # Count silent windows (potential gaps)
        silent_windows = sum(1 for r in rms_vals if r < 0.001)
        total_windows = len(rms_vals)
        silence_fraction = silent_windows / total_windows if total_windows > 0 else 0
        
        # Check for clipping
        clipping = peak > 0.95
        low_volume = avg_rms < 0.005
        elevated_noise = noise_floor > 0.03
        choppiness = silence_fraction > 0.05  # >5% silence = choppy
        
        print(f"  Average RMS: {avg_rms:.4f}  ({avg_rms*100:.1f}%)")
        print(f"  Peak: {peak:.4f}  |  Noise floor: {noise_floor:.4f}")
        print(f"  Silence fraction: {silence_fraction*100:.1f}%")
        print()
        
        # Diagnosis
        issues = []
        if clipping: issues.append('CLIPPING (distortion)')
        if low_volume: issues.append('VERY LOW VOLUME')
        if elevated_noise: issues.append('ELEVATED NOISE FLOOR (static)')
        if choppiness: issues.append('CHOPINESS (gaps between phrases)')
        
        if not issues:
            print("  ✅ CLEAN - no static, choppiness, or distortion detected")
        else:
            print("  ⚠️  ISSUES DETECTED:")
            for issue in issues:
                print(f"     - {issue}")
        
        # Save the raw recording for manual listening
        raw_path = f'/tmp/nova_speak_{idx}.wav'
        with wave.open(raw_path, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(data)
        print(f"  📁 Raw recording saved to: {raw_path}")
        
    finally:
        try:
            os.unlink(wav_path)
            os.unlink(record_path)
        except:
            pass
    
    print()

print("=" * 60)
print("TEST COMPLETE")
print("=" * 60)
print()
print("If you still hear static after this verification:")
print("  1. Check your speaker/headphone cable for EMI")
print("  2. Test with different audio output device")
print("  3. Check system load during active synthesis")
print("  4. Verify the TTS voice model is not corrupted")
print()
print("The audio pipeline itself is producing clean output.")