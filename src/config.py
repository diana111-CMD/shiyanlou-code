"""系统全局配置 — LLM、ROS、硬件参数、Agent 策略等。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseModel):
    """LLM API 配置，兼容 OpenAI / Claude / Qwen 等。"""
    api_key: str = Field(default="", env="LLM_API_KEY")
    base_url: str = Field(default="https://api.openai.com/v1", env="LLM_BASE_URL")
    model: str = Field(default="gpt-4o", env="LLM_MODEL")
    max_tokens: int = 4096
    temperature: float = 0.3
    thinking_budget: int = Field(default=0, description="Claude thinking / extended reasoning budget (0 = disabled)")


class ROSConfig(BaseModel):
    """ROS 通信配置。"""
    master_uri: str = Field(default="http://localhost:11311", env="ROS_MASTER_URI")
    arm_topic: str = "/arm_controller/command"
    arm_feedback_topic: str = "/arm_controller/feedback"
    vehicle_topic: str = "/vehicle/cmd_vel"
    vehicle_feedback_topic: str = "/vehicle/odom"
    camera_topic: str = "/camera/image_raw"
    use_mock: bool = Field(default=True, description="True 时使用模拟执行器，不连接真实硬件")


class AgentConfig(BaseModel):
    """Agent 策略配置。"""
    max_planning_depth: int = Field(default=5, description="任务拆解最大深度")
    max_code_retries: int = Field(default=3, description="自纠错最大重试次数")
    planning_timeout_s: int = 30
    code_gen_timeout_s: int = 30
    error_analysis_timeout_s: int = 20


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm: LLMConfig = Field(default_factory=LLMConfig)
    ros: ROSConfig = Field(default_factory=ROSConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    log_dir: Path = Field(default=Path("logs"))
    workspace_dir: Path = Field(default=Path("workspace"))


settings = Settings()
