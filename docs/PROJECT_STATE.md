# LuckRobot AI - Project State

Last updated: 2026-09-12

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
- GLM-4.6V-Flash

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

Build sherpa-onnx v1.13.8 with:
- Jetson arm64
- CUDA 12.6
- cuDNN 9
- ONNX Runtime 1.18.1
- GPU enabled
- PortAudio disabled for first benchmark

Then benchmark SenseVoice CPU vs CUDA.

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
