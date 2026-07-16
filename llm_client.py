"""
llm_client.py
================================================================================
DeepSeek LLM 客户端封装层。

针对 deepseek-v4-flash 模型特性做了以下规范化处理：
  1. 统一的客户端工厂（单例，避免重复创建）
  2. 指数退避重试机制（应对 429 / 5xx 等瞬时错误）
  3. Token 估算工具（用于上下文长度预算管理）
  4. 动态批处理：根据 token 预算自动裁剪每批邮件数量，
     确保单次请求不会超出 deepseek-v4-flash 的 128K 上下文窗口
  5. 统一的错误返回格式
"""

import time
import json
import logging
from typing import List, Dict, Optional

import openai

from config import Config
from prompts import (
    render_prompt,
    SUMMARY_SYSTEM_PROMPT,
    SUMMARY_WITH_TRANSLATION_PROMPT,
)

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# Token 估算
# ═════════════════════════════════════════════════════════════════════════════
def estimate_tokens(text: str) -> int:
    """
    粗略估算字符串的 token 数量。

    deepseek-v4-flash 使用 BPE 分词器，经验值：
      - 英文 ≈ 4 字符 / token
      - 中文 ≈ 1.5 字符 / token
      - 混合内容取中间值 ≈ 2.5 字符 / token

    此处采用保守估算（偏低），配合上下文安全余量使用。
    """
    if not text:
        return 0
    # 统计中文字符数
    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_count = len(text) - cjk_count
    # 中文 ~1.5 字/token, 英文 ~4 字符/token
    return int(cjk_count / 1.5 + other_count / 4.0) + 1


# ═════════════════════════════════════════════════════════════════════════════
# 客户端封装
# ═════════════════════════════════════════════════════════════════════════════
class LLMClient:
    """DeepSeek API 客户端，封装重试与上下文管理逻辑。"""

    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._client: Optional[openai.OpenAI] = None

    @property
    def client(self) -> openai.OpenAI:
        """惰性初始化 OpenAI 兼容客户端（单例）。"""
        if self._client is None:
            self._client = openai.OpenAI(
                api_key=self._cfg.deepseek_api_key,
                base_url=self._cfg.deepseek_base_url,
            )
        return self._client

    # ──────────────────────────────────────────────────────────────────────────
    # 核心调用（带重试）
    # ──────────────────────────────────────────────────────────────────────────
    def chat(
        self,
        system_prompt: str,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        发送单轮对话请求，带指数退避重试。

        Args:
            system_prompt: 完整的系统提示词（已渲染占位符）。
            temperature: 覆盖配置中的默认温度。
            max_tokens: 覆盖配置中的默认输出上限。
        Returns:
            模型回复文本。若所有重试均失败，返回空字符串。
        """
        temp = temperature if temperature is not None else self._cfg.summary_temperature
        out_tokens = max_tokens if max_tokens is not None else self._cfg.max_output_tokens

        last_error: Optional[Exception] = None
        for attempt in range(1, self._cfg.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self._cfg.deepseek_model,
                    messages=[{"role": "system", "content": system_prompt}],
                    temperature=temp,
                    max_tokens=out_tokens,
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                last_error = e
                if attempt < self._cfg.max_retries:
                    delay = self._cfg.retry_base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"[LLM] 第 {attempt}/{self._cfg.max_retries} 次调用失败，"
                        f"{delay:.0f}s 后重试: {e}"
                    )
                    time.sleep(delay)

        logger.error(f"[LLM] 全部 {self._cfg.max_retries} 次重试均失败: {last_error}")
        return ""

    # ──────────────────────────────────────────────────────────────────────────
    # 单封邮件 token 预算兜底
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def truncate_email_to_budget(
        mail: Dict,
        token_budget: int,
    ) -> Dict:
        """
        当单封邮件的 JSON token 数超出预算时，截断 body_preview 以适配。
        返回截断后的邮件副本（不修改原对象）。

        用于处理极端情况：某封邮件即便单独成批也超出 128K 预算
        （例如 WoS 推送 100+ 篇文章的超长邮件）。
        """
        import copy
        mail_copy = copy.deepcopy(mail)
        body = mail_copy.get("body_preview", "")

        # 二分查找最大可保留字符数
        lo, hi = 0, len(body)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            mail_copy["body_preview"] = body[:mid]
            test_json = json.dumps(mail_copy, ensure_ascii=False)
            if estimate_tokens(test_json) <= token_budget:
                lo = mid
            else:
                hi = mid - 1

        truncated_len = lo
        if truncated_len < len(body):
            mail_copy["body_preview"] = body[:truncated_len]
            # 尝试在截断处找到行边界，避免半行截断
            last_newline = mail_copy["body_preview"].rfind("\n")
            if last_newline > truncated_len * 0.8:
                mail_copy["body_preview"] = mail_copy["body_preview"][:last_newline]
            mail_copy["_truncated"] = True
            mail_copy["_original_chars"] = len(body)
            mail_copy["_retained_chars"] = len(mail_copy["body_preview"])
            logger.warning(
                f"[LLM] 邮件 '{mail.get('subject', '')[:40]}' 超出 token 预算，"
                f"正文从 {len(body)} 截断至 {len(mail_copy['body_preview'])} 字符"
            )
        else:
            mail_copy["body_preview"] = body

        return mail_copy

    # ──────────────────────────────────────────────────────────────────────────
    # 动态批处理
    # ──────────────────────────────────────────────────────────────────────────
    def compute_dynamic_batches(
        self,
        emails: List[Dict],
        system_prompt_template: str,
    ) -> List[List[Dict]]:
        """
        根据 token 预算动态计算批次大小，确保每批邮件 + 提示词
        不会超出 deepseek-v4-flash 的有效输入预算。

        逻辑：
          1. 估算模板自身（不含邮件数据）的 token 数
          2. 对每封邮件估算其 JSON 序列化后的 token 数
          3. 若单封邮件超出整个预算 → 截断 body_preview 兜底
          4. 贪心填充：依次将邮件加入当前批次，直到 token 预算耗尽
             或达到 summary_batch_size 上限
        """
        if not emails:
            return []

        # 估算模板空渲染的 token 开销（不含邮件数据）
        empty_prompt = render_prompt(
            system_prompt_template, emails="[]", start_index="1"
        )
        template_tokens = estimate_tokens(empty_prompt)
        budget = self._cfg.effective_input_budget - template_tokens

        if budget <= 0:
            logger.warning("[LLM] 提示词模板已超出上下文预算，强制单封批次")
            return [[e] for e in emails]

        # ── 安全兜底：截断超长邮件 ──
        safe_emails: List[Dict] = []
        for mail in emails:
            mail_json = json.dumps(mail, ensure_ascii=False)
            mail_tokens = estimate_tokens(mail_json)
            if mail_tokens > budget:
                mail = self.truncate_email_to_budget(mail, budget)
            safe_emails.append(mail)

        batches: List[List[Dict]] = []
        current_batch: List[Dict] = []
        current_tokens = 0

        for mail in safe_emails:
            mail_json = json.dumps(mail, ensure_ascii=False)
            mail_tokens = estimate_tokens(mail_json)

            # 判断是否需要开启新批次：
            #   a) 当前批次 + 该邮件超出 token 预算
            #   b) 当前批次已达 summary_batch_size 上限
            if current_batch and (
                current_tokens + mail_tokens > budget
                or len(current_batch) >= self._cfg.summary_batch_size
            ):
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0

            current_batch.append(mail)
            current_tokens += mail_tokens

        if current_batch:
            batches.append(current_batch)

        logger.info(
            f"[LLM] 动态分批完成: {len(emails)} 封邮件 → {len(batches)} 批"
            f"（预算 {budget} tokens / 模板 {template_tokens} tokens）"
        )
        return batches

    # ──────────────────────────────────────────────────────────────────────────
    # 摘要流水线
    # ──────────────────────────────────────────────────────────────────────────
    def summarize_emails(
        self,
        emails: List[Dict],
        with_translation: bool = False,
    ) -> str:
        """
        对邮件列表进行分批摘要，返回完整 Markdown 报告。

        Args:
            emails: 邮件列表
            with_translation: 是否使用内联双语摘要提示词（v1.2 默认）
        """
        if not emails:
            return (
                "### 每日邮件汇总\n"
                "**总览：共 0 封邮件**\n\n---\n\n今日没有收到新邮件。"
            )

        # 根据是否启用翻译选择提示词
        prompt_template = (
            SUMMARY_WITH_TRANSLATION_PROMPT if with_translation
            else SUMMARY_SYSTEM_PROMPT
        )

        total = len(emails)
        batches = self.compute_dynamic_batches(emails, prompt_template)

        mode_tag = "（中英双语）" if with_translation else ""
        report_parts = [
            f"### 每日邮件汇总\n**总览：共 {total} 封邮件{mode_tag}**\n\n---"
        ]

        print(f"[Pipeline] 开始分批摘要{mode_tag}: {total} 封邮件 → {len(batches)} 批")

        processed = 0
        for batch_idx, batch in enumerate(batches):
            start_index = processed + 1
            end_index = processed + len(batch)
            print(
                f"  [批次 {batch_idx + 1}/{len(batches)}] "
                f"邮件 {start_index}–{end_index} ..."
            )

            emails_json = json.dumps(batch, ensure_ascii=False, indent=2)
            prompt = render_prompt(
                prompt_template,
                emails=emails_json,
                start_index=start_index,
            )

            # 摘要输出使用更充足的 max_tokens（中文摘要会增加输出量）
            result = self.chat(prompt, max_tokens=self._cfg.summary_max_output_tokens)
            if result:
                report_parts.append(result)
            else:
                report_parts.append(
                    f"\n---\n\n#### 处理邮件 {start_index}–{end_index} 时出错\n"
                    f"- **错误**: 所有重试均失败，请检查日志。\n\n---"
                )

            processed += len(batch)

        return "\n".join(report_parts)
