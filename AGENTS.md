# 维护指引

先读 docs/PROJECT_STATE.md、docs/ARCHITECTURE.md、docs/TOOLS.md、docs/OPERATIONS.md 和 docs/CONVERSATION_LATENCY.md。

保留设备本地配置和未提交修改；不要提交密钥、录音、日志或 private 数据。运行目录 luckrobot_latency_test 与生产/备份目录不同，修改前检查 cwd 和分支。工具 schema 与实际处理函数必须同步，禁止模型直接构造 shell 命令或播放任意 URL。导航模式已接入ROS 2监督/Trigger；Nav2目标阶段未启用。明确的语音任务可直接请求自动探索和恢复，含糊请求先询问，重启仅维护区提供。不得把 accepted 宣称为任务完成、已停车或已到达；实机测试默认仅查询状态，运动必须有现场看护和物理急停。

会话结束必须返回唤醒等待状态，并清除本轮候选。流式事件与文本/TTS 流式输出是不同能力，文档必须准确区分。

修改会话状态、路由或工具后运行 .venv/bin/python -B -m unittest discover -s tests -q 和 git diff --check；硬件行为需另做现场验收。新增工具或配置时同步维护 docs/TOOLS.md；启动逻辑变更同步维护 docs/OPERATIONS.md。
