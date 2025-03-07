"""Handle getting EPG from filmweb.pl"""

# pylint: disable=too-many-locals

import asyncio
import concurrent.futures
from datetime import datetime
from typing import Iterable, List, Tuple

import requests
from bs4 import BeautifulSoup
from loguru import logger as log
from unidecode import unidecode

from models import RawEvent

BASE_URL = "https://www.filmweb.pl"
PROG_URL = f"{BASE_URL}/program-tv"

CHANNELS = (
    ("Fokus+TV", "Fokus TV"),
    # ("Nowa+TV", "Nowa TV"),
    ("Polsat", "Polsat"),
    ("Puls+2", "PULS 2"),
    ("Stopklatka", "Stopklatka"),
    ("Super+Polsat", "Super Polsat"),
    # ("TTV", "TTV"),
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


def wget(prog: str) -> Tuple[str, str]:
    """Get filmweb webpage"""
    log.debug(f"Asking filmweb for: {prog}")
    html = requests.get(f"{PROG_URL}/{prog}", timeout=10).text
    return (prog, html)


async def get_epg_from_filmweb(channel_keys: List[str]) -> Iterable[RawEvent]:
    """Parse filmweb page and extract EPG data"""
    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        loop = asyncio.get_event_loop()
        futures = [loop.run_in_executor(executor, wget, prog) for prog in channel_keys]

        for prog, raw_html in await asyncio.gather(*futures):
            html = BeautifulSoup(raw_html, "html.parser")
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

                log.debug(f"new event '{unidecode(link.text)}': {start}  -  {end}")

                if start < datetime.now():
                    continue
                log.debug(f"Got '{link.text}'")
                year, fid = link.get("href").rsplit("/", 1)[1].split("-")[1:]
                results.append(
                    RawEvent(
                        channel=prog,
                        title=unidecode(link.text),
                        year=int(year),
                        fid=int(fid),
                        start=start,
                        end=end,
                    )
                )
    return results


def get_epg(dvrdb):
    """Parse output from filmweb and put it into db"""
    ch_keys = dvrdb.get_channel_keys()
    loop = asyncio.get_event_loop()
    raw_events = loop.run_until_complete(get_epg_from_filmweb(ch_keys))

    for raw_event in sorted(raw_events, key=lambda x: x.start):
        fw_entry = dvrdb.get_filmweb_entry(raw_event.fid)
        if fw_entry is None:
            dvrdb.add_filmweb_entry(raw_event.fid, raw_event.title, raw_event.year)
            fw_entry = dvrdb.get_filmweb_entry(raw_event.fid)

        epg = dvrdb.get_epg(raw_event.fid, raw_event.start)
        if epg:
            log.warning(f"EPG {raw_event.title} ({raw_event.year}) already in DB")
            continue

        dvrdb.add_epg(
            fw_id=fw_entry.id,
            start=raw_event.start,
            stop=raw_event.end,
            channel_key=raw_event.channel,
        )
