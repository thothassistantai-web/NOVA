# NOVA: research for a ChatGPT-like voice conversation

## Recommendation

Keep NOVA's desktop orb, provider choices and agent/tool bridges. Replace the current record–transcribe–reply loop with a persistent conversation controller that supports echo-cleaned simultaneous listening, adaptive turn endings, incremental speech recognition, streamed playback and interruption-aware history.

The most useful first upgrades are a persistent transcription worker and a tested echo-cancelled audio path. A fixed silence timer alone cannot deliver the experience requested. OpenAI Realtime or Gemini Live can provide a more integrated speech front end, but API access and billing must be checked separately from consumer subscriptions. Local speech plus the existing free-model routes should remain a supported option.

This report is research and a proposed design. No realtime provider was activated and no new runtime changes were deployed during this research.

## What the reference products establish

**ChatGPT Live:** OpenAI's product documentation describes simultaneous listening and speaking, including spoken interruption. It also notes that noise, overlapping speech, network conditions and microphone settings affect recognition. This establishes the user-facing behavior to target; it does not disclose the complete private implementation. [ChatGPT Voice](https://help.openai.com/en/articles/20001274-chatgpt-voice).

**OpenAI Realtime:** Its documented turn detection includes acoustic silence-based detection and semantic detection. Semantic detection considers whether the utterance appears complete, rather than treating every pause alike. Response creation and interruption are separately configurable. These APIs provide implementation building blocks; they are not proof that every ChatGPT product feature uses identical settings. [Voice activity detection](https://developers.openai.com/api/docs/guides/realtime-vad).

**Gemini Live:** Google documents continuous audio input, input/output transcription and interruption notifications. On interruption, the client must stop playback and clear queued audio. Google also describes the role of automatic activity detection. This confirms that interruption handling must exist in the client, not just in the model. [Live capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities).

**Conversation consistency:** OpenAI's conversation guide describes coordination between audio output, cancellation and conversation state. The design implication for NOVA is to retain the portion of a reply actually heard when interrupted, rather than silently treating an entire generated answer as delivered. [Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations).

## Verified NOVA gaps

The following come from reading the current native application, not assumptions about its design:

- Microphone capture ends before transcription and playback. Continuous mode resumes listening after the answer; it is not full duplex.
- A fixed 1.25-second speech-ending silence determines the turn boundary. It cannot distinguish a thinking pause from a completed thought.
- Every transcription launches a new process and constructs a new Whisper model. Speech synthesis is cached, but speech recognition is not.
- Five recent completed transcriptions took 4.65, 5.73, 4.48, 7.99 and 5.75 seconds from capture stopping to transcript completion. These are observed log samples, not controlled benchmarks. They include startup and transcription work.
- Model streaming is consumed into a final answer before the UI receives it. Speech is synthesized as a complete utterance before playback.
- Clicking can interrupt playback. There is no verified acoustic interruption path while the assistant speaks.
- Generated replies enter history in full before playback finishes. Playback position is not tracked.
- The session ends after 30 seconds with no speech. That is a product choice, not a necessary property of conversational voice.
- The configured 175% speech gain makes playback-reference fidelity and clipping tests especially important for echo cancellation.

## Desired conversation behavior

A session begins with one click and a short connection sound. After connection, the microphone remains active while NOVA listens, thinks and speaks. It ends only on an explicit stop, a configurable idle policy, a device fault, or a connection failure that cannot recover.

A short pause inside “find the file … the one I edited yesterday” should not force a response. “Actually, make that tomorrow” should update the latest turn or interrupt a pending reply without creating two independent tasks. A deliberate spoken interruption should stop audible playback promptly and discard queued output. A keyboard click must remain an immediate, reliable fallback.

Routine turns should use subtle visual state changes rather than two prominent beeps every few seconds. Keep audible cues for session connection, muting, ending and errors. A louder start/stop cue can remain an accessibility preference.

Natural replies should usually be short initially, with detail available on request. Long tool work should receive one truthful progress acknowledgment, not repeated filler. Silence from a tool should not be mistaken for microphone failure. Interrupting speech must not silently imply that a dispatched computer action was canceled.

## Proposed architecture

### 1. Persistent audio engine

Maintain a single capture path and a playback queue on a shared timing basis. Use bounded ring buffers and timestamps. Keep Qt rendering outside audio inference threads. Preserve a small pre-speech buffer so detection does not discard the beginning of a word. Measure device latency and handle reconnects without issuing duplicate turns.

PipeWire's echo-cancel module can expose processed capture/playback nodes and supports an AEC implementation based on WebRTC. NOVA should explicitly select those nodes and validate the render reference against the actual output device. Loading a module alone is not proof of working cancellation. [PipeWire echo cancellation](https://docs.pipewire.org/page_module_echo_cancel.html).

Test both speakers and headphones. The speaker test must include the actual selected volume, device changes, playback containing human voices, and a user speaking over the assistant. If cancellation fails, keep the existing microphone-paused playback mode available as a visible fallback.

### 2. Speech activity and turn completion

Use speech detection to find speech onset, then a separate endpoint decision to determine whether the thought has ended. There should be one authoritative turn controller. Do not run a provider's automatic endpointing and an independent local endpoint system that both submit the same turn.

Silero is an open-source speech detector with CPU-friendly inference options. Its published performance is a vendor benchmark, not a measurement on this laptop. It is a candidate to compare with the installed WebRTC detector; replacing the current detector without an accuracy test is not justified. [Silero VAD](https://github.com/snakers4/silero-vad).

Pipecat Smart Turn is an audio-native completion detector intended to complement a lightweight VAD. The project offers a quantized CPU model. This makes it a candidate for local adaptive turn endings without requiring a completed transcript first. Its published timing and accuracy must be validated on this machine. [Smart Turn](https://github.com/pipecat-ai/smart-turn), [integration reference](https://github.com/pipecat-ai/docs/blob/main/api-reference/server/utilities/turn-detection/smart-turn-overview.mdx).

For a cloud speech front end, evaluate OpenAI's semantic turn detection or Gemini's native activity controller directly. For a local front end, evaluate Smart Turn after a pause, with a bounded maximum wait and an explicit manual-send fallback.

### 3. Persistent recognition and partial transcripts

Load the recognition model once and keep it ready across turns. Expose provisional text separately from committed text so corrections do not dispatch duplicate actions. A rolling audio stream needs stability logic; repeatedly transcribing overlapping windows and appending all text is incorrect.

Faster Whisper is the existing recognition backend and can remain part of the system. Its repository links to realtime streaming integrations. Whisper Streaming provides a stability-based approach to turning an offline recognizer into a streaming service. Neither source guarantees subsecond recognition on this CPU. [Faster Whisper](https://github.com/SYSTRAN/faster-whisper), [Whisper Streaming](https://github.com/ufal/whisper_streaming).

### 4. Streamed generation and speech

Deliver model text increments to a sentence-aware speech queue. Begin speaking once a useful stable phrase is available; do not wait for an entire essay. Preserve punctuation and avoid reading incomplete words, raw markup or changing partial transcripts. Bound the queued audio so cancellation is fast.

A native speech-to-speech provider can instead supply audio directly. Keep transcripts for display and debugging, but treat the spoken interaction as the primary experience. The current Piper option remains useful for the modular/local path; changing the chat model should not require changing the microphone engine.

### 5. Interruption and history reconciliation

Each turn gets a generation identifier. A new user turn invalidates earlier generation, transcription and playback callbacks. On confirmed interruption: stop the output queue, cancel generation where supported, record how much audio was actually played, then reconcile history.

Stopping audio and canceling a dispatched agent/tool task are different operations. An interruption such as “wait” should pause speech immediately. Any active computer operation must report whether it was canceled, still running, or already completed. Do not replay a task just because a voice connection recovered.

### 6. Tool and agent separation

Use a fast conversational front end for turn-taking while OpenClaw, Codex and Cursor remain task executors. Their tool/authentication boundaries remain intact. Tool results should return into the current conversation without moving the user to a separate chat or exposing backend noise.

A raw free-model chat endpoint is not a native realtime audio service. Its tool bridge can be retained, but the voice controller must manage recognition, synthesis and interruption independently. An optional OpenAI/Gemini voice route therefore complements the existing model routes rather than proving that all existing models support native audio.

## Starting tuning values — proposals, not measured guarantees

- Audio frames: initially 20 ms, matching the existing detection framing.
- Pre-speech retention: approximately 250–400 ms.
- Interruption decision: test sustained speech confirmation around 150–300 ms after echo suppression; tune against false interruptions.
- Endpoint wait: adaptive, with short completed phrases handled sooner and hesitant phrases allowed longer. Avoid replacing the current timer with a universally shorter timer.
- Playback cancellation target: under 200 ms from confirmed interruption.
- Ordinary answer onset target: under 1.5 seconds from the actual end of a short user turn, excluding long tool work. This is an acceptance target, not achieved performance.
- Idle behavior: make the current 30-second cutoff configurable; offer an explicit persistent conversation mode.

## Implementation order

1. Establish timestamped voice-event metrics and record controlled baseline scenarios.
2. Keep Whisper loaded in a persistent worker; remove per-turn cold starts.
3. Validate echo cancellation at ordinary and 175% speech gain, then enable speech detection during playback.
4. Add interruption-aware cancellation, playback tracking and history reconciliation.
5. Stream sentence-sized replies into speech playback.
6. Evaluate adaptive local endpointing against the fixed timer.
7. Optionally evaluate one native realtime provider as a reference and user-selectable route, after confirming its access and costs.

The desktop orb and existing agent bridges can remain in place. A wholesale UI rebuild is unnecessary for these improvements.

## Acceptance tests and monitoring

Use recorded fixtures first, then repeat with the user's voice on the actual laptop. Include: a short factual question; a hesitant sentence; a mid-turn correction; speech over playback; cough, fan noise and keyboard noise; silence; a long agent operation; “stop listening”; a microphone disconnect; a provider reconnect; and an output-device change.

Track speech onset, endpoint decision, transcript readiness, first model output, first audible output, confirmed interruption, output stopped and task cancellation result. Measure false interruptions per minute, premature turn endings, duplicate actions, lost words and total answer-onset latency. Evaluate tails as well as averages.

At 175% volume, verify saturation, intelligibility and echo suppression rather than assuming amplification preserves quality. No user audio fixture should be kept indefinitely merely for convenience; the existing behavior log can keep event timings while controlled evaluation samples use an explicit retention policy.

## Decision

The recommended first path is an improved local/modular controller, preserving the existing providers. A cloud realtime path is useful as an optional quality reference and may offer a closer initial conversational experience. The final choice should follow actual latency, interruption and recognition tests on this laptop—not product branding or undocumented assumptions about ChatGPT's internals.
