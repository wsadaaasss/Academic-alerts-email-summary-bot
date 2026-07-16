"""
translator.py
================================================================================
中英文逐行对照翻译模块。

调用 deepseek-v4-pro 对每封邮件的正文（含主题）进行双语翻译，
输出"原文 / 译文"交替排列的格式，便于快速比对阅读。

★ 长邮件分块机制：
  Web of Science 单期推送可达 50+ 篇论文（~80K 字符），翻译输出量
  约为输入量的 2 倍（原文+译文逐行）。本模块将超长邮件自动拆分为
  token 预算内的分块，逐块翻译后拼接，确保不超出 128K 上下文窗口。
"""

import logging
from typing import List, Dict

from config import Config
from llm_client import LLMClient, estimate_tokens
from prompts import render_prompt, TRANSLATION_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


# 翻译输出 token 上限（deepseek-v4-pro 输出量 ≈ 输入 × 2）
TRANSLATION_MAX_OUTPUT_TOKENS = 32_768


def _estimate_template_tokens() -> int:
    """估算翻译提示词模板（空渲染）的 token 开销。"""
    empty_prompt = render_prompt(TRANSLATION_SYSTEM_PROMPT, content="")
    return estimate_tokens(empty_prompt)


def _compute_max_chunk_chars(cfg: Config) -> int:
    """
    计算单块翻译内容的最大字符数。

    约束推导（设 content_tokens = C, template_tokens = T）：
      - 输入 = T + C
      - 输出 ≈ 2C（原文行 + 译文行）
      - 总量 ≤ 上下文窗口 - 安全余量
      → T + 3C ≤ effective_input_budget
      → C ≤ (effective_input_budget - T) / 3
      同时输出受 max_tokens 限制：2C ≤ max_tokens → C ≤ max_tokens / 2
      取两者较小值。
    """
    template_tokens = _estimate_template_tokens()
    context_constraint = (cfg.effective_input_budget - template_tokens) // 3
    output_constraint = TRANSLATION_MAX_OUTPUT_TOKENS // 2
    max_tokens = min(context_constraint, output_constraint)
    # 保守转换为字符数：混合内容 ~3 字符/token
    max_chars = max_tokens * 3
    logger.info(
        f"[Translator] 单块上限: {max_chars} chars "
        f"(tokens: context={context_constraint}, output={output_constraint})"
    )
    return max_chars


def _chunk_content(content: str, max_chars: int) -> List[str]:
    """
    将长文本按行边界拆分为不超过 max_chars 的分块。
    确保不在行中间截断。
    """
    if len(content) <= max_chars:
        return [content]

    chunks: List[str] = []
    lines = content.split("\n")
    current_lines: List[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for \n
        if current_len + line_len > max_chars and current_lines:
            chunks.append("\n".join(current_lines))
            current_lines = []
            current_len = 0
        current_lines.append(line)
        current_len += line_len

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks


def _prepare_email_content(mail: Dict) -> str:
    """将单封邮件的标题和正文组装为待翻译文本。"""
    subject = mail.get("subject", "")
    body = mail.get("body_preview", "")
    return f"【主题】\n{subject}\n\n【正文】\n{body}"


def translate_single_email(
    llm: LLMClient,
    cfg: Config,
    mail: Dict,
    index: int,
) -> str:
    """
    对单封邮件内容进行中英逐行对照翻译。

    长邮件自动分块：每块独立调用 deepseek-v4-pro，结果按序拼接。
    """
    content = _prepare_email_content(mail)

    if not content.strip():
        return ""

    max_chunk_chars = _compute_max_chunk_chars(cfg)
    chunks = _chunk_content(content, max_chunk_chars)

    if len(chunks) > 1:
        print(f"    邮件正文 {len(content)} 字符 → 拆分为 {len(chunks)} 块翻译")

    translation_parts: List[str] = []

    for chunk_idx, chunk in enumerate(chunks):
        prompt = render_prompt(TRANSLATION_SYSTEM_PROMPT, content=chunk)

        result = llm.chat(
            prompt,
            temperature=cfg.translation_temperature,
            max_tokens=TRANSLATION_MAX_OUTPUT_TOKENS,
        )

        if result:
            translation_parts.append(result)
        else:
            translation_parts.append(
                f"> 原文：[第 {chunk_idx + 1}/{len(chunks)} 块翻译失败]\n"
                f"> 译文：[翻译调用失败，请检查日志]"
            )
            logger.warning(
                f"[Translator] 邮件 {index} 第 {chunk_idx + 1}/{len(chunks)} 块翻译失败"
            )

    translation = "\n\n".join(translation_parts)

    # 包装为 Markdown 区块
    subject = mail.get("subject", "")
    chunk_info = f"（共 {len(chunks)} 块）" if len(chunks) > 1 else ""
    return (
        f"\n---\n\n#### 邮件 {index}：{subject} — 双语对照{chunk_info}\n\n"
        f"{translation}\n"
    )


def translate_emails(
    cfg: Config,
    llm: LLMClient,
    emails: List[Dict],
) -> str:
    """
    对邮件列表逐封翻译，返回完整双语对照报告。
    """
    if not cfg.enable_translation or not emails:
        return ""

    total = len(emails)
    print(f"[Pipeline] 开始双语翻译: {total} 封邮件")

    parts = [
        "\n\n---\n\n"
        "## 📖 双语对照翻译\n"
        f"以下为 {total} 封邮件的原文与中英文译文逐行对照。\n"
    ]

    for i, mail in enumerate(emails):
        index = i + 1
        print(f"  [翻译 {index}/{total}] {mail.get('subject', '')[:40]} ...")
        block = translate_single_email(llm, cfg, mail, index)
        if block:
            parts.append(block)

    return "\n".join(parts)
