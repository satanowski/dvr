"""Handle getting EPG from filmweb.pl"""

from datetime import datetime
from typing import Iterable

import requests
from bs4 import BeautifulSoup
from loguru import logger as log
from unidecode import unidecode

from models import RawEvent

BASE_URL = "https://www.filmweb.pl"
PROG_URL = f"{BASE_URL}/program-tv"

CHANNELS = (
    ("Fokus+TV", "Fokus TV"),
    ("Nowa+TV", "Nowa TV"),
    ("Polsat", "Polsat"),
    ("Puls+2", "PULS 2"),
    ("Stopklatka", "Stopklatka"),
    ("Super+Polsat", "Super Polsat"),
    ("TTV", "TTV"),
    ("TV+Puls", "TV Puls"),
    ("TV4", "TV4"),
    ("TV6", "TV6"),
    ("TVN", "TVN"),
    ("TVN+Siedem", "TVN 7"),
    ("TVP+1", "TVP1"),
    ("TVP+2", "TVP2"),
    ("TVP+Historia", "TVP Historia"),
    ("TVP+Kultura", "TVP Kultura"),
)


def wget(url: str) -> str:
    """HTTP get"""
    return requests.get(url, timeout=10).text


def get_epg_from_filmweb(dvrdb) -> Iterable[RawEvent]:
    """Parse filmweb page and extract EPG data"""
    for prog in dvrdb.get_channel_keys():
        log.debug(f"Getting epg for {prog}...")
        raw = wget(f"{PROG_URL}/{prog}")
        html = BeautifulSoup(raw, "html.parser")
        for div in html.findAll("div", {"data-type": "film"}):
            if not div.find("a"):
                continue
            sid = int(div.get("data-sid"))
            nextsid = sid + 1
            next_div = html.find("div", {"data-sid": nextsid}) or {}
            if not next_div:
                continue
            link = div.find("a")
            start = datetime(*map(int, div.get("data-start").split(",")))
            end = datetime(*map(int, next_div.get("data-start").split(",")))
            if start < datetime.now():
                continue
            log.debug(f"Got '{link.text}'")
            year, fid = link.get("href").rsplit("/", 1)[1].split("-")[1:]
            yield RawEvent(
                channel=prog,
                title=unidecode(link.text),
                year=int(year),
                fid=int(fid),
                start=start,
                end=end,
            )


def get_epg(dvrdb):
    """Parse output from filmweb and put it into db"""
    for event in sorted(list(get_epg_from_filmweb(dvrdb)), key=lambda x: x.start):
        log.debug(f"Adding {event}")

        dvrdb.add_event(
            title=event.title,
            year=event.year,
            fid=event.fid,
            start=event.start_ts,
            stop=event.stop_ts,
            duration=event.duration,
            channel_key=event.channel,
        )
