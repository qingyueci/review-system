from __future__ import annotations

import threading
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.parse import quote
import webbrowser

import uvicorn

from review_app.api import SERVICE_TOKEN, SITE_URL


LOCAL_STATUS_URL = "http://127.0.0.1:8765/api/status"


def service_is_running() -> bool:
    request = Request(
        LOCAL_STATUS_URL,
        headers={"X-Review-Token": SERVICE_TOKEN},
    )
    try:
        with urlopen(request, timeout=1.5) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def open_site(delay: float = 0) -> None:
    if delay:
        time.sleep(delay)
    webbrowser.open(f"{SITE_URL}/#token={quote(SERVICE_TOKEN)}")


def main() -> None:
    if service_is_running():
        open_site()
        return
    threading.Thread(target=open_site, args=(1.2,), daemon=True).start()
    uvicorn.run(
        "review_app.api:app",
        host="127.0.0.1",
        port=8765,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
