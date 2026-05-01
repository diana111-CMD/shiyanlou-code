# Embodied AI Agent System

> 基于大模型驱动的具身智能机械臂与智能车任务规划 Agent 系统

## 解决的痛点

传统硬件控制高度依赖 ROS 等底层硬编码，面对非结构化动态环境缺乏柔性适应能力。本系统通过多 Agent 协作 + 大模型长链推理，实现：

- **自然语言指令**：用人类语言直接下达任务，无需编写控制代码
- **自动任务拆解**：大模型将宏观目标拆解为原子动作序列树
- **动态代码生成**：自动生成可执行的 Python/ROS 控制脚本
- **自纠错闭环**：执行失败自动分析根因并重写逻辑

## 系统架构

```
┌─────────────────────────────────────────────────────┐
│                   用户 (自然语言指令)                    │
│              "将工作台上的杂物分类放置"                    │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│            感知与规划 Agent (PlanningAgent)             │
│  - 长链推理理解意图                                     │
│  - 拆解为层次化任务树                                    │
│  - 扁平化为线性动作序列                                   │
└────────────────────┬────────────────────────────────┘
                     │  TaskPlan (动作序列)
                     ▼
┌─────────────────────────────────────────────────────┐
│           代码生成 Agent (CodeGenAgent)                │
│  - LLM 生成或模板生成 Python/ROS 脚本                   │
│  - 包含错误处理和安全检查                                │
└────────────────────┬────────────────────────────────┘
                     │  plan_xxx.py
                     ▼
┌─────────────────────────────────────────────────────┐
│                 执行器 (Executor)                       │
│  - Mock 模式: 本地模拟执行                               │
│  - ROS 模式: 连接真实机械臂/智能车                        │
└────────────────────┬────────────────────────────────┘
                     │  ExecutionReport
                     ▼
            ┌─────────┴──────────┐
            │     成功?           │
            │   是 ↓      ↓ 否    │
            │  返回结果    ┌──────────────┐
            │            │ SelfCorrect  │
            │            │ Agent        │
            │            │ 根因分析     │
            │            │ 重新规划/    │
            │            │ 重新生成/    │
            │            │ 参数调整     │
            │            └──────┬───────┘
            │                   │ 重试 (≤3次)
            │                   ▼
            │             Executor ───→ ...
            └─────────────────────┘
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY
```

### 3. 运行

```bash
# 交互式 CLI（Mock 模式，无需硬件）
python main.py

# 直接执行单条指令
python main.py "将红色方块移动到蓝色区域"

# 指定 LLM 模型
python main.py --model claude-sonnet-4-6 --base-url https://api.anthropic.com/v1 "把杯子放到架子上"

# 启动 API 服务
python main.py --serve
# 服务地址: http://localhost:8000
# API 文档: http://localhost:8000/docs
```

### 4. 连接真实硬件（ROS 模式）

```bash
# 先启动 roscore
roscore &

# 启动机械臂和智能车节点
python src/hardware/arm_node.py &
python src/hardware/vehicle_node.py &

# 关闭 mock 模式运行
python main.py --no-mock "执行任务"
```

## 项目结构

```
.
├── main.py                      # 主入口 (CLI + API)
├── requirements.txt
├── .env.example
├── src/
│   ├── __init__.py
│   ├── config.py                # 全局配置 (LLM, ROS, Agent 策略)
│   ├── models.py                # 核心数据模型 (TaskPlan, Action, ErrorLog...)
│   ├── llm_client.py            # LLM 客户端 (OpenAI 兼容接口)
│   ├── logger.py                # 统一日志 (Rich 彩色输出 + 文件归档)
│   ├── orchestrator.py          # Agent 编排协调器 (核心状态机)
│   ├── executor.py              # 脚本执行器 (Mock + ROS)
│   ├── api.py                   # FastAPI HTTP/WebSocket 接口
│   ├── agents/
│   │   ├── planning_agent.py    # 感知与规划 Agent
│   │   ├── codegen_agent.py     # 代码生成 Agent
│   │   └── self_correct_agent.py # 自纠错 Agent
│   └── hardware/
│       ├── arm_node.py          # 机械臂 ROS 节点
│       └── vehicle_node.py      # 智能车 ROS 节点
├── logs/                        # 运行日志目录 (自动生成)
└── workspace/                   # 生成的脚本目录 (自动生成)
```

## API 接口

### POST /api/v1/task

```json
{
  "instruction": "将工作台上的红色方块分类放到蓝色篮子里",
  "use_builtin_executor": true
}
```

### WebSocket /api/v1/task/stream

流式推送任务执行进度，适合前端实时展示推理过程和动作执行状态。

```javascript
const ws = new WebSocket("ws://localhost:8000/api/v1/task/stream");
ws.send(JSON.stringify({
  instruction: "把杯子放到架子上",
  use_builtin_executor: true
}));

ws.onmessage = (e) => {
  const event = JSON.parse(e.data);
  if (event.type === "progress") {
    console.log(`[${event.stage}] ${event.message}`);
  } else if (event.type === "result") {
    console.log("任务完成:", event);
  }
};
```

## 配置项

| 环境变量 | 说明 | 默认值 |
|---|---|---|
| `LLM_API_KEY` | LLM API 密钥 | 空 |
| `LLM_BASE_URL` | API 地址 | `https://api.openai.com/v1` |
| `LLM_MODEL` | 模型名称 | `gpt-4o` |
| `ROS_MASTER_URI` | ROS Master 地址 | `http://localhost:11311` |

## 支持的模型

系统使用 OpenAI 兼容接口，理论上支持所有兼容该接口的模型：

- OpenAI: `gpt-4o`, `gpt-4-turbo`, `o1`, `o3`
- Claude: 通过 `base_url: https://api.anthropic.com/v1`
- Qwen: 通过兼容接口
- 其他兼容 OpenAI SDK 的模型

> **建议**: 任务规划需要较强的推理能力，推荐使用 Claude Sonnet/Opus 或 GPT-4o 及以上模型。

## 开发计划

- [ ] 视觉检测模块集成（YOLO/CLIP 目标检测）
- [ ] 机械臂逆运动学求解器
- [ ] 智能车自主导航（集成 MoveBase/Nav2）
- [ ] 任务执行的 3D 仿真可视化
- [ ] 多设备并发支持
- [ ] 人类反馈强化学习 (RLHF) 优化规划质量

## License

MIT
