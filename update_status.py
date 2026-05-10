#!/usr/bin/env python3
"""
Strait of Hormuz — hourly status updater
Calls Claude (with web_search) to determine current shipping status,
then patches the JSON data island in index.html.

Required env var: ANTHROPIC_API_KEY
"""

import anthropic
import json
import re
import sys
from datetime import datetime, timezone

HTML_FILE = "index.html"

# Matches the data island script tag and its contents
DATA_TAG_RE = re.compile(
    r'(<script id="hormuz-data" type="application/json">)\s*(\{.*?\})\s*(</script>)',
    re.DOTALL,
)

PROMPT = """\
Search for the latest news about the Strait of Hormuz shipping situation.
Run these two searches:
  1. "Strait of Hormuz shipping open closed today"
  2. "Strait of Hormuz news latest"

Based on your findings, determine the current status — pick exactly one:
  OPEN        Normal or near-normal shipping traffic is flowing
  RESTRICTED  Technically passable but severely limited (escorts needed, active threats, very few ships)
  CLOSED      Officially blockaded; commercial shipping effectively stopped
  UNCLEAR     Conflicting reports or insufficient recent information

Return ONLY a single valid JSON object — no markdown fences, no explanation, nothing else:
{
  "status": "OPEN|RESTRICTED|CLOSED|UNCLEAR",
  "statusLabel": "Open|Restricted|Closed|Unclear",
  "summary": "2-4 sentence plain-English summary of the current situation.",
  "lastChecked": "<current UTC time as ISO 8601, e.g. 2026-05-10T14:00:00Z>",
  "trafficLevel": "e.g. '~6 ships/day (normal: ~120/day)'",
  "shipsStranded": <integer or null>,
  "sources": [
    {"title": "Headline or site name", "url": "https://...", "date": "YYYY-MM-DD"}
  ]
}
"""


def strip_cite_tags(text: str) -> str:
    return re.sub(r'<cite[^>]*>(.*?)</cite>', r'\1', text, flags=re.DOTALL).strip()


def get_status() -> dict:
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": PROMPT}]

    for attempt in range(10):
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 5,
            }],
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    text = block.text.strip()
                    m = re.search(r"\{.*\}", text, re.DOTALL)
                    if m:
                        data = json.loads(m.group())
                        if "summary" in data:
                            data["summary"] = strip_cite_tags(data["summary"])
                        return data
            raise ValueError(f"No JSON found in final response:\n{response.content}")

        # Continue the agentic loop (tool_use stop)
        messages.append({"role": "assistant", "content": response.content})

    raise RuntimeError("Reached max iterations without end_turn")


def patch_html(data: dict) -> None:
    with open(HTML_FILE, encoding="utf-8") as f:
        html = f.read()

    new_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    new_html, count = DATA_TAG_RE.subn(
        rf"\g<1>\n{new_json}\n\g<3>",
        html,
    )

    if count == 0:
        raise ValueError(
            'Could not find <script id="hormuz-data"> tag in index.html'
        )

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(new_html)


def main():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Fetching Strait of Hormuz status...", flush=True)
    try:
        data = get_status()
    except Exception as e:
        print(f"ERROR fetching status: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Status : {data['status']}", flush=True)
    print(f"Traffic: {data.get('trafficLevel', 'N/A')}", flush=True)
    print(f"Summary: {data.get('summary', '')[:120]}...", flush=True)

    try:
        patch_html(data)
    except Exception as e:
        print(f"ERROR patching index.html: {e}", file=sys.stderr)
        sys.exit(1)

    print("index.html updated successfully.", flush=True)


if __name__ == "__main__":
    main()
