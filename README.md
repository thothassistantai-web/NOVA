# NOVA desktop orb

## Current voice experience

The compact dock provides chat, microphone, an animated blue orb, speaker mute and a separate end-conversation button. Controls fade while idle, leaving the orb; hover reveals them. Listening text scrolls to the newest words. The orb reacts to microphone level, with distinct thinking and speaking animations. Muting spoken replies preserves the active conversation and model request.

Continuous follow-up listening, automatic turn detection, click-to-interrupt and periodic Groq transcript previews are implemented. Speech is currently buffered as one reply to avoid playback gaps. Acoustic interruption is disabled on the installed machine because its echo-cancelled microphone was unreliable. This is not yet equivalent to ChatGPT’s full-duplex voice experience.

Run `npm test` for regression checks. Credentials, recordings, local profiles, logs and downloaded models are excluded from this repository. The setup still relies on locally installed speech environments and agent integrations.

Design reference: [OpenAI Realtime conversation lifecycle](https://developers.openai.com/api/docs/guides/realtime-conversations), including automatic turn detection and interruption handling. NOVA’s present implementation uses its existing providers rather than that API.

## Earlier implementation notes

The sections below record the project’s evolution; the current summary above and later corrective updates take precedence.

The working desktop application is `native/nova.py`, using the system's PyQt5 runtime. Launch it with `./launch_nova.sh` or the **NOVA Blue Orb** application-menu entry. A browser server and Tauri CLI are not needed for this runtime.

## Controls

- Left-click the blue orb to speak. A rising tone plays before the microphone opens. Finish your sentence and pause about 1.25 seconds; a falling tone marks capture ending, then NOVA transcribes, sends and speaks the reply. Click again while listening to finish manually.
- Right-click the orb for **Open chat**, **Choose AI / model**, **Talk to NOVA**, **Stop / mute**, or **Quit**. Drag to move the orb.
- Click during thinking or playback to interrupt and start a new voice turn.
- Select a provider and a model, type a message and press Enter or Send. The model selector supports substring search; choose a matching catalog item.
- Use Refresh model catalogs to reload the shared managed catalog and 9router model IDs.
- Record voice, then Finish recording. Review/edit the transcript before Send.
- Orb voice turns always speak their replies using local espeak-ng. The **Speak replies** checkbox controls typed-chat replies only.
- Stop cancels recording, transcription, requests and speech playback.
- Escape hides the panel; right-click the orb or use its tray menu to quit.
- Position is saved in Qt user settings; launches prevent duplicate instances.

## Working adapters and configuration

`~/.nova/desktop.json` configures the local Ollama URL/model, OpenClaw command, speech model/python and optional cloud model IDs. Restart NOVA after editing it.

Ollama uses the existing local service on port 11434. OpenClaw uses its existing CLI and gateway with an independent NOVA session and without external-channel delivery. OpenAI and Anthropic require their API keys in the launch environment; they have not been exercised with live credentials. Provider conversations remain independent and errors never reroute data automatically.

Speech capture uses arecord at 16 kHz mono. Transcription uses the existing faster-whisper environment and cached base.en model. Raw PCM arrays bypass that environment's incompatible PyAV decoder. Speech output now uses cached Piper neural voices (see the update below). Piper, Kokoro, wake word, echo cancellation and Android handoff are not implemented in this runtime.

## Correction to the earlier handoff

The old handoff claimed more completion than the files supported. The original Rust code returned placeholder success, the React file had syntax errors and imported Canvas-only components, and src-tauri lacked a Cargo manifest. The npm Tauri CLI was already installed. Cargo builds on /mnt/shared2 failed because its exFAT file mask strips executable bits; this is not solved by chmod.

The working Qt application replaces that incomplete runtime. Original files are preserved under `backups/2026-10-12/`. The Tauri files are archived under `backups/2026-10-12/legacy-tauri/` as an unfinished optional port; Linux GTK/WebKit development packages require privileged installation before they can be built. Do not treat that port as a verified application.

## Validation and limits

Native launch and rendered orb verified on KDE X11. Window properties show always-on-top. Actual NOVA adapters returned replies from both Ollama and OpenClaw. Default route is OpenClaw. Cached Whisper loaded and completed a synthetic-audio transcription; 16 kHz microphone capture also passed; real speech recognition accuracy remains to be checked with the user. Four behavior tests passed, covering click/Escape, cancellation, stale reply suppression and missing credentials. Provider request cancellation suppresses stale results, although remote work already dispatched may continue on the server. No boot autostart was enabled.

## Shared model routing (October 12 update)

NOVA reads `~/.cursor/cursor-fallback/config.json` for the existing managed model catalog and provider endpoints. Credentials are resolved with the existing fallback credential helper from environment/keyring/configured credential files; NOVA does not copy keys or alter Cursor routing.

The provider selector includes 9router, NVIDIA, Managed Free Models, and configured managed provider groups (OpenRouter, Groq, Gemini, Mistral, Ollama Cloud), alongside OpenClaw, Ollama and the optional direct cloud adapters. The managed catalog currently has 29 entries. The live 9router catalog returned 294 IDs, cached at `~/.nova/router-models.json`. Catalog membership is not a guarantee of current availability or chat compatibility. All four installed local Ollama models are selectable.

The model selector uses exact provider model IDs. Conversations are keyed by provider/model, and selections are remembered. Managed Free Models exposes the shared catalog for explicit selection; it does not silently advance to a different provider on failure. OpenRouter requests constrain prompt/completion price to zero.

Live NOVA adapter checks passed for NVIDIA `nvidia/nemotron-3.5-lightning-30b-a3b` and 9router `nvapi/openai/gpt-oss-20b`. Both returned `NOVA ready`. Other catalog models have not all been probed. Seven behavior/routing tests passed.

## Voice-first orb interaction

The orb itself no longer opens a chat panel on left-click. Recording from the chat panel remains an editable-transcript workflow. Orb recording is automatic voice input and spoken output using the selected provider/model.

Capture uses 16 kHz PCM with WebRTC VAD (vendored `webrtcvad-wheels` 2.0.14.post1) and a 1.25 second speech-ending pause. It times out after 8 seconds without detected speech and has a 45 second hard capture limit. Only a detected spoken turn is sent. Microphone capture stops before end tones, transcription and speech playback, preventing NOVA from recording its own reply during a normal turn. This does not implement full duplex echo cancellation.

`voice_threshold` and `voice_silence_seconds` in desktop.json can tune detection. Fourteen behavior/model/voice tests passed, covering left-click voice initiation, right-menu chat, automatic transcript submission, mandatory spoken voice replies, manual capture finish and pause endpointing. Start/stop cues were played successfully through paplay. Recognition accuracy with the user's own voice remains unverified.

WebRTC VAD reference: https://github.com/wiseman/py-webrtcvad . License notices are retained in the vendored wheel metadata.

## Neural voice, context, agent tools and behavior monitoring

NOVA now uses cached local Piper `en_US-lessac-medium` neural speech instead of espeak-ng. The high-quality Lessac voice is selectable in the chat panel; Preview neural voice is available from the orb menu. Native launch uses the dedicated .tts-venv so neural synthesis can stay in memory. Two inference threads keep CPU use bounded. The warmed medium voice synthesized the benchmark greeting in 0.66 seconds; that is a sample measurement, not a guarantee for every reply.

Current time is read in America/New_York on every request. City-level location is Queens, New York City, confirmed by Damian and stored privately in ~/.nova/profile.json. Simple clock/location questions are answered directly from the host, while every model receives fresh host context. This location is a saved profile, not GPS tracking.

The OpenClaw route uses the dedicated nova-desktop agent with a full tool profile and the existing shared OpenClaw workspace. Existing approval and authentication rules remain in force. The live agent ran a real date command and exposed browser, computer, skill, Codex, CUA, Mimic, REA, web-fetch and plugin-discovery tools. Codex Agent and Cursor Agent execute the installed agents with their own configured tools. NOVA's private Codex CLI was updated to 0.162.1 to fix old-CLI configuration/model incompatibilities; the app's configuration was not changed. Both agent routes executed real clock checks and reported their configured MCP tools.

OpenAI-compatible direct model routes have get_system_context and run_system_agent tools. Delegation runs OpenClaw, Codex or Cursor for live-information/computer tasks; tool calls and results are recorded. NVIDIA successfully used the context tool. Tool support varies by raw model; the OpenClaw route is the direct system-assistant choice. The optional Anthropic API adapter currently receives context but has no native function-tool loop. Product-specific features and authenticated connectors remain available only through a backend that actually exposes them; an API model does not inherit every product feature.

Private rotating JSONL behavior logs live at ~/.nova/logs/behavior.jsonl, with up to four 5 MB backups. They record state changes, transcripts, requests, replies, latency, failures, agent/tool activity and neural speech timings. Common credential patterns and secret fields are redacted. Microphone WAVs and synthesized reply WAVs are deleted after use. Do not put raw secrets in spoken requests.

The active Improve NOVA from behavior logs heartbeat reviews logs every 30 minutes. It stays quiet for unchanged/non-actionable state, respects quiet hours, and can fix clear reversible NOVA bugs with backups and tests. It only restarts an idle NOVA process. review_logs.py produces a private health-review.json; successful later requests mark earlier route failures as recovered. Codex automations require the desktop scheduler/host to be available.

Seventeen behavior/context/tool-routing tests passed. Live checks also exercised all three agent backends, NVIDIA tool calling and actual neural playback.

## Spoken replies and volume defaults

Spoken replies are enabled by default, including typed-chat replies. The checkbox preference is persisted; orb voice turns always speak. NOVA's neural synthesis volume starts at 175% and is adjustable from 0–200% in the chat panel. This boosts NOVA's generated speech rather than changing the system-wide output volume. Nineteen tests passed after this update.

## Continuous voice sessions

Click the orb once to start a continuous conversation. After each spoken answer, NOVA resumes listening after a short pause, with start/stop cues and retained per-model conversation history. Say “stop listening,” use Stop / mute, or click Stop to end the session. Clicking during speech interrupts playback and starts a fresh turn. Dragging still only moves the orb; text chat remains in the right-click menu.

NOVA now uses an app-owned PipeWire/WebRTC echo-cancelled input/output pair and monitors speech during replies. Confirmed speech interrupts the prior request and playback while preserving the ongoing microphone capture. A failed/no-speech transcript gets one listening retry, then ends the session instead of looping endlessly. Maintenance restart checks now exclude active continuous sessions even between turns. Voice volume is 175%, with a 0–200% slider. Twenty-two tests passed, including reply-to-listen resumption, Stop invalidating queued restarts, and spoken session-ending commands.


## Conversation upgrade

Whisper remains loaded in a dedicated local worker. Smart Turn v3.2 CPU provides adaptive end-of-thought detection with a bounded silence fallback. OpenAI-compatible SSE replies feed sentence-level local Piper playback before generation completes; agent CLI and non-streaming routes still wait for their final reply. Playback history commits after audio completion and marks interrupted replies. Existing model routes, credentials and 175% voice preference are preserved. Continuous sessions wait until explicitly stopped; the microphone indication remains visible.

Partial transcript infrastructure is included but disabled by default (`partial_transcripts`), because measurements on this loaded computer showed slow Whisper inference and partial requests would delay the final transcript. No microphone audio is automatically sent to a new cloud speech service. Local recognition latency remains a material limitation. The echo route smoke test played successfully and produced no false speech onset, but real-room user interruption accuracy needs ongoing observation.

## Compact voice bar
The compact mode provides chat, microphone start/stop, blue-orb interruption, speaker mute, and a live status pill. Drag the background to move it; right-click to toggle back to the orb. The choice and position are saved. Puter transcription was researched but not enabled: it is account-backed user-pays cloud transcription and its documented speech-to-text interface does not currently stream.

## Speech speed options
Groq Whisper large-v3-turbo is selected for recognition using the existing shared credential. Microphone utterances are uploaded to Groq. Network/auth/quota failures fall back to the loaded local recognizer. Select Private recognition in chat to keep audio local. The synthetic fixture transcribed accurately in .65 and .49 seconds; the earlier local warm fixture took 23.45 seconds under load. These are small smoke benchmarks, not controlled quality evaluation.

Groq Orpheus Hannah/Troy choices are wired into the speech menu with 175% gain and local Piper fallback. The existing account currently rejects synthesis until its organization administrator accepts model terms; no terms or billing settings were changed. Local medium voice stays active: sample warm synthesis 3.46 seconds versus 29.23 seconds for high quality. Free-tier speech limits apply; API access does not establish account billing tier.

## Verified playback correction
Reply audio now buffers the complete response and plays a single native-rate WAV. This intentionally increases time to first speech to avoid synthesis gaps. The previous phrase producer deleted queued WAVs before playback and lacked a completion exit; both defects are removed. Python per-sample resampling was removed in favor of the audio server's native conversion. A soft-knee limiter preserves the configured 175% boost without hard saturation.

Physical-device playback bypasses the failing echo-cancel playback sink; an app-owned asynchronous monitor source retains the echo-reference path. No system default or unrelated application settings were changed. Three physical playback trials returned zero and did not increase output-device error counters. Echo-source counters still showed errors; microphone/room interruption quality is not established by this output test. Evidence: research/playback-verification.json and research/full-reply-verification.json.

## Listening feedback
The compact and full orb animate from measured microphone amplitude. Listening status shows partial Groq recognition and horizontally scrolls to the latest words. Partial previews run approximately every five seconds, with at most one in flight and no slow local fallback; final recognition remains authoritative. This is periodic preview transcription, not word-by-word native streaming. Private/local-only recognition still has an audio-reactive orb but displays the transcript after completion.
