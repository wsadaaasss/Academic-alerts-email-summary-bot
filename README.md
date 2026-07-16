原作者 https://github.com/Leeboom7/email-summary-bot

在原作者项目的基础上进行了修改，其核心目标是实现对 Google 学术、Web of Science、ScienceDirect 等学术平台的每日订阅邮件进行总结，这些邮件是依据我们所设置的关键词或者关注的作者来推送相关文献的。现有开源项目主要针对 arXiv 预发表网站进行跟踪总结，航空航天相关 arXiv 使用较少，故对原项目进行修改以满足自身学习科研使用。

得到的文献汇总示例如下：

<img width="2122" height="1474" alt="image" src="https://github.com/user-attachments/assets/213cd2be-77f5-49ce-b8c7-3becaa8a9f88" />


# 个人AI邮件总结助手 (Email Summary Bot)

> **v1.2** — 内联双语翻译优化（API 调用次数减少 90%，运行时间缩短 80%）

这是一个基于 GitHub Actions 的自动化工具，它能每日定时读取你指定的邮箱文件夹，使用 **DeepSeek** 的 `deepseek-v4-pro` 语言模型进行智能总结，并将一份邮件汇总报告发送到你的另一个邮箱。

## ✨ 特点

- **完全自动化**：每日定时运行，无需人工干预。
- **免费运行**：充分利用 GitHub Actions 的免费额度。
- **高度安全**：所有敏感信息均存储在 GitHub 的加密 Secrets 中。
- **高度可定制**：提示词、模型参数、批次大小均可通过环境变量配置。
- **无需服务器**：你不需要购买或维护任何服务器。
- **模块化架构** (v1.1)：代码拆分为配置、邮件获取、LLM 客户端、翻译、通知五个解耦模块。
- **上下文智能管理** (v1.1)：动态 token 估算 + 动态批处理，精准适配 128K 上下文窗口。
- **内联双语翻译** (v1.2)：在摘要阶段同时输出原文与中文摘要，单次 API 调用完成双语输出，运行时间缩短 80%。

## 📁 项目结构

```
Academic-alerts-email-summary-bot/
├── main.py              # 流水线入口（5阶段标准化流程）
├── config.py            # 集中式配置管理
├── prompts.py           # 提示词模板（内联双语摘要 + 兼容旧版）
├── email_fetcher.py     # IMAP 邮件获取 + HTML 解析
├── llm_client.py        # DeepSeek 客户端封装（重试 + 动态批处理 + token 估算）
├── translator.py        # 独立翻译模块（v1.2 标记为可选，默认关闭）
├── notifier.py          # SMTP 邮件发送
├── find_folders.py      # 邮箱文件夹查找工具
├── .github/workflows/
│   ├── main.yaml        # 每日定时工作流
│   └── test-smtp.yml    # SMTP 连接测试工作流
└── requirements.txt     # Python 依赖
```

## 🔄 流水线阶段（v1.2）

```
① Config.from_env()                 →  加载 & 校验配置
② fetch_emails_by_date()            →  IMAP 拉取目标日期邮件
③ llm.summarize_emails()            →  deepseek-v4-pro 分批摘要（默认含中文）
                                       论文条目下直接附中文摘要，单次 API 调用输出双语
④ translate_emails()                →  独立翻译模块（可选，默认关闭）
                                       仅当 ENABLE_SEPARATE_TRANSLATION=true 时运行
⑤ send_report()                    →  SMTP 发送合并报告
```

**v1.2 性能对比**（24 封邮件 + 1 封 WoS 50+ 篇）：

| 模式 | API 调用次数 | 预估运行时间 |
|------|-------------|-------------|
| v1.1 摘要 + 独立翻译 | ~55 次 | ~25 分钟 |
| **v1.2 内联翻译（默认）** | **5 次** | **~5 分钟** |

## 🚀 配置步骤

**1. Fork 本仓库**

点击仓库右上角的 "Fork" 按钮，将本仓库复制到你自己的 GitHub 账户下。

**2. 准备你的凭据**

你需要准备好以下信息：

- **① 用于读取的邮箱 (IMAP)**
    - `IMAP_EMAIL`: 你的邮箱地址。
    - `IMAP_AUTH_CODE`: 上述邮箱的 IMAP 授权码。
    - `IMAP_SERVER`: 你邮箱的 IMAP 服务器地址 (例如 `imap.qq.com`)。
    - `IMAP_PORT`: IMAP 服务器的 SSL 端口 (例如 `993`)。

- **② DeepSeek API 密钥**
    - `DEEPSEEK_API_KEY`: 前往 [DeepSeek 开放平台](https://platform.deepseek.com/api_keys) 创建你的 API 密钥。

- **③ 用于发送总结报告的邮箱 (SMTP)**
    - `SENDER_EMAIL`: 用于发送报告的邮箱。
    - `SENDER_AUTH_CODE`: 上述发件邮箱的 SMTP 授权码。
    - `RECEIVER_EMAIL`: 你希望接收总结报告的邮箱地址。
    - `SMTP_SERVER`: 发件邮箱的 SMTP 服务器地址 (例如 `smtp.qq.com`)。
    - `SMTP_PORT`: SMTP 服务器的端口 (例如 `465` 或 `587`)。

- **④ 目标文件夹**
    - `TARGET_FOLDER`: 运行 `find_folders.py` 脚本来找到它的"真实名称"。
      1. 在你的电脑上安装 Python。
      2. 下载本仓库中的 `find_folders.py`。
      3. 在终端中运行 `python find_folders.py`，并按提示操作。
      4. 脚本会打印出你所有的邮箱文件夹。找到你需要的文件夹，**完整地复制它引号内的那部分** (例如 `&UXZO1mWHTvZZOQ-/HKU`)。

**3. 在 GitHub 中设置 Secrets**

1.  在你 Fork 的仓库页面，点击 `Settings` -> `Secrets and variables` -> `Actions`。
2.  点击 `New repository secret`，依次创建以下**所有** Secrets：
    - `IMAP_EMAIL`
    - `IMAP_AUTH_CODE`
    - `IMAP_SERVER`
    - `IMAP_PORT`
    - `TARGET_FOLDER`
    - `DEEPSEEK_API_KEY`
    - `SENDER_EMAIL`
    - `SENDER_AUTH_CODE`
    - `RECEIVER_EMAIL`
    - `SMTP_SERVER`
    - `SMTP_PORT`

**4. 启用并测试 GitHub Actions**

1.  点击仓库顶部的 `Actions` 标签页。
2.  如有提示，请点击 "I understand my workflows, go ahead and enable them"。
3.  在左侧，点击 "Daily Email Summary" 工作流。
4.  在右侧，点击 "Run workflow" 下拉按钮，然后点击绿色的 "Run workflow" 按钮来手动触发一次任务。
5.  你可以点击运行记录，实时查看任务的执行日志。如果一切顺利，几分钟后你的收件箱就会收到第一封总结报告。

## ⚙️ 可选环境变量

以下环境变量可在 GitHub Actions 的 `main.yaml` 中覆盖默认值，无需修改代码：

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | DeepSeek 模型名 |
| `MAX_BODY_CHARS` | `80000` | 邮件正文最大保留字符数 |
| `SUMMARY_BATCH_SIZE` | `5` | 摘要批次大小上限 |
| `ENABLE_TRANSLATION` | `true` | v1.2: 是否在摘要中输出中文（设为 `false` 则纯英文摘要） |
| `ENABLE_SEPARATE_TRANSLATION` | `false` | v1.2: 是否额外运行独立翻译模块（会增加 API 调用次数） |

---

## 📋 变更日志

### v1.2 (2026-07-16)

#### 性能优化
- **内联双语翻译**：将翻译集成到摘要阶段，单次 API 调用同时输出论文原文与中文摘要
  - API 调用次数：~55 次（v1.1）→ **5 次（v1.2）**，减少 90%+
  - 整体运行时间：~25 分钟（v1.1）→ **~5 分钟（v1.2）**，缩短 80%
  - 输出格式：每篇论文下直接附"中文摘要"行，类似网页双语对照阅读体验
- **`summary_max_output_tokens` 提升至 16,384**：摘要现在包含中文内容，输出量增加

#### 行为变更（非破坏性）
- **`ENABLE_TRANSLATION` 语义调整**：从"是否运行独立翻译模块"变为"是否在摘要中输出中文"，默认仍为 `true`
- **新增 `ENABLE_SEPARATE_TRANSLATION`**：控制是否额外运行 v1.1 风格的独立翻译模块，默认 `false`
- **独立翻译模块保留**：可通过 `ENABLE_SEPARATE_TRANSLATION=true` 启用（适用于特殊场景）

#### 输出格式变化
- 摘要现在包含"中文主题"和"中文摘要"字段
- 文献 Alert 邮件每篇论文下新增"**中文摘要**："行（1-2 句中文概括研究方法/主要发现）

### v1.1 (2026-07-16)

#### 破坏性变更
- **模型迁移**：从 `deepseek-chat` 迁移至 `deepseek-v4-pro`（`deepseek-chat` 与 `deepseek-reasoner` 将于 2026/07/24 弃用）

#### 新功能
- **双语对照翻译模块** (`translator.py`)：调用 deepseek-v4-pro 对每封邮件逐行中英文互译，原文与译文交替排列，支持快速双语阅读与信息比对
- **长邮件分块翻译**：Web of Science 单期推送 50+ 篇论文时自动拆分为 token 预算内的分块，逐块翻译后拼接
- **可配置环境变量**：新增 `DEEPSEEK_MODEL`、`MAX_BODY_CHARS`、`ENABLE_TRANSLATION` 等可选参数

#### 架构重构
- **模块化拆分**：原 356 行单文件 `main.py` 拆分为 7 个职责单一的模块
  - `config.py` — 集中式配置管理（dataclass + 环境变量校验）
  - `prompts.py` — 提示词模板集中管理
  - `email_fetcher.py` — IMAP 邮件获取与 HTML 解析
  - `llm_client.py` — DeepSeek 客户端封装
  - `translator.py` — 中英文对照翻译
  - `notifier.py` — SMTP 邮件发送
  - `main.py` — 精简为 5 阶段标准化流水线入口
- **编码解码逻辑收敛**：原 4 处重复的 utf-8/gbk 降级逻辑合并为 `_safe_decode_bytes()`

#### 性能优化
- **动态 token 估算**：区分中英文（中文 ~1.5 字/token，英文 ~4 字符/token），精确管理 128K 上下文窗口
- **动态批处理**：贪心算法根据 token 预算自动裁剪每批邮件数量，避免上下文溢出
- **单封邮件超预算兜底**：极端超长邮件（100+ 篇论文）二分查找截断至 token 预算内，在行边界截断
- **`max_body_chars` 提升**：10,000 → 80,000，解决 WoS 30+ 篇论文推送被截断 72% 的问题
- **指数退避重试**：LLM API 调用增加 3 次重试（指数退避），应对 429/5xx 瞬时错误
- **翻译输出上限**：`TRANSLATION_MAX_OUTPUT_TOKENS = 32,768`，匹配翻译输出量 ≈ 输入 × 2 的特性

#### 其他改进
- **日志框架**：从 `print()` 升级为 `logging` 模块，支持级别区分
- **邮件样式**：报告邮件增加基础 CSS 样式，提升可读性
- **截断告警**：邮件截断时输出明确日志，告知用户哪些邮件被截断
- **`.gitignore`**：新增，忽略 `__pycache__/`

### v1.0

- 基于原作者 [Leeboom7/email-summary-bot](https://github.com/Leeboom7/email-summary-bot) 修改
- 实现 Google 学术、Web of Science、ScienceDirect 学术订阅邮件的每日总结
- 使用 `deepseek-chat` 模型
- GitHub Actions 每日定时运行
