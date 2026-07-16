"""
main.py
================================================================================
学术邮件每日总结 — 标准化流水线入口（v1.2）

流水线阶段（Pipeline Stages）：
  ① 配置加载    Config.from_env()
  ② 邮件获取    email_fetcher.fetch_emails_by_date()
  ③ 内联双语摘要 llm_client.summarize_emails(with_translation=True)
  ④ 独立翻译    translator.translate_emails()  ← 可选，默认关闭
  ⑤ 报告发送    notifier.send_report()

v1.2 优化：将翻译集成到摘要阶段（③），单次 API 调用同时输出原文与中文摘要，
相比 v1.1"先摘要后独立翻译"的两阶段方案：
  - API 调用次数: 5+50+ 次 → 5 次（压缩 90%+）
  - 整体运行时间: 25+ 分钟 → ~5 分钟（缩短 80%）
  - 输出格式: 更接近网页双语对照阅读体验
"""

import logging
from datetime import datetime, timedelta, timezone

from config import Config
from email_fetcher import fetch_emails_by_date
from llm_client import LLMClient
from translator import translate_emails
from notifier import send_report


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")

BEIJING_TZ = timezone(timedelta(hours=8))


def run_pipeline() -> None:
    """执行完整的每日邮件总结流水线。"""

    # ── ① 配置加载 ──
    cfg = Config.from_env()
    beijing_now = datetime.now(BEIJING_TZ)
    target_day = beijing_now - timedelta(days=1)

    logger.info(
        f"流水线启动 | 模型: {cfg.deepseek_model} | "
        f"目标日期(北京): {target_day.strftime('%Y-%m-%d')} | "
        f"内联翻译: {cfg.enable_translation} | "
        f"独立翻译: {cfg.enable_separate_translation}"
    )

    # ── ② 邮件获取 ──
    emails = fetch_emails_by_date(cfg, target_day)
    logger.info(f"阶段②完成: 获取 {len(emails)} 封邮件")

    # ── ③ 内联双语摘要（v1.2：单次 API 调用同时输出原文+中文）──
    llm = LLMClient(cfg)
    summary_report = llm.summarize_emails(
        emails,
        with_translation=cfg.enable_translation,
    )
    logger.info("阶段③完成: 摘要生成完毕")

    # ── ④ 独立翻译模块（v1.1 行为，可选，默认关闭）──
    translation_report = ""
    if cfg.enable_separate_translation and emails:
        print(f"[Pipeline] 启用独立翻译模块（v1.1 行为，将增加额外 API 调用）")
        translation_report = translate_emails(cfg, llm, emails)
        logger.info("阶段④完成: 独立翻译生成完毕")
    else:
        logger.info("阶段④跳过: 独立翻译未启用（推荐使用阶段③的内联翻译）")

    # ── ⑤ 报告发送 ──
    send_report(cfg, summary_report, translation_report, target_day)
    logger.info("流水线完成")


if __name__ == "__main__":
    run_pipeline()
