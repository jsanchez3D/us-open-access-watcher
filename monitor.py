import hashlib
import json
import os
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup


STATE_FILE = Path("state.json")

PAGES = {
    "registration": "https://fanpass.usopen.org/register",
    "fan_access": "https://www.usopen.org/en_US/fan-week/fan-access-pass.html",
    "fan_week": "https://www.usopen.org/en_US/about/us_open_fan_week.html",
}

OPEN_MARKERS = [
    "register below for access to fan week",
    "sign me up for a fan access pass",
]

CLOSED_MARKERS = [
    "new registrations for fan access pass are now closed",
    "registrations for fan access pass are now closed",
    "registration is now closed",
]


def fetch_page(url):
    response = requests.get(
        url,
        timeout=30,
        headers={
            "User-Agent": (
                "Mozilla/5.0 USOpenFanWeekPersonalMonitor/1.0"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = " ".join(soup.stripped_strings)
    text = re.sub(r"\s+", " ", text)

    return text


def page_hash(text):
    # Remove countdown wording that may change daily
    text = re.sub(
        r"\b\d+\s+days?\s+left\s+until\s+fan\s+week\b",
        "",
        text,
        flags=re.IGNORECASE,
    )

    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def registration_status(text):
    lower = text.lower()

    if any(marker in lower for marker in CLOSED_MARKERS):
        return "CLOSED"

    if any(marker in lower for marker in OPEN_MARKERS):
        return "OPEN"

    return "UNKNOWN"


def send_pushover(title, message, url):
    token = os.environ.get("PUSHOVER_TOKEN")
    user = os.environ.get("PUSHOVER_USER")

    if not token or not user:
        print("Pushover secrets not configured yet.")
        return

    response = requests.post(
        "https://api.pushover.net/1/messages.json",
        data={
            "token": token,
            "user": user,
            "title": title,
            "message": message,
            "url": url,
            "url_title": "Open official US Open page",
            "priority": 1,
        },
        timeout=30,
    )

    response.raise_for_status()


def load_state():
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def main():
    old_state = load_state()
    new_state = {}
    first_run = not bool(old_state)

    for name, url in PAGES.items():
        try:
            text = fetch_page(url)

            info = {
                "hash": page_hash(text)
            }

            if name == "registration":
                info["status"] = registration_status(text)

            new_state[name] = info

            previous = old_state.get(name, {})

            if first_run and name == "registration":
                status = info["status"]

                send_pushover(
                    "US Open monitor is running",
                    (
                        "Monitoring is active. "
                        f"Fan Access Pass registration "
                        f"currently appears: {status}."
                    ),
                    url,
                )

            elif name == "registration":
                old_status = previous.get("status")
                new_status = info["status"]

                if (
                    old_status
                    and new_status != old_status
                ):
                    if new_status == "OPEN":
                        send_pushover(
                            "US OPEN ACCESS ALERT",
                            (
                                "VERIFIED OFFICIAL SIGNAL: "
                                "Fan Access Pass registration "
                                "appears to have reopened. "
                                "Open the official page now and "
                                "confirm availability."
                            ),
                            url,
                        )

                    elif new_status == "CLOSED":
                        send_pushover(
                            "US Open registration update",
                            (
                                "Official Fan Access Pass page "
                                "now appears CLOSED."
                            ),
                            url,
                        )

                    else:
                        send_pushover(
                            "US Open registration page changed",
                            (
                                "The registration status could "
                                "not be classified automatically. "
                                "Check the official page."
                            ),
                            url,
                        )

            old_hash = previous.get("hash")

            if (
                not first_run
                and name != "registration"
                and old_hash
                and old_hash != info["hash"]
            ):
                send_pushover(
                    "US Open official page changed",
                    (
                        f"The official {name.replace('_', ' ')} "
                        "page changed. Review it for Fan Week "
                        "access, capacity, RSVP, standby, or "
                        "entry-policy updates."
                    ),
                    url,
                )

            print(
                f"{name}: OK "
                f"{info.get('status', '')}"
            )

        except Exception as exc:
            print(f"{name}: ERROR: {exc}")

            # Keep the previous known state if a page
            # temporarily fails.
            if name in old_state:
                new_state[name] = old_state[name]

    save_state(new_state)


if __name__ == "__main__":
    main()
