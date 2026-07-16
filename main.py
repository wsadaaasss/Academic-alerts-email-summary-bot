"""
main.py
================================================================================
学术邮件每日总结 — 标准化流水线入口

流水线阶段（Pipeline Stages）：
  ① 配置加载    Config.from_env()
  ② 邮件获取    email_fetcher.fetch_emails_by_date()
  ③ 邮件摘要    llm_client.summarize_emails()      ← deepseek-v4-pro
  ④ 双语翻译    translator.translate_emails()       ← deepseek-v4-pro（新增）
  ⑤ 报告发送    notifier.send_report()

各阶段解耦，可独立测试与替换。
"""

import logging
from datetime import datetime, timedelta, timezone

from config import Config
from email_fetcher import fetch_emails_by_date
from llm_client import LLMClient
from translator import translate_emails
from notifier import send_report


# ──────────────────────────────────────────────────────────────────────────────
# 日志配置
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")

BEIJING_TZ = timezone(timedelta(hours=8))


# ═════════════════════════════════════════════════════════════════════════════
# 主流水线
# ═════════════════════════════════════════════════════════════════════════════
def run_pipeline() -> None:
    """执行完整的每日邮件总结流水线。"""

    # ── ① 配置加载 ──
    cfg = Config.from_env()
    beijing_now = datetime.now(BEIJING_TZ)
    target_day = beijing_now - timedelta(days=1)

    logger.info(f"流水线启动 | 模型: {cfg.deepseek_model} | 目标日期(北京): {target_day.strftime('%Y-%m-%d')}")

    # ── ② 邮件获取 ──
    emails = fetch_emails_by_date(cfg, target_day)
    logger.info(f"阶段②完成: 获取 {len(emails)} 封邮件")

    # ── ③ 邮件摘要 ──
    llm = LLMClient(cfg)
    summary_report = llm.summarize_emails(emails)
    logger.info("阶段③完成: 摘要生成完毕")

    # ── ④ 双语翻译 ──
    translation_report = ""
    if cfg.enable_translation and emails:
        translation_report = translate_emails(cfg, llm, emails)
        logger.info("阶段④完成: 双语翻译生成完毕")
    else:
        logger.info("阶段④跳过: 翻译功能未启用或无邮件")

    # ── ⑤ 报告发送 ──
    send_report(cfg, summary_report, translation_report, target_day)
    logger.info(f"流水线完成 | 总耗时见日志")


# ═════════════════════════════════════════════════════════════════════════════
# 入口
# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    run_pipeline()
