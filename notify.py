"""Handle sending notifications via Pushover"""

import http.client
import os
import re
import urllib
from datetime import datetime

from loguru import logger as log

from models import EPG

PUSHOVER_TOKEN = os.getenv("PUSHOVER_TOKEN")
PUSHOVER_USR_KEY = os.getenv("PUSHOVER_USR_KEY")

sch = re.compile(r"[^a-zA-Z\d ]")


def notify(epg_event: EPG):
    """Send notification about finished recording."""
    url = (
        "https://www.filmweb.pl/film/"
        f"{sch.sub('+', epg_event.title)}-{epg_event.year}-{epg_event.fid}"
    )
    conn = http.client.HTTPSConnection("api.pushover.net:443")
    conn.request(
        "POST",
        "/1/messages.json",
        urllib.parse.urlencode(
            {
                "token": PUSHOVER_TOKEN,
                "user": PUSHOVER_USR_KEY,
                "html": 1,
                "title": epg_event.title,
                "timestamp": int(datetime.now().timestamp()),
                "priority": -1,
                "message": (
                    f"Movie <a href='{url}'>{epg_event.title}</a> ({epg_event.year}) "
                    "has just been recorded :)"
                ),
            }
        ),
        {"Content-type": "application/x-www-form-urlencoded"},
    )
    log.debug(f"Notifiaction sent?: {conn.getresponse().code}")
