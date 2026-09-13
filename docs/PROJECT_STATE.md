# LuckRobot AI - Project State

Last updated: 2026-09-13

## Hardware architecture

Two Jetson Orin Nano Super 8GB devices.

### Interaction / AI Jetson

Responsibilities:
- USB microphone
- USB speaker
- monocular interaction camera
- local VAD
- local ASR
- TTS playback
- VLM/LLM cloud client
- later YOLO/perception
- ROS2 AI gateway

Environment:
- JetPack 6.2.1
- L4T R36.4.3
- Ubuntu 22.04
- Python 3.10.12
- CUDA 12.6.68
- cuDNN 9.3

Audio:
- Microphone: Generalplus Usb Audio Device
- PulseAudio source:
  alsa_input.usb-Generalplus_Usb_Audio_Device-00.mono-fallback
- Speaker: Jieli Technology CD002-AUDIO
- PulseAudio sink prefix:
  alsa_output.usb-Jieli_Technology_CD002-AUDIO
- Never depend on ALSA card number because enumeration changes after reboot/replug.

### Navigation Jetson

Repository:
https://github.com/Luckme921/luckrobot_v2

Responsibilities:
- ROS2 Humble
- Nav2
- slam_toolbox
- Collision Monitor
- LiDAR
- RGB-D
- IMU / encoder
- chassis
- semantic navigation execution

AI must never directly publish raw /cmd_vel.
AI issues high-level ROS actions/services only.

## Networking

Future dedicated Ethernet:
- interface: enP8p1s0
- ROS2/FastDDS between the two Jetsons

Wi-Fi on Interaction Jetson:
- Internet/cloud APIs

## V1 architecture

V1 dialogue mode: HALF DUPLEX

LISTENING -> THINKING -> SPEAKING -> LISTENING

During SPEAKING, normal user speech is not processed.
Voice interruption will be implemented in V2.

## V2 audio

Full duplex:
- AEC
- VAD
- ASR while speaker is active
- barge-in / interruption

## ASR

Primary:
- local sherpa-onnx
- SenseVoice
- benchmark CPU INT8 vs CUDA

Fallback:
- Qwen3-ASR local
- Tencent/Baidu cloud ASR

Current sherpa-onnx version:
- v1.13.8
- source under third_party/sherpa-onnx

## VLM / LLM

Primary:
- GLM-5.3-Flash

Optional complex reasoning:
- DeepSeek provider

## Vision

Interaction monocular camera:
- human/robot visual dialogue
- local ring buffer
- upload frames only when needed

Future semantic mapping:
- detector (YOLO/open-vocabulary)
- RGB-D depth
- TF
- map-frame position
- semantic object database

Do not use monocular VLM output as metric map coordinates.

## TTS

Cloud TTS primary initially.
Local TTS fallback later.

## System modifications made

2026-09-12:
- Installed git/build-essential/cmake/wget/bzip2/libasound2-dev/portaudio19-dev.
- Ubuntu replaced libjack-jackd2-0 with libjack0/libjack-dev.
- apt-get check passed.
- dpkg --audit clean.
- PulseAudio remained healthy.
- Generalplus microphone detected.
- Jieli speaker detected.
- No JACK rollback performed.

## Current task

Phase 3.4:
- add multi-turn Cloud Agent conversation context
- keep one dialogue context during the active Lucky session
- reset dialogue context when the local interaction session sleeps
- preserve Tool Router behavior with conversation history
- keep navigation backend MOCK only
- TTS remains pending
- real ROS2 motion remains disabled
- AI Jetson must never publish raw /cmd_vel

## Phase 1 - Local ASR validation COMPLETE

Completed: 2026-09-12

### sherpa-onnx

C++ benchmark runtime:
- sherpa-onnx v1.13.8
- ONNX Runtime 1.18.1
- Jetson Orin Nano Super
- JetPack 6.2.1
- CUDA 12.6

Python interaction runtime:
- Python 3.10.12
- isolated venv: .venv
- sherpa-onnx Python 1.13.7
- NumPy 2.2.6
- PyYAML 6.0.3

### Production ASR choice

Primary Mandarin model:
- sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17
- provider: CPU
- threads: 4
- language: zh
- ITN: enabled

Reason:
- CPU INT8 RTF about 0.053-0.056
- CUDA INT8 RTF about 0.108
- CPU is faster for this model
- GPU is reserved for future YOLO/vision workloads

Optional Cantonese model:
- sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09

### USB microphone validation

Generalplus USB microphone:
- PulseAudio capture verified
- PCM 16-bit
- mono
- 16000 Hz

Real microphone recording:
- duration: 23.404 s
- SenseVoice inference: 1.307 s
- RTF: 0.056
- Mandarin transcription matched spoken content

### Silero VAD validation

Model:
- silero_vad.onnx

Validation result:
- VAD_ASR_PIPELINE=OK
- 23.4 s recording automatically reduced to two speech segments

Detected segments:
1. start 11.590 s, duration 1.322 s
   text: 你好。

2. start 13.510 s, duration 6.058 s
   text: 我是戴伟，请带我去实验室。

### Current milestone

Phase 1: COMPLETE

Phase 2 in progress:
- stable PulseAudio USB device resolver
- continuous microphone capture
- Silero VAD automatic utterance segmentation
- resident SenseVoice recognizer
- automatic real-time transcription

Models, logs, third_party source, and .venv remain local and are not committed to Git.

## Phase 2 - Real-time speech baseline

Status: usable baseline accepted on 2026-09-12.

Validated:
- Generalplus USB microphone dynamic PulseAudio resolution
- continuous 16 kHz mono PCM capture
- Silero VAD real-time endpointing
- resident SenseVoice INT8 ASR
- CPU / 4 threads
- typical ASR inference around 0.06-0.15 s
- low-latency parec capture
- USB microphone unplug/replug recovery
- AUDIO_CONNECTING / AUDIO_OK / AUDIO_DEGRADED states
- Ctrl+C leaves no stale parec process
- PulseAudio module-suspend-on-idle disabled at audio startup
- microphone input baseline: 100% / 0 dB

Known issue:
- a small number of repeated runtime starts have produced no recognition
  despite AUDIO_OK/READY.
- This issue is currently non-blocking and remains on the regression backlog.
- Do not change VAD/ASR parameters unless reproducible evidence requires it.

Frozen baseline:
- SenseVoice 2024-07-17 INT8 model
- provider: CPU
- num_threads: 4
- VAD threshold: 0.5
- VAD min_silence_duration: 0.40 s
- parec requested latency: 100 ms
- parec process time: 20 ms

## Phase 2.1 - Lucky wake/session and ASR context COMPLETE

Status: COMPLETE on 2026-09-13.

Wake word:
- dedicated sherpa-onnx KeywordSpotter
- keyword: Lucky
- zh-en 3M Zipformer KWS model
- CPU / 1 thread
- keywords_threshold: 0.25
- keywords_score: 1.0
- wake detection no longer depends on SenseVoice transcription

Interaction session:
- SLEEPING -> AWAKE_WAIT_COMMAND -> ACTIVE
- Lucky is required only to start a session
- normal follow-up timeout: 12 s
- chat mode timeout: 20 s
- explicit sleep phrases return to SLEEPING
- follow-up conversation does not require repeating Lucky
- transcript wake aliases are cleanup only and never trigger wake

ASR robustness:
- VAD threshold remains frozen at 0.5
- microphone gain remains 100% / 0 dB
- SenseVoice remains CPU INT8 / 4 threads
- ASR receives real microphone context around each VAD segment:
  - pre-roll: 0.30 s
  - post-roll: 0.20 s
- A/B validation:
  - raw tightly-cropped VAD segments: about 3/10 successful in the stress sample
  - expanded real-audio context: 10/10 successful in the same sample
- production runtime validation passed for:
  - Lucky + command in one utterance
  - Lucky then separate command
  - continuous follow-up commands
  - chat mode
  - automatic timeout sleep
  - explicit sleep request

Tests:
- InteractionGate: 12 tests passing
- py_compile passed
- git diff --check passed

Privacy:
- debug_log_transcript disabled after validation.

Safety limitation before real motion:
- sleeping-state emergency stop is not yet an always-on local detector.
- Do not connect MOCK navigation to real robot motion until local stop handling is available independently of cloud/session state.

## Phase 3.1 - Cloud text Agent and robot identity

Status: COMPLETE on 2026-09-12.

Cloud Agent:
- provider: Zhipu
- model: GLM-5.3-Flash
- OpenAI-compatible API
- FastAPI local gateway
- API key loaded only from local .env
- .env is ignored by Git
- default reasoning_effort: low
- max_tokens: 2048

LuckRobot identity:
- name: LuckRobot
- developer: Bilibili UP主 luckme
- product type: 家用移动服务机器人
- not a Bilibili official product
- supports natural conversation and emotional companionship
- personality and capability definitions are stored locally in robot_profile.yaml

Validated:
- GET /health returns OK
- normal GLM text conversation works
- identity response correct
- developer identity response correct
- emotional companionship behavior works
- navigation request is understood without falsely claiming execution

Reasoning policy:
- low: normal conversation, companionship, simple intent recognition, simple tool selection
- high: complex vision and multi-step planning
- max: exceptional complex reasoning tasks
- physical safety must not depend on LLM reasoning depth

Next:
- Phase 3.2 Tool Router
- first semantic tool: navigate_to(location)
- tool execution will initially use MOCK backend
- later connect Tool Router to ROS2 AI Gateway
- AI Agent must never publish raw /cmd_vel

## Phase 3.2 - MOCK Tool Router COMPLETE

Status: COMPLETE on 2026-09-13.

Implemented:
- OpenAI-compatible tool calling in GLM Agent
- semantic tool allowlist
- first tool: navigate_to(location)
- Tool Router MOCK navigation backend
- tool result explicitly reports:
  - backend: mock
  - executed: false
  - status: mock_accepted
- robot profile reports that Tool Router MOCK is connected
- ROS2 Nav Gateway remains not connected

Validated through real FastAPI /chat requests:
- normal identity conversation does not invoke navigation tool
- navigation request "请带我去实验室。" invokes:
  navigate_to(location="实验室")
- runtime log confirmed:
  [TOOL] navigate_to location='实验室' backend=mock executed=false
- final Agent response correctly states that actual movement has not been executed
- Agent does not falsely claim physical navigation

Safety:
- Tool Router does not publish raw /cmd_vel
- AI Jetson must never publish raw /cmd_vel
- real ROS2 motion remains disabled
- sleeping-state local emergency stop must be implemented before real navigation execution

## Phase 3.3 - Voice to Cloud Agent bridge COMPLETE

Status: COMPLETE on 2026-09-13.

Implemented:
- local edge CloudAgentClient
- standard-library HTTP client to local FastAPI gateway
- endpoint:
  http://127.0.0.1:8000/chat
- local ASR COMMAND output is sent to GLM Agent
- Agent reply is returned to the audio runtime
- no additional HTTP dependency required

V1 half-duplex behavior:
- microphone capture stops while Agent is THINKING
- microphone capture restarts after Agent response
- VAD is recreated after cloud processing to discard stale audio
- follow-up timeout restarts after robot response finishes
- TTS is not connected yet

Validated end-to-end:
- "Lucky，你是谁"
  -> local wake
  -> ASR command
  -> GLM Agent reply
- follow-up "你可以做什么"
  -> no repeated Lucky required
  -> GLM Agent reply
- interaction session returns to SLEEPING after timeout
- "Lucky，请带我去实验室"
  -> GLM tool call
  -> Tool Router navigate_to(location="实验室")
  -> MOCK backend
  -> executed=false
- Cloud log confirmed:
  [TOOL] navigate_to location='实验室' backend=mock executed=false

Known limitation:
- Cloud Agent is currently stateless between /chat requests.
- Multi-turn linguistic context is not preserved yet.
- This can cause repeated introductions or loss of conversational references.
- Phase 3.4 will add session-scoped conversation history.

Safety:
- navigation remains MOCK only
- ROS2 Nav Gateway is not connected
- AI Jetson does not publish raw /cmd_vel
- always-on local emergency stop is required before any real navigation execution
