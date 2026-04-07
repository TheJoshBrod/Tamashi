import json
import urllib.request
import urllib.parse

from core.config import settings
from tools.registry import tool


@tool
def web_search(query: str) -> str:
    """Search the web and return the top results for a query."""
    if not settings.tavily_api_key:
        return "Error: TAVILY_API_KEY is not set."

    payload = json.dumps({
        "query": query,
        "max_results": 5,
        "include_answer": True,
    }).encode()

    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={
            "Authorization": f"Bearer {settings.tavily_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        return f"Search failed: {exc}"

    lines: list[str] = []

    if data.get("answer"):
        lines.append(f"Answer: {data['answer']}\n")

    for r in data.get("results", []):
        lines.append(f"- {r['title']}\n  {r['url']}\n  {r.get('content', '')[:200]}")

    return "\n".join(lines) if lines else "No results found."
