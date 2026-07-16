"""
config.py
================================================================================
集中式配置管理模块。

将原 main.py 中散落在顶层的 os.environ.get() 调用统一收敛为单一数据源，
并显式声明 deepseek-v4-pro 模型相关的运行时参数（上下文长度、输出上限、
重试策略、温度等），使模型特性对调用方透明、可配置、可追溯。
"""

import os
import sys
from dataclasses import dataclass


# ──────────────────────────────────────────────────────────────────────────────
# deepseek-v4-pro 模型常量
# ──────────────────────────────────────────────────────────────────────────────
# deepseek-v4-pro 上下文窗口 128K tokens
MODEL_CONTEXT_WINDOW = 131_072
# 为系统提示词与输出预留的安全余量
CONTEXT_SAFETY_MARGIN = 8_192
# 单次请求最大输出 tokens
DEFAULT_MAX_OUTPUT_TOKENS = 8_192
# 摘要任务推荐温度（低温度 = 输出稳定、忠实于原文）
SUMMARY_TEMPERATURE = 0.0
# 翻译任务推荐温度
TRANSLATION_TEMPERATURE = 0.1


@dataclass
class Config:
    """全局运行配置，所有字段均可通过环境变量注入。"""

    # ── IMAP（读取邮件）──
    imap_email: str
    imap_auth_code: str
    imap_server: str
    imap_port: int = 993
    target_folder: str = ""

    # ── DeepSeek API ──
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-pro"
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    max_context_tokens: int = MODEL_CONTEXT_WINDOW
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    summary_temperature: float = SUMMARY_TEMPERATURE
    translation_temperature: float = TRANSLATION_TEMPERATURE
    # 邮件正文最大保留字符数。
    # 旧值 10,000 会在 WoS 推送 30+ 篇文章时截断 72%+ 内容。
    # 新值 80,000 可容纳 ~50 篇论文（标题+作者+摘要+元数据），
    # 约合 ~25K tokens，远在 128K 上下文预算内。
    # 实际超出部分由 llm_client 的 token 预算机制二次兜底截断。
    max_body_chars: int = 80_000
    # 摘要批次大小上限（实际批次由 token 预算动态裁剪）
    summary_batch_size: int = 5
    # 翻译批次大小（逐封翻译，此处为并发预留）
    translation_batch_size: int = 3

    # ── 重试策略 ──
    max_retries: int = 3
    retry_base_delay: float = 2.0  # 指数退避基数（秒）

    # ── SMTP（发送报告）──
    sender_email: str = ""
    sender_auth_code: str = ""
    receiver_email: str = ""
    smtp_server: str = ""
    smtp_port: int = 587

    # ── 功能开关 ──
    enable_translation: bool = True  # 是否生成双语对照翻译

    # ──────────────────────────────────────────────────────────────────────────
    # 构建方式
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def from_env(cls) -> "Config":
        """从环境变量构建配置，并对必填项进行校验。"""
        cfg = cls(
            imap_email=os.environ.get("IMAP_EMAIL", ""),
            imap_auth_code=os.environ.get("IMAP_AUTH_CODE", ""),
            imap_server=os.environ.get("IMAP_SERVER", ""),
            imap_port=int(os.environ.get("IMAP_PORT", 993)),
            target_folder=os.environ.get("TARGET_FOLDER", ""),
            deepseek_api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            sender_email=os.environ.get("SENDER_EMAIL", ""),
            sender_auth_code=os.environ.get("SENDER_AUTH_CODE", ""),
            receiver_email=os.environ.get("RECEIVER_EMAIL", ""),
            smtp_server=os.environ.get("SMTP_SERVER", ""),
            smtp_port=int(os.environ.get("SMTP_PORT", 587)),
            # 可选运行时参数（覆盖默认值）
            deepseek_model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
            max_body_chars=int(os.environ.get("MAX_BODY_CHARS", 80_000)),
            summary_batch_size=int(os.environ.get("SUMMARY_BATCH_SIZE", 5)),
            enable_translation=os.environ.get("ENABLE_TRANSLATION", "true").lower()
            in ("true", "1", "yes"),
        )
        cfg.validate()
        return cfg

    # ──────────────────────────────────────────────────────────────────────────
    # 校验
    # ──────────────────────────────────────────────────────────────────────────
    def validate(self) -> None:
        """校验必填项；缺失时打印清晰提示并退出。"""
        required = {
            "IMAP_EMAIL": self.imap_email,
            "IMAP_AUTH_CODE": self.imap_auth_code,
            "IMAP_SERVER": self.imap_server,
            "TARGET_FOLDER": self.target_folder,
            "DEEPSEEK_API_KEY": self.deepseek_api_key,
            "SENDER_EMAIL": self.sender_email,
            "SENDER_AUTH_CODE": self.sender_auth_code,
            "RECEIVER_EMAIL": self.receiver_email,
            "SMTP_SERVER": self.smtp_server,
        }
        missing = [name for name, val in required.items() if not val]
        if missing:
            print(f"[Config] 错误：以下必要环境变量未设置: {', '.join(missing)}")
            sys.exit(1)

    # ──────────────────────────────────────────────────────────────────────────
    # 便捷属性
    # ──────────────────────────────────────────────────────────────────────────
    @property
    def effective_input_budget(self) -> int:
        """单次 API 请求可用的输入 token 预算（上下文窗口 - 输出 - 安全余量）。"""
        return (
            self.max_context_tokens
            - self.max_output_tokens
            - CONTEXT_SAFETY_MARGIN
        )
