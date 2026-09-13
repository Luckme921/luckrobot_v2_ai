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

Current local TTS baseline:
- sherpa-onnx Kokoro multi-lang v1.0
- speaker ID: 50
- CPU threads: 6
- output: 24 kHz mono PCM
- USB speaker volume baseline: 80%
- sentence/chunk pipeline playback
- post-playback microphone guard: 0.6 s
- V1 remains half duplex
- normal ASR is not active while the robot is speaking

Cloud TTS is not required for the current baseline.

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

Phase 4.4C2-B live voice-to-vision interaction: COMPLETE.

Current focus:
- anchor visual evidence to the user utterance time instead of post-routing time
- make recent visual context relative to the user turn
- reduce Kokoro chunk-to-chunk playback gaps
- keep ordinary non-visual conversation image-free
- optimize visual interaction latency after temporal semantics are correct
- continue to keep navigation-related development deferred

Navigation / Phase 3.5 status:
- DEFERRED by user on 2026-09-13 while the Navigation Jetson is being optimized
- navigation Tool Router remains MOCK only
- ROS2 real-motion integration remains disconnected
- always-on local emergency-stop work remains required before real motion
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
- zh-en 3M Zipformer KWS model
- CPU / 1 thread
- keywords_threshold: 0.20
- keywords_score: 1.0
- tracked keyword file: configs/keywords_lucky.txt
- active acoustic keyword variants:
  - Lucky
  - 拉克
  - 那可
  - 那可以
  - 拉可
- wake detection no longer depends on SenseVoice transcription

Interaction session:
- SLEEPING -> AWAKE_WAIT_COMMAND -> ACTIVE
- Lucky is required only to start a session
- normal follow-up timeout: 12 s
- chat mode timeout: 20 s
- explicit sleep phrases return to SLEEPING
- follow-up conversation does not require repeating Lucky
- transcript wake aliases are cleanup only and never trigger wake
- observed wake-word ASR residue is removed before Cloud Agent dispatch
- repeated Lucky/wake aliases are also stripped during an ACTIVE session
- wake-only utterances are ignored instead of being sent to the Agent

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
- InteractionGate: 14 tests passing
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
- developer: 哔哩哔哩 UP主 luckme
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
- TTS was not connected at the end of Phase 3.3; Phase 4.1 subsequently added local Kokoro TTS

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

Known limitation at the end of Phase 3.3:
- Cloud Agent API itself was stateless between /chat requests.
- Multi-turn linguistic context had not yet been preserved.
- Phase 3.4 subsequently superseded this limitation with persistent Edge-owned conversation memory.

Safety:
- navigation remains MOCK only
- ROS2 Nav Gateway is not connected
- AI Jetson does not publish raw /cmd_vel
- always-on local emergency stop is required before any real navigation execution

## Phase 3.4 - Persistent long-conversation memory COMPLETE

Status: COMPLETE on 2026-09-13.

Architecture:
- conversation memory is owned by the AI Jetson Edge side
- SQLite database:
  private/memory/conversation.sqlite3
- private/ is excluded from Git
- Cloud API remains stateless between requests
- raw conversation turns are stored persistently on the AI Jetson

Memory V2:
- Raw Archive:
  all successful user/assistant turns are stored in SQLite
- raw history is append-only and is not deleted by compaction
- Compaction:
  each batch of 100 unsummarized turns is summarized by the Cloud Agent
- Block Summary:
  records the information extracted from one 100-turn batch
- Master Summary:
  combines previous accumulated memory with the newest block summary
- Recent Context:
  unsummarized recent raw turns are sent directly to the Agent
- Archive Retrieval:
  relevant old raw turns can be retrieved from SQLite and supplied to the Agent
  even when the Master Summary omitted that detail
- normal Lucky sleep does not erase memory
- audio runtime restart does not erase memory

Context sent to the Agent can contain:
1. robot system/persona prompt
2. accumulated Master Summary
3. retrieved relevant old archive turns
4. unsummarized recent raw conversation
5. current user request

Validated:
- local SQLite conversation persistence survives audio runtime restart
- 100-turn GLM compaction completed successfully
- first-turn fact "海鸥计划的测试编号是31415" survived compaction
- after 100 turns:
  summarized_through_turn_id=100
- turn 101 continued with only one active unsummarized raw turn
- raw archive remained intact after compaction
- archive retrieval recovered Q7X9 from turn 1 even when the Master Summary
  deliberately did not contain Q7X9
- Agent correctly answered Q7X9 using retrieved raw history
- contextual navigation follow-up remained functional:
  "请带我去实验室。" -> navigate_to(location="实验室")
  "那厨房呢？" -> navigate_to(location="厨房")
- both navigation calls remained MOCK:
  backend=mock
  executed=false
- 15 unit tests passed
- py_compile passed
- git diff --check passed

Failure behavior:
- memory compaction is fail-open for normal conversation
- a compaction failure does not intentionally block ordinary dialogue
- raw SQLite archive remains the source of truth

Privacy:
- raw conversation database stays under private/
- private/ is ignored by Git
- no local conversation database should be committed to GitHub

Known limitations:
- Archive Retrieval currently uses lightweight local lexical/substring matching
- semantic embedding retrieval is a future optional upgrade
- structured personal/profile memory remains a separate future layer
- TTS was still pending at the end of Phase 3.4; Phase 4.1 subsequently added local TTS

Safety:
- navigation backend remains MOCK only
- ROS2 Nav Gateway remains disconnected
- AI Jetson must never publish raw /cmd_vel
- always-on local emergency stop is the next prerequisite before real motion

## Phase 4.1 - Local TTS voice output COMPLETE

Status: COMPLETE baseline on 2026-09-13.

Architecture:
- local/offline TTS on the Interaction / AI Jetson
- sherpa-onnx Python runtime
- Kokoro multi-lang v1.0
- selected voice:
  speaker ID 50
- provider:
  CPU
- threads:
  6
- output:
  24000 Hz mono PCM
- playback:
  PulseAudio / paplay
- speaker is dynamically resolved through the existing PulseAudio USB device resolver
- no ALSA card number is hardcoded
- speaker volume baseline:
  80%

V1 dialogue state:
- LISTENING -> THINKING -> SPEAKING -> LISTENING
- microphone capture remains stopped while Cloud Agent processing and TTS playback are active
- true full-duplex barge-in / AEC remains a future V2 task

TTS text handling:
- removes unsuitable Markdown decoration
- replaces URLs with a spoken placeholder
- removes wave-dash endings that caused unnatural intonation
- splits long replies into smaller spoken chunks
- long comma-separated replies are split at natural punctuation when possible
- Agent system prompt now asks for shorter, more natural spoken Chinese replies

Latency optimization:
- initial whole-response synthesis caused roughly 10 s of additional delay before speech
- TTS was changed to chunked pipeline generation/playback
- while one generated chunk is playing, the next chunk is synthesized
- standalone validation:
  first audio latency about 2.15 s
- full runtime validation:
  first TTS audio latency observed about 1.37-2.18 s
- Cloud Agent latency observed about 6.18-7.61 s
- therefore Cloud Agent response time is currently the main contributor to total user-to-first-speech latency
- further Cloud streaming/model-routing optimization is deferred to a later performance phase

Playback feedback protection:
- post-playback microphone guard:
  0.6 s
- purpose:
  reduce the chance that speaker tail/reverberation is recognized as a new user utterance after playback
- full AEC is not implemented yet

Validated end-to-end:
- Lucky wake
- local SenseVoice ASR
- persistent Cloud Agent conversation
- local Kokoro speech synthesis
- Jieli USB speaker playback
- follow-up conversation without repeating Lucky
- state returns to LISTENING after speech
- selected voice successfully pronounces mixed Chinese and LuckRobot text

Tests:
- 18 unit tests passing
- TTS text normalization tests added
- TTS chunk-splitting tests added
- py_compile passed
- git diff --check passed

Voice/product wording:
- robot profile now uses "哔哩哔哩 UP主 luckme" instead of the English spelling "Bilibili" so local Chinese TTS reads the identity naturally

Known limitations:
- total response latency remains longer than desired because Cloud Agent currently takes roughly 6-8 s in observed tests
- Kokoro CPU generation is around real time
- V1 is half duplex
- no true acoustic echo cancellation
- Internet/web search was not connected at the end of Phase 4.1; Phase 4.2 subsequently added controlled Web Search
- music service is not connected yet

Next:
- continue Lucky wake and voice-session robustness work
- keep music search/playback as a separate future tool
- keep navigation-related work deferred until explicitly resumed

## Phase 4.2 - Controlled real-time Web Search COMPLETE

Status: COMPLETE on 2026-09-13.

Implemented:
- Zhipu Web Search integration
- endpoint:
  https://open.bigmodel.cn/api/paas/v4/web_search
- engine: search_std
- result count: 5
- search timeout: 15 s
- compact result content before returning to the Agent
- web search remains separate from future music-service integration

Cost / call control:
- hard per-user-turn Web Search budget
- maximum one real Web Search request per user turn
- budget is consumed before the external request is sent
- invalid/rejected calls before external dispatch do not consume the per-turn search budget
- once an external search dispatch is attempted, the per-turn search budget is consumed
- ordinary static conversation does not invoke Web Search
- unit tests use FakeWebSearch and do not consume real search resources

Agent behavior:
- current/recent information may use web_search
- static/general knowledge should answer without searching
- links and media are optional and must never be invented
- current system/profile/tool capability state takes precedence over
  stale historical conversation statements
- old conversation claims such as "联网未接入" are treated as past state
- developer identity is normalized to:
  哔哩哔哩 UP主 luckme

Validated:
- direct Web Search API smoke test returned fresh results
- direct Agent query for current technology news invoked web_search
- Cloud log confirmed:
  [TOOL] web_search ... paid_requests=1
- static identity request did not invoke web_search
- voice end-to-end current-news response worked after stale-capability
  precedence was added
- full local test suite passed with Web Search budget regression coverage

Voice / wake robustness improvements completed during this phase:
- KWS threshold adjusted from 0.25 to 0.20
- multiple acoustic wake variants are tracked in configs/keywords_lucky.txt
- successful real-device wake validation observed for:
  - LUCKY
  - LUCKY_LAKE
  - LUCKY_NAKE
  - LUCKY_NAKEYI
- KWS keyword file supports expanded ~/ / absolute paths while retaining model_dir-relative paths
- observed SenseVoice wake-word residue is filtered before Agent dispatch
- repeated wake words during ACTIVE sessions are also stripped
- wake-only utterances do not become Cloud commands
- fixed "好的，我想一下" filler was evaluated and intentionally removed;
  simple/complex keyword heuristics were rejected as too brittle

Safety:
- navigation remains deferred and MOCK only
- Web Search cannot directly control robot motion
- AI Jetson must never publish raw /cmd_vel

## Phase 4.3 - Response latency characterization

Status: BASELINE CHARACTERIZED on 2026-09-13.

Purpose:
- identify whether GLM generation itself, the LuckRobot prompt/tool context,
  or whole-response buffering is the dominant response-latency source
- avoid making architectural changes based on one end-to-end timing number

Direct GLM streaming benchmark:
- model: GLM-5.3-Flash
- thinking: enabled
- reasoning_effort: low
- simple two-sentence identity prompt
- first readable content:
  TTFT = 2.144 s
- total:
  2.456 s
- result:
  raw model generation itself can be relatively fast

LuckRobot prompt + tools benchmark:
- full production system prompt:
  4085 characters
- tools:
  2
- observed run:
  TTFT = 5.531 s
  total = 6.427 s

Prompt-size A/B benchmark:
- full prompt:
  4085 characters
- compact experimental prompt:
  1334 characters
- reduction:
  67.3%
- two-run median full-prompt TTFT:
  4.630 s
- two-run median compact-prompt TTFT:
  4.449 s
- median improvement:
  0.181 s

Decision:
- do not replace the production system prompt merely for prompt-size reduction
- the measured 67.3% prompt reduction produced only a small TTFT improvement
  relative to observed cloud/request variance
- preserve complete identity, safety, tool and capability instructions
- later latency work should measure full memory/context cost and evaluate
  Cloud-to-Edge response streaming plus earlier TTS playback
- fixed canned "thinking" filler remains intentionally removed

Notes:
- these benchmarks did not change production code
- the direct streaming tests were diagnostic calls and did not write
  normal Edge conversation memory
- navigation work remains deferred


## Phase 4.4 - Monocular visual dialogue

### Phase 4.4A - Camera hardware validation COMPLETE

Status: COMPLETE on 2026-09-13.

Interaction camera:
- USB UVC camera
- product:
  DECXIN Camera
- USB ID:
  1bcf:2d50
- driver:
  uvcvideo
- V4L2 nodes:
  /dev/video0
  /dev/video1
- production node selected for the current baseline:
  /dev/video0

Validated camera capabilities include:
- MJPEG 1920x1200
- MJPEG 1920x1080
- MJPEG 1280x720
- MJPEG 640x360
- YUY2 modes are also exposed

Real capture validation:
- GStreamer v4l2src successfully captured JPEG from /dev/video0
- validated frame:
  1920x1200
- captured JPEG size in the smoke test:
  48935 bytes

Dependency decision:
- Python gi / GStreamer bindings are not currently installed
- OpenCV is not currently installed in the project venv
- no new dependency was added for the first visual baseline
- camera capture uses the already-working GStreamer command-line runtime


### Phase 4.4B - Local JPEG ring buffer COMPLETE

Status: COMPLETE baseline on 2026-09-13.

Architecture:
- camera:
  /dev/video0
- capture format:
  MJPEG
- resolution:
  1280x720
- capture rate:
  10 FPS
- buffer duration:
  approximately 5 seconds
- maximum retained files:
  50
- storage:
  /dev/shm/luckrobot_vision
- storage is tmpfs/RAM-backed and does not continuously write the NVMe
- GStreamer multifilesink automatically deletes old frames after the limit

Implemented:
- configs/vision.yaml
- edge/vision/camera.py
- edge/vision/ring_buffer.py
- edge/vision/__init__.py
- scripts/vision_smoke.py
- tests/test_vision_ring_buffer.py

Visual buffer API:
- latest_frame()
- frame_ago(seconds)
- sample_recent(seconds, count)

JPEG safety:
- FileRingBuffer verifies JPEG SOI/EOI markers
- incomplete/currently-being-written frames are skipped
- frame reads tolerate files disappearing while the rolling sink deletes them

Real hardware smoke validation:
- first JPEG successfully received from the DECXIN camera
- first observed smoke frame:
  77523 bytes
- after continuous capture:
  BUFFER_FILES=50
- current frame lookup succeeded
- approximately 2-second-old frame lookup succeeded
- five-frame sampling across the recent window succeeded
- camera process stopped cleanly

Final direct smoke after script import-path fix:
- FIRST_FRAME bytes=63961
- BUFFER_FILES=50
- latest frame available
- 2-second historical frame available
- RECENT_COUNT=5
- clean STOPPED state

Tests:
- 5 new FileRingBuffer unit tests passing
- full repository test suite:
  30 tests passing
- compileall passed
- git diff --check passed

Privacy / bandwidth policy:
- camera may capture continuously into the local RAM-backed ring buffer
- continuous raw video is not sent to the cloud
- only frames needed for an explicit visual interaction should be selected
  and uploaded
- ordinary non-visual conversation should not upload camera imagery

Next:
- Phase 4.4C:
  connect voice/text intent to visual-frame selection
- send text plus current/recent JPEG frames to a multimodal Cloud Agent
- first visual behaviors should support requests such as:
  "我手里拿的是什么？"
  and
  "我刚才做了什么？"
- real navigation remains deferred
- AI Jetson must never publish raw /cmd_vel

### Phase 4.4C1 - Multimodal gateway transport COMPLETE

Status: COMPLETE baseline on 2026-09-13.

Purpose:
- carry selected local JPEG frames through the normal LuckRobot Edge/Cloud path
- preserve text-only behavior when no visual frame is needed
- avoid introducing a second vision-model provider

Model validation:
- GLM-5.3-Flash accepted JPEG image_url input directly
- test JPEG:
  1280x720
  65562 bytes
- direct multimodal request:
  3.801 s
- finish_reason:
  stop
- model correctly described the visible person, laptop and air conditioner

Implemented locally:
- GLMAgent can build a multimodal current-user message containing:
  - text
  - one or more image_url items
- FastAPI /chat accepts base64 JPEG payloads
- Cloud API validates:
  - maximum 5 images per request
  - maximum 2 MB per image
  - maximum 5 MB total image bytes
  - valid base64
  - complete JPEG SOI/EOI markers
- Edge CloudAgentClient accepts raw JPEG bytes and base64-encodes them
- text-only requests omit the image payload entirely
- durable conversation memory stores user text and assistant reply, not image bytes

Gateway end-to-end validation:
- temporary local FastAPI gateway:
  HTTP 200
- Edge log:
  [VISION] UPLOAD_FRAMES count=1
- full gateway request:
  9.475 s
- model:
  glm-5.3-flash
- visual description matched the real camera scene
- successful exchange was written to Edge memory:
  MEMORY_TURNS=1
- smoke result:
  SMOKE_EXIT=0

Tests:
- 5 new multimodal payload tests
- full repository suite:
  35 tests passing
- compileall passed
- git diff --check passed

Privacy / bandwidth behavior:
- no image is attached to ordinary text-only chat
- selected JPEG frames are sent only when the caller explicitly supplies them
- continuous camera video is not uploaded to the Cloud

Latency note:
- the multimodal gateway request took about 9.5 s in the observed smoke test
- visual interaction latency remains an optimization target
- correctness and routing behavior are being established before streaming optimization

Next:
- Phase 4.4C2:
  connect the persistent vision ring buffer to the live voice runtime
- do not use a hard-coded list of words such as
  "看", "手里", or "刚才" as the visual-intent router
- use model-driven visual acquisition so the system can decide whether it needs:
  - no image
  - the current frame
  - several recent frames
- ordinary non-visual conversation must remain image-free
- real navigation remains deferred
- AI Jetson must never publish raw /cmd_vel

### Phase 4.4C2-A - Model-driven visual acquisition routing COMPLETE

Status: COMPLETE baseline on 2026-09-13.

Architecture:
- visual intent is decided by the Cloud Agent through a structured tool request
- no hard-coded phrase list is used to decide whether camera context is required
- new semantic tool:
  request_vision
- supported acquisition modes:
  - latest
  - recent

latest:
- requests one current frame
- intended for questions about:
  - current objects
  - people
  - environment
  - items currently being shown to the robot

recent:
- requests multiple frames from the recent local ring buffer
- lookback is clamped to 1-5 seconds
- frame count is clamped to 2-5
- intended for recent motion, change or short temporal context

Agent behavior:
- when no image is attached and visual evidence is required,
  the Agent returns a structured vision_request instead of guessing
- request_vision is removed from the available tool list after images
  have already been attached
- this prevents repeated vision acquisition loops within the same user request
- ordinary text-only questions can continue without uploading camera data

Memory behavior:
- a vision acquisition request is an intermediate internal action
- it is not stored as a completed conversation turn
- only the final successful user/assistant exchange is written to durable memory

Robot profile:
- vision capability now reflects the real implementation:
  monocular camera, local approximately 5-second buffer and multimodal gateway
- visual context remains acquired only on demand

Real route smoke:
- first request contained text only
- Agent autonomously returned:
  request_vision(mode=latest)
- route latency:
  6.835 s
- no reply text was produced before visual evidence was acquired
- memory after the intermediate route:
  0 turns
- one current JPEG was selected from the local ring buffer
- second request uploaded:
  1 frame
- visual response latency:
  6.005 s
- GLM-5.3-Flash correctly described the actual camera scene
- final visual request:
  none
- durable memory after final reply:
  1 turn
- smoke result:
  SMOKE_EXIT=0

Tests:
- 4 vision-request protocol tests added
- full repository suite:
  39 tests passing
- compileall passed
- git diff --check passed

Latency note:
- the current model-driven path requires two Cloud Agent calls for a new
  visual request:
  1. decide whether/what visual context is required
  2. answer after selected frame(s) are supplied
- observed Cloud time for the validated visual turn was approximately
  12.84 seconds before local TTS
- correctness and privacy are prioritized for the first baseline
- later optimization should reduce this two-stage latency without falling
  back to brittle phrase matching

Next:
- Phase 4.4C2-B:
  integrate the persistent camera and visual-request fulfillment into
  edge/audio/runtime.py
- keep the existing half-duplex state machine:
  LISTENING -> THINKING -> SPEAKING -> LISTENING
- fix the post-TTS guard so it runs only when playback actually occurred
- validate real voice -> visual request -> camera -> multimodal reply -> TTS
- navigation remains deferred
- AI Jetson must never publish raw /cmd_vel

### Phase 4.4C2-B - Live voice-to-vision interaction COMPLETE

Status: COMPLETE baseline on 2026-09-13.

Runtime integration:
- the interaction camera starts with the audio runtime
- camera capture remains local in the RAM-backed ring buffer
- camera failure falls back to voice-only operation
- model-driven request_vision is fulfilled from the local ring buffer
- selected JPEG frames are passed through the existing multimodal gateway
- camera shuts down cleanly when the audio runtime exits

Validated live interaction:
- Lucky wake word
- SenseVoice ASR
- Cloud Agent
- model-driven visual acquisition
- local camera frame selection
- GLM-5.3-Flash multimodal understanding
- Kokoro local TTS
- Jieli USB speaker playback

Non-visual validation:
- "你是谁"
- Agent answered normally
- no vision request or image upload occurred

Visual validation:
- "你看看我手里拿的是什么"
- Agent requested:
  latest
- first attempt correctly reported that the user's hand was no longer visible
- second attempt correctly recognized a phone when it remained visible
- "你现在能看到我吗"
  correctly described the visible person, phone and background

Runtime logs confirmed:
- [VISION] REQUEST
- [VISION] FULFILL
- [VISION] SELECTED_FRAMES
- [VISION] UPLOAD_FRAMES
- multimodal Agent reply
- Kokoro TTS playback
- POST_TTS_GUARD only after successful playback
- [VISION] CAMERA_STOPPED on runtime exit

Tests:
- 4 runtime vision bridge tests added
- full repository suite:
  43 tests passing
- compileall passed
- run_audio.sh shell syntax check passed
- git diff --check passed

Known visual timing limitation:
- latest currently means the newest frame when request_vision is fulfilled
- the frame is therefore selected after the first Cloud routing call
- observed first-stage routing can take roughly 4-6 seconds
- latest is not yet anchored to the instant the user finished speaking
- this can cause an object to disappear before the selected frame is captured

Planned timing fix:
- freeze a per-turn visual snapshot in local RAM when the user command is accepted
- preserve both:
  - the current frame
  - several sampled frames from the preceding approximately 5 seconds
- after model routing:
  - latest uses the turn-anchored current frame
  - recent uses the turn-anchored historical sample
- no images are uploaded unless the Agent actually requests vision

Known TTS UX issue:
- some replies contain noticeable pauses between synthesized chunks
- current Kokoro synthesis is chunked and pipelined
- TTS generation is sometimes near or slower than real-time playback
- each chunk is currently played as a separate playback operation
- gapless/persistent PCM playback is a future optimization

Next:
- implement turn-aligned visual snapshots
- validate latest after the user lowers the shown object immediately after speaking
- validate recent temporal questions
- improve continuous TTS playback
- then return to end-to-end latency optimization
- navigation remains deferred
- AI Jetson must never publish raw /cmd_vel
