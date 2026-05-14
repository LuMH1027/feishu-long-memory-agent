"""LLM决策抽取模块"""
import json
import os
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv(override=True)


DECISION_EXTRACTION_PROMPT = """你是一个专业的决策分析助手。请从以下飞书群聊消息中提取结构化的项目决策信息。

请严格按照以下JSON格式输出，不要输出任何其他内容：

{
    "is_decision": true/false,
    "topic": "决策主题",
    "conclusion": "决策结论",
    "reason": "决策原因（如果有）",
    "project": "相关项目（如果有）",
    "preferred_terms": ["推荐的术语/方案列表"],
    "rejected_terms": ["废弃的术语/方案列表"],
    "deadline": "截止日期（如果有，格式：YYYY-MM-DD）",
    "confidence": 0.0-1.0
}

注意：
1. is_decision: 只有明确表达团队决策、确认、统一意见的消息才是true
2. topic: 决策的核心主题，如"部署环境选择"、"周报发送对象"等
3. conclusion: 决策的最终结论
4. reason: 做出决策的原因
5. project: 相关的项目名称
6. preferred_terms: 推荐使用的术语、方案、工具等
7. rejected_terms: 废弃的术语、方案、工具等
8. deadline: 决策的截止日期（如果有明确提到）
9. confidence: 判断的置信度，0.0-1.0

示例1：
输入："以后 project-a 统一用 prod 部署，不再使用 staging"
输出：
{
    "is_decision": true,
    "topic": "部署环境选择",
    "conclusion": "project-a 以后统一用 prod 部署",
    "reason": null,
    "project": "project-a",
    "preferred_terms": ["prod"],
    "rejected_terms": ["staging"],
    "deadline": null,
    "confidence": 0.95
}

示例2：
输入："周报以后发给 B，不再发给 A"
输出：
{
    "is_decision": true,
    "topic": "周报发送对象",
    "conclusion": "周报以后发给 B",
    "reason": null,
    "project": null,
    "preferred_terms": ["B"],
    "rejected_terms": ["A"],
    "deadline": null,
    "confidence": 0.9
}

示例3：
输入："今天天气不错啊"
输出：
{
    "is_decision": false,
    "topic": null,
    "conclusion": null,
    "reason": null,
    "project": null,
    "preferred_terms": [],
    "rejected_terms": [],
    "deadline": null,
    "confidence": 0.95
}

现在请分析以下消息：
{message}
"""


def _get_openai_client():
    """获取OpenAI客户端"""
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("未安装 openai，请先执行 pip install openai")

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    if not api_key:
        raise RuntimeError("缺少 OPENAI_API_KEY 环境变量")

    return OpenAI(api_key=api_key, base_url=base_url)


def _extract_json_from_response(raw_text: str) -> dict[str, Any]:
    """从 LLM 原始响应中健壮提取 JSON 对象。

    处理常见情况：
    - 纯 JSON: {"key": "value"}
    - Markdown 代码块: ```json {...} ``` 或 ``` {...} ```
    - 带前导/尾随文本: Some text {"key": "value"} more text
    - 模型拒绝输出 JSON 时返回空字典
    """
    import re

    if not raw_text or not raw_text.strip():
        raise ValueError("LLM 返回空响应")

    text = raw_text.strip()

    # 1) 尝试直接解析（最快路径）
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2) 提取 markdown 代码块中的 JSON
    fenced_patterns = [
        r'```(?:json)?\s*\n?(.*?)\n?```',  # ```json ... ``` 或 ``` ... ```
    ]
    for pat in fenced_patterns:
        matches = re.findall(pat, text, re.DOTALL)
        for m in matches:
            try:
                return json.loads(m.strip())
            except json.JSONDecodeError:
                continue

    # 3) 在文本中找到第一个平衡的 { ... } 块
    start = text.find('{')
    if start == -1:
        raise ValueError(f"响应中未找到 JSON 对象: {text[:200]}")

    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue  # 继续找下一个 {

    raise ValueError(f"无法从响应中提取有效 JSON: {text[:200]}")


def extract_decision_with_llm(message: str, model: Optional[str] = None) -> dict[str, Any]:
    """
    使用LLM从消息中抽取决策信息

    Args:
        message: 飞书消息内容
        model: 使用的模型（可选，默认使用环境变量配置）

    Returns:
        抽取的决策信息字典
    """
    try:
        client = _get_openai_client()
        model = model or os.getenv("LLM_MODEL", "gpt-3.5-turbo")

        prompt = DECISION_EXTRACTION_PROMPT.replace("{message}", message)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个专业的决策分析助手，专门从群聊消息中提取结构化的项目决策信息。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=500
        )

        # 提取响应内容
        raw_content = response.choices[0].message.content or ""
        print(f"[LLM抽取] 原始响应 ({len(raw_content)} 字符): {raw_content[:300]}", flush=True)

        # 健壮解析 JSON
        result = _extract_json_from_response(raw_content)

        normalized = _normalize_result(result)
        print(f"[LLM抽取] is_decision={normalized['is_decision']} "
              f"topic={normalized.get('topic')} "
              f"confidence={normalized.get('confidence')}", flush=True)
        return normalized

    except json.JSONDecodeError as e:
        print(f"[LLM抽取] JSON解析失败: {e}", flush=True)
        return {
            "is_decision": False,
            "error": f"JSON解析失败: {str(e)}",
            "raw_response": raw_content if 'raw_content' in locals() else None
        }
    except Exception as e:
        print(f"[LLM抽取] 调用异常: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return {
            "is_decision": False,
            "error": f"LLM调用失败: {str(e)}"
        }


def _normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    """规范化LLM返回的结果"""
    # 确保所有必需字段存在
    normalized = {
        "is_decision": bool(result.get("is_decision", False)),
        "topic": result.get("topic"),
        "conclusion": result.get("conclusion"),
        "reason": result.get("reason"),
        "project": result.get("project"),
        "preferred_terms": result.get("preferred_terms", []),
        "rejected_terms": result.get("rejected_terms", []),
        "deadline": result.get("deadline"),
        "confidence": float(result.get("confidence") or 0.5)
    }

    # 确保列表字段是列表
    if not isinstance(normalized["preferred_terms"], list):
        normalized["preferred_terms"] = []
    if not isinstance(normalized["rejected_terms"], list):
        normalized["rejected_terms"] = []

    # 过滤空值
    normalized["preferred_terms"] = [t for t in normalized["preferred_terms"] if t]
    normalized["rejected_terms"] = [t for t in normalized["rejected_terms"] if t]

    return normalized


def extract_decision_with_rules_fallback(message: str, use_llm: bool = True) -> dict[str, Any]:
    """
    使用LLM抽取决策，失败时降级为规则抽取

    Args:
        message: 飞书消息内容
        use_llm: 是否使用LLM（默认True）

    Returns:
        抽取的决策信息字典
    """
    if use_llm:
        try:
            result = extract_decision_with_llm(message)
            if result.get("is_decision"):
                return result
            # 如果LLM判断不是决策，返回结果
            return result
        except Exception:
            pass

    # 降级为规则抽取
    from backend.routers.feishu import extract_decision, is_decision_message

    if not is_decision_message(message):
        return {
            "is_decision": False,
            "topic": None,
            "conclusion": None,
            "reason": None,
            "project": None,
            "preferred_terms": [],
            "rejected_terms": [],
            "deadline": None,
            "confidence": 0.0
        }

    # 使用规则抽取
    decision = extract_decision(message)

    return {
        "is_decision": True,
        "topic": decision.get("topic"),
        "conclusion": decision.get("conclusion"),
        "reason": decision.get("reason"),
        "project": decision.get("project"),
        "preferred_terms": decision.get("preferred_terms", []),
        "rejected_terms": decision.get("rejected_terms", []),
        "deadline": None,
        "confidence": 0.7  # 规则抽取的置信度较低
    }


# ── LLM 消息意图分类 ────────────────────────────────────

INTENT_CLASSIFICATION_PROMPT = """你是一个专业的飞书群聊消息分析助手。请将以下消息分类为以下意图之一，并输出JSON。

意图类型：
- decision_new: 明确提出了一个新的团队决策、规范或约定（如"以后用XXX"、"统一用XXX"）
- decision_revise: 修改或更正已有决策（如"不对，XXX改成YYY"、"更正，XXX"、暗示之前方案不对）
- decision_confirm: 表示同意已有建议或确认已有决策（如"那就按XXX说的做"、"同意"、"OK就用这个"）
- decision_repeal: 明确废除或放弃已有决策（如"废弃XXX"、"不再使用XXX"、"取消XXX"）
- unclear: 有决策意图但信息不足（如模糊引用"用那个新的"、只说问题没给方案、多人讨论无共识）
- query: 提问、查找信息（如"怎么XXX"、"查一下XXX"、"之前XXX是什么"）
- chat: 普通闲聊、讨论、信息同步，不涉及决策意图

输出格式（严格JSON，不要其他内容）：
{
    "intent": "decision_new|decision_revise|decision_confirm|decision_repeal|unclear|query|chat",
    "confidence": 0.0-1.0,
    "reason": "分类理由（一句话）",
    "clarification_question": "追问内容（仅unclear时需要，其他为null）",
    "suggested_options": ["选项1", "选项2"] (仅unclear时最多3个选项，其他为空数组)
}

示例1：
输入："那就按张工说的做吧"
输出：{"intent": "decision_confirm", "confidence": 0.92, "reason": "明确表示同意按张工方案执行", "clarification_question": null, "suggested_options": []}

示例2：
输入："以后用那个新的部署方式"
输出：{"intent": "unclear", "confidence": 0.85, "reason": "有决策意图但方案不明确", "clarification_question": "你说的「新的部署方式」是指 k8s 还是 docker-compose？", "suggested_options": ["k8s部署", "docker-compose部署", "等有结论再说"]}

现在请分析以下消息：
{message}
"""


def classify_message_intent(message: str, model: Optional[str] = None) -> dict[str, Any]:
    """
    使用 LLM 对飞书消息进行 7 类意图分类

    Returns:
        {"intent": str, "confidence": float, "reason": str,
         "clarification_question": str|null, "suggested_options": list,
         "fallback": bool, "fallback_reason": str}
    """
    try:
        client = _get_openai_client()
        model = model or os.getenv("LLM_MODEL", "gpt-3.5-turbo")
        base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

        prompt = INTENT_CLASSIFICATION_PROMPT.replace("{message}", message)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个专业的飞书群聊消息分类助手。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=300,
        )

        raw_content = response.choices[0].message.content or ""
        print(f"[LLM分类] 原始响应 ({len(raw_content)} 字符): {raw_content[:300]}", flush=True)

        result = _extract_json_from_response(raw_content)

        _reason = result.get('reason') or ''
        print(f"[LLM分类] intent={result.get('intent')} "
              f"confidence={result.get('confidence')} "
              f"reason={_reason[:60]}", flush=True)

        return {
            "intent": result.get("intent", "chat"),
            "confidence": float(result.get("confidence") or 0.5),
            "reason": result.get("reason", ""),
            "clarification_question": result.get("clarification_question"),
            "suggested_options": result.get("suggested_options", []),
            "fallback": False,
            "model": model,
            "base_url": base,
        }
    except Exception as e:
        print(f"[LLM分类] 调用失败 ({model or os.getenv('LLM_MODEL', '?')} @ "
              f"{os.getenv('OPENAI_BASE_URL', '?')}): {e}", flush=True)
        import traceback
        traceback.print_exc()
        return {
            "intent": "chat",
            "confidence": 0.0,
            "reason": f"LLM调用失败，回退规则模式: {str(e)[:80]}",
            "clarification_question": None,
            "suggested_options": [],
            "fallback": True,
            "fallback_reason": str(e)[:100],
        }


def batch_extract_decisions(messages: list[str], use_llm: bool = True) -> list[dict[str, Any]]:
    """
    批量抽取决策信息

    Args:
        messages: 消息列表
        use_llm: 是否使用LLM

    Returns:
        决策信息列表
    """
    results = []
    for message in messages:
        result = extract_decision_with_rules_fallback(message, use_llm=use_llm)
        results.append(result)
    return results


def extract_deadline(message: str) -> Optional[str]:
    """
    从消息中提取截止日期

    Args:
        message: 消息内容

    Returns:
        截止日期字符串（YYYY-MM-DD格式）或None
    """
    import re
    from datetime import datetime, timedelta

    # 常见日期模式
    patterns = [
        # 明确日期：2024-05-10、2024/05/10、5月10日
        r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})',
        r'(\d{1,2})月(\d{1,2})[日号]',
        # 相对日期：下周三、明天、后天
        r'(下周[一二三四五六日天])',
        r'(明天|后天|大后天)',
        r'(\d+天后)',
        # 截止日期关键词
        r'截止[日时]?[期是]?[:：]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
        r'Deadline[:：]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
    ]

    message_lower = message.lower()

    for pattern in patterns:
        match = re.search(pattern, message_lower)
        if match:
            groups = match.groups()

            # 处理明确日期
            if len(groups) == 3 and groups[0].isdigit():
                try:
                    year = int(groups[0])
                    month = int(groups[1])
                    day = int(groups[2])
                    if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                        return f"{year}-{month:02d}-{day:02d}"
                except ValueError:
                    pass

            # 处理中文日期
            if len(groups) == 2 and groups[0].isdigit():
                try:
                    month = int(groups[0])
                    day = int(groups[1])
                    if 1 <= month <= 12 and 1 <= day <= 31:
                        year = datetime.now().year
                        return f"{year}-{month:02d}-{day:02d}"
                except ValueError:
                    pass

            # 处理相对日期
            if len(groups) == 1:
                text = groups[0]
                today = datetime.now()

                if text == "明天":
                    target = today + timedelta(days=1)
                elif text == "后天":
                    target = today + timedelta(days=2)
                elif text == "大后天":
                    target = today + timedelta(days=3)
                elif "下周" in text:
                    # 计算下周几
                    weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
                    for char, wd in weekday_map.items():
                        if char in text:
                            days_ahead = wd - today.weekday() + 7
                            target = today + timedelta(days=days_ahead)
                            break
                    else:
                        continue
                elif text.endswith("天后"):
                    try:
                        days = int(text[:-2])
                        target = today + timedelta(days=days)
                    except ValueError:
                        continue
                else:
                    continue

                return target.strftime("%Y-%m-%d")

    return None
