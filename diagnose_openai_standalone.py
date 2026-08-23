"""Standalone OpenAI auth diagnostic for TutAIR.

This script intentionally lives outside the TutAIR viewer code path. It loads the
same local API key source, sends one tiny request, and redacts key-looking text
from all output.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def sanitize(text: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    sanitized = text
    if api_key:
        sanitized = sanitized.replace(api_key, "<redacted-openai-key>")
    return re.sub(r"sk-[A-Za-z0-9_-]+", "sk-<redacted>", sanitized)


def set_env_line(line: str, override: bool = False) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return False
    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip().strip('"').strip("'")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        return False
    if override:
        os.environ[key] = value
    else:
        os.environ.setdefault(key, value)
    return True


def load_env() -> None:
    if ENV_PATH.is_file():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            set_env_line(line, override=True)
        return
    if ENV_PATH.is_dir():
        for child in ENV_PATH.iterdir():
            if not child.is_file():
                continue
            loaded = False
            for line in child.read_text(encoding="utf-8").splitlines():
                loaded = set_env_line(line, override=True) or loaded
            if not loaded:
                set_env_line(child.name, override=False)


def main() -> int:
    load_env()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("TUTAIR_AI_MODEL", "gpt-4o-mini").strip()
    print(f"checked_env_path={ENV_PATH}")
    print(f"api_key_found={bool(api_key)}")
    print(f"api_key_prefix={(api_key[:7] + '...') if api_key else 'missing'}")
    print(f"api_key_length={len(api_key)}")
    print(f"model={model}")
    print(f"endpoint={OPENAI_URL}")
    print("authorization_header=Bearer <redacted>")
    if not api_key:
        print("HTTP status code: not-sent")
        print("Response body: OPENAI_API_KEY was not found")
        return 1

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Say hello"}],
        "temperature": 0,
    }
    request = Request(
        OPENAI_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
            print(f"HTTP status code: {response.status}")
            print(f"Response body: {sanitize(body)}")
            return 0
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP status code: {exc.code}")
        print(f"Response body: {sanitize(body)}")
        return 1
    except URLError as exc:
        print("HTTP status code: network-error")
        print(f"Response body: {sanitize(str(exc))}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
