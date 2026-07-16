"""
email_fetcher.py
================================================================================
IMAP 邮件获取与 HTML 正文解析模块。

职责单一化：仅负责从邮箱中拉取目标日期的邮件并返回结构化数据，
不涉及 LLM 调用或 SMTP 发送。
"""

import re
import imaplib
import email
import json
from email.header import decode_header
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

from config import Config


# 北京时区（UTC+8）
BEIJING_TZ = timezone(timedelta(hours=8))


# ═════════════════════════════════════════════════════════════════════════════
# HTML → 纯文本提取
# ═════════════════════════════════════════════════════════════════════════════
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_BLANK_RE = re.compile(r"\n\s*\n+")

_HTML_ENTITIES = {
    "&nbsp;": " ",
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
}


def extract_text_from_html(html_content: str) -> str:
    """
    从 HTML 内容中提取纯文本，保留论文列表的结构。
    相比原版：合并正则、清理更彻底。
    """
    if not html_content:
        return ""

    text = _HTML_TAG_RE.sub("\n", html_content)
    text = _MULTI_BLANK_RE.sub("\n\n", text)

    for entity, char in _HTML_ENTITIES.items():
        text = text.replace(entity, char)

    # 逐行 strip 后重组
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    return text.strip()


# ═════════════════════════════════════════════════════════════════════════════
# 编码解码工具
# ═════════════════════════════════════════════════════════════════════════════
def _safe_decode_bytes(raw: bytes) -> str:
    """
    安全解码字节流：依次尝试 utf-8 → gbk → utf-8(errors=ignore)。
    将原 main.py 中多处重复的 try/except 编码逻辑收敛为此单一函数。
    """
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="ignore")


def _decode_header_value(raw_value) -> str:
    """安全解码邮件头部字段（Subject / From）。"""
    if raw_value is None:
        return ""
    parts = decode_header(raw_value)
    decoded = []
    for data, enc in parts:
        if isinstance(data, bytes):
            decoded.append(
                data.decode(enc if enc else "utf-8", errors="ignore")
            )
        else:
            decoded.append(data)
    return "".join(decoded)


# ═════════════════════════════════════════════════════════════════════════════
# 邮件正文提取
# ═════════════════════════════════════════════════════════════════════════════
def _extract_body(msg) -> str:
    """
    从 email.message.Message 中提取正文纯文本。
    优先 text/html（经 HTML→文本转换），退而使用 text/plain。
    将原版中 multipart / 非 multipart 两条冗长分支合并。
    """
    body_plain = ""
    body_html = ""

    for part in msg.walk():
        content_type = part.get_content_type()
        if content_type == "text/html" and not body_html:
            payload = part.get_payload(decode=True)
            if payload:
                body_html = _safe_decode_bytes(payload)
        elif content_type == "text/plain" and not body_plain:
            payload = part.get_payload(decode=True)
            if payload:
                body_plain = _safe_decode_bytes(payload)

    # HTML 优先（文献邮件多为 HTML 格式，信息更完整）
    if body_html:
        return extract_text_from_html(body_html)
    return body_plain


# ═════════════════════════════════════════════════════════════════════════════
# IMAP 邮件获取主逻辑
# ═════════════════════════════════════════════════════════════════════════════
def fetch_emails_by_date(cfg: Config, target_date: datetime) -> List[Dict]:
    """
    连接 IMAP 服务器，获取 target_date（北京时间日期）收到的邮件。

    返回结构：[{"from_sender", "subject", "body_preview", "date"}, ...]
    """
    mail_list: List[Dict] = []

    try:
        conn = imaplib.IMAP4_SSL(cfg.imap_server, cfg.imap_port)
        conn.login(cfg.imap_email, cfg.imap_auth_code)
        conn.select(f'"{cfg.target_folder}"')

        # 向前多取 2 天以覆盖时区边界，再在客户端精确过滤
        fetch_since = target_date - timedelta(days=2)
        search_query = f'(SINCE "{fetch_since.strftime("%d-%b-%Y")}")'

        status, messages = conn.search(None, search_query)
        if status != "OK":
            print(f"[EmailFetcher] IMAP 搜索失败: {search_query}")
            conn.logout()
            return []

        email_ids = messages[0].split()

        for email_id in reversed(email_ids):
            try:
                _, msg_data = conn.fetch(email_id, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])

                # ── 日期过滤（统一到北京时区）──
                date_header = msg.get("Date")
                if not date_header:
                    continue
                email_dt = parsedate_to_datetime(date_header)
                if email_dt.tzinfo is None:
                    email_dt = email_dt.replace(tzinfo=timezone.utc)
                email_dt_bj = email_dt.astimezone(BEIJING_TZ)
                if email_dt_bj.date() != target_date.date():
                    continue

                # ── 提取字段 ──
                subject = _decode_header_value(msg["Subject"])
                from_sender = _decode_header_value(msg.get("From"))
                body = _extract_body(msg)

                # 截断超长正文并记录警告
                truncated = len(body) > cfg.max_body_chars
                body_preview = body[:cfg.max_body_chars]
                if truncated:
                    print(
                        f"[EmailFetcher] ⚠ 邮件 '{subject[:50]}' 正文 "
                        f"{len(body)} 字符超出上限 {cfg.max_body_chars}，已截断"
                    )

                mail_list.append({
                    "from_sender": from_sender,
                    "subject": subject,
                    "body_preview": body_preview,
                    "date": email_dt_bj.isoformat(),
                })
            except Exception as e:
                eid = email_id.decode() if isinstance(email_id, bytes) else str(email_id)
                print(f"[EmailFetcher] 解析邮件 {eid} 时出错: {e}")
                continue

        conn.logout()
        print(f"[EmailFetcher] 成功获取 {len(mail_list)} 封邮件（文件夹: {cfg.target_folder}）")
        return mail_list

    except Exception as e:
        print(f"[EmailFetcher] 获取邮件失败: {e}")
        return []
