# Jetson TTS 对照测试

日期：2026-09-19。设备 /home/jetson/luckrobot_latency_test；模型加载一次后，每引擎/音色对四段固定中文文本各测三次。机器人仍在待唤醒状态，未修改默认引擎、未自动向扬声器播放。不是空载实验室或声学首音测量。

| 引擎/音色 | 成功/请求 | 首批音频中位数 | 首批范围 | 合成 RTF 中位数 |
|---|---:|---:|---:|---:|
| Piper huayan medium | 12/12 | 0.170s | 0.089–0.259s | 0.101 |
| Kokoro speaker 50 | 12/12 | 1.629s | 0.748–2.304s | 1.270 |
| Edge 晓晓 | 12/12 | 1.473s | 1.225–1.617s | 未测音频时长 |
| Edge 云希 | 10/12 | 1.695s | 1.169–3.001s | 未测音频时长 |

首批指标：Piper 为 synthesize 首个 PCM 块；Kokoro 为首个非空回调；Edge 为首个 MP3 网络音频包，尚未计入解码/播放缓冲。因此不能直接当作麦克风到扬声器的完整延迟。模型加载时间单独记录在 JSONL，不含在表中；表中包括各模型首次合成。RTF=合成时间/音频时长，小于 1 表示整体生成快于播放，但不单独证明没有局部供音间隙。

本次 Piper 速度明显优于当前 Kokoro，建议优先试听 Piper，再决定是否切为本地主力。晓晓本次全部成功，云希出现两次 NoAudioReceived；24 次请求不足以证明在线服务长期稳定。没有对音色自然度做自动评分，中文重音/停顿和英文名读法需要用户试听。

## 试听

Windows 打开 private/tts-eval/listening/index.html；同一页提供 Piper、Kokoro、Edge 晓晓、Edge 云希的四组相同文本音频。Jetson 同路径下也有 wav/mp3 文件。请反馈哪个声音更自然，尤其普通问答和中英混读两组。当前主程序仍使用 Kokoro，尚未接入 Piper 或 Edge 的运行时切换。

## 重现

独立环境：private/tts-eval-venv，piper-tts 1.8.0、edge-tts 7.3.1、onnxruntime 1.23.2。完整依赖记录在试听目录 environment.txt。不要向机器人共用 .venv 安装测试依赖。

    private/tts-eval-venv/bin/python -m scripts.benchmark_tts --engine piper --runs 3
    private/tts-eval-venv/bin/python -m scripts.benchmark_tts --engine edge --runs 3
    .venv/bin/python -m scripts.benchmark_tts --engine kokoro --runs 3

每次重测用 --output 指定新目录，避免结果 JSONL 追加混在一起；脚本不会自动播放音频。在线只发送脚本中的固定文本，单请求上限 25 秒，无自动重试，失败也计入成功率。

Piper 模型 zh_CN-huayan-medium，22050Hz；来源 rhasspy/piper-voices。设备不能直连 Hugging Face，因此通过 hf-mirror.com 下载；ONNX MD5 40cdb7930ff91b81574d5f0489e076ea，与官方模型清单一致。模型、依赖、音频和原始结果放在 private，不提交 Git；代码和本报告提交。

参考：https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md 、https://huggingface.co/rhasspy/piper-voices 、https://github.com/rany2/edge-tts 。
