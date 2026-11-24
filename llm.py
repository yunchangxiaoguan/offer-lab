"""Optional provider adapter. Credentials stay in the local environment."""

import json
import os
import urllib.error
import urllib.request


def available():
    return bool(os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"))


def complete(system, user):
    deepseek = bool(os.getenv("DEEPSEEK_API_KEY"))
    key = os.getenv("DEEPSEEK_API_KEY" if deepseek else "OPENAI_API_KEY")
    if not key:
        raise ValueError("本机没有配置模型密钥，可以选择本机生成。")
    url = "https://api.deepseek.com/v1" if deepseek else "https://api.openai.com/v1"
    model = os.environ.get("OFFER_MODEL") or (
        "deepseek-chat" if deepseek else "gpt-4.1-mini"
    )
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 8192,
    }
    request = urllib.request.Request(
        url + "/chat/completions",
        method="POST",
        data=json.dumps(data).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=200) as response:
            result = json.load(response)["choices"][0]
        if result.get("finish_reason") == "length":
            raise ValueError(
                "模型输出达到长度上限，请缩短单项目说明后重新生成，或使用本机生成。"
            )
        content = result["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("模型返回了空正文。")
        return content
    except urllib.error.HTTPError as exc:
        raise ValueError(
            f"模型服务返回 HTTP {exc.code}，请核对配置或改选本机生成。"
        ) from None
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError):
        raise ValueError("暂时无法取得模型回复，请重试或改选本机生成。") from None
