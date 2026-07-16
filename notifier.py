"""
notifier.py
================================================================================
SMTP 邮件发送模块。

职责单一化：接收 Markdown 文本，转换为 HTML 后通过 SMTP (STARTTLS) 发送。
不涉及邮件获取或 LLM 调用。
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime

import markdown2

from config import Config

logger = logging.getLogger(__name__)


def send_report(
    cfg: Config,
    summary_md: str,
    translation_md: str,
    date_for_subject: datetime,
) -> bool:
    """
    将摘要报告 + 双语翻译报告合并为 HTML 邮件并发送。

    Args:
        cfg: 全局配置。
        summary_md: 邮件摘要 Markdown 文本。
        translation_md: 双语翻译 Markdown 文本（可为空字符串）。
        date_for_subject: 用于邮件主题的日期。
    Returns:
        True 表示发送成功，False 表示失败。
    """
    if not all([cfg.sender_email, cfg.sender_auth_code, cfg.receiver_email]):
        print("[Notifier] 发送邮件所需的环境变量不完整，跳过发送。")
        return False

    # 合并摘要 + 翻译
    full_md = summary_md
    if translation_md:
        full_md += "\n" + translation_md

    # Markdown → HTML
    html_body = markdown2.markdown(
        full_md,
        extras=["tables", "fenced-code-blocks", "header-ids"],
    )

    # 基础样式（使邮件在客户端中更易读）
    styled_html = f"""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; line-height: 1.7; color: #333; max-width: 900px; margin: 0 auto; padding: 20px; }}
  blockquote {{ border-left: 3px solid #4a90d9; margin: 8px 0; padding: 4px 12px; background: #f7f9fc; border-radius: 4px; }}
  blockquote p {{ margin: 4px 0; }}
  h3, h4 {{ color: #2c3e50; margin-top: 24px; }}
  hr {{ border: none; border-top: 1px solid #ddd; margin: 20px 0; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
</style>
</head>
<body>
{html_body}
</body>
</html>
"""

    message = MIMEText(styled_html, "html", "utf-8")
    subject_str = f"每日邮件总结 - {date_for_subject.strftime('%Y-%m-%d')}"
    message["Subject"] = Header(subject_str, "utf-8")
    message["From"] = cfg.sender_email
    message["To"] = cfg.receiver_email

    try:
        server = smtplib.SMTP(cfg.smtp_server, cfg.smtp_port, timeout=30)
        server.starttls()
        server.login(cfg.sender_email, cfg.sender_auth_code)
        server.sendmail(cfg.sender_email, [cfg.receiver_email], message.as_string())
        server.quit()
        print(f"[Notifier] 报告已发送至 {cfg.receiver_email}")
        return True
    except Exception as e:
        logger.error(f"[Notifier] 发送邮件失败: {e}")
        print(f"[Notifier] 发送邮件失败: {e}")
        return False
