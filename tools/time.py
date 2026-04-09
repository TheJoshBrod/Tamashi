from datetime import datetime
from tools.registry import tool

@tool
def get_current_time() -> str:
    """Get the current local date and time.
    Use this when the user asks for the current time, date, or day of the week, or when you need to know the exact timestamp for a relative query (like 'remind me tomorrow').
    """
    now = datetime.now()
    # Format e.g., "2026-04-09 15:58:30 (Thursday)"
    return now.strftime("%Y-%m-%d %H:%M:%S (%A)")
