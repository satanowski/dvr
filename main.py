#!/usr/bin/env python3
"""Main module"""
# pylint:disable=no-value-for-parameter

import sys
from pathlib import Path
from time import sleep
from typing import Iterable, Tuple

import click
from loguru import logger as log
from prompt_toolkit import HTML, print_formatted_text
from prompt_toolkit.shortcuts import checkboxlist_dialog, radiolist_dialog
from prompt_toolkit.styles import Style
from unidecode import unidecode

from db import DvrDB
from defaults import CONFIG_DIR, DONGLE_NUM, MOVIES_DIR, REC_DIR
from dvb import DVB
from filmweb import get_epg
from models import sch
from notify import notify
from rec import Recorder

recorders = [Recorder(i) for i in range(DONGLE_NUM)]

style = Style.from_dict(
    {"red": "#ff0066", "green": "#44ff00 italic", "yellow": "#ffff5f"}
)

dvrdb = DvrDB()


def get_free_recorder() -> Recorder:
    """Return handle to free recorder instance if any."""
    for recorder in recorders:
        if not recorder.busy:
            return recorder
    return None


def scan_for_channels():
    """Run initial scanning of DVB channels"""
    channels_discovered = DVB.scan()
    if not channels_discovered:
        log.error("Cannot scan channels!")
        sys.exit(1)

    channels_selected = checkboxlist_dialog(
        title="Select channels you want to use",
        text="Detected channels:",
        values=[(ch, ch) for ch in channels_discovered.keys()],
    ).run()

    if not channels_selected:
        log.error("No channels selected!")
        sys.exit(1)

    DVB.save_channels_config(
        {
            channel: data
            for channel, data in channels_discovered.items()
            if channel in channels_selected
        }
    )


def get_existing_movies(movies_dir=MOVIES_DIR) -> Iterable[Tuple[str, int]]:
    """Get list of tuples(movie title, movie year) based on files in given dir"""
    if not MOVIES_DIR:
        yield None
    for p in Path(movies_dir).glob("**/*.mts"):
        filename = p.name.rsplit(".", 1)[0]
        try:
            title, year = filename.rsplit(" ", 1)
            yield (sch.sub("_", unidecode(title).lower()), int(year.strip("()")))
        except ValueError:
            log.error(f"Cannot parse file name: {p}")


def check_plan_and_start_stop_recording_if_needed():
    """Check if recording of any event should be now started or stopped and do it."""
    log.debug("checking...")
    events2start = dvrdb.get_event_to_start_recording()
    events2stop = dvrdb.get_event_to_stop_recording()

    log.debug(f"On the start list: {events2start}")
    log.debug(f"On the stop list: {events2stop}")

    if len(events2start) == 0 and len(events2stop) == 0:
        log.debug("nothing to do")
        return

    for event, channel in events2stop:
        log.info(f"Stopping event {event.title} on adapter {event.recorder}...")
        if recorders[event.recorder].stop_rec():
            dvrdb.marked_as_being_recorded(event)
            notify(event)

    for event, channel in events2start:
        dvb = get_free_recorder()
        if dvb is None:
            log.warning(
                f"Cannot start recording of {event.title}! No recorders available!"
            )
            return

        log.info(
            f"Starting recording of event {event.title} on adapter {dvb.adapter}..."
        )
        if dvb.start_rec(
            channel.name, f"{REC_DIR}/{channel.safe_name}_{event.rec_file_name}"
        ):
            dvrdb.marked_as_being_recorded(event, dvb.adapter)
            log.debug("recording started")


def schedule_for_recording(channel: str, select: bool):
    """Mark event as scheduled to be recorded"""
    selected_channel = (
        radiolist_dialog(
            title="Select channel",
            values=[
                (channel.id, channel.name) for channel in dvrdb.get_channels(sort=False)
            ],
        ).run()
        if select
        else None
    )

    selected_channel = (
        dvrdb.channel_by_id(selected_channel).name if selected_channel else channel
    )

    # filter out stuff we already have
    movies = list(get_existing_movies())  # (title, year)
    filtered = []
    titles2skip = []
    titles2skip.extend(movies)
    titles2skip.extend([(ev.safe_title, ev.year) for ev, _ in dvrdb.get_scheduled()])
    for ev, ch in dvrdb.get_events_for_schedule(channel=selected_channel):
        if (ev.safe_title, ev.year) in titles2skip:
            log.debug(
                f"{ev.title} ({ev.year}) skipped as it is already recorded or scheduled"
            )
        else:
            filtered.append((ev, ch))

    results_array = checkboxlist_dialog(
        title="Select event",
        text="Movies in near future",
        values=[
            (
                event.id,
                f"{event.title} ({event.year}) [{channel.name}] ({event.start_t}-{event.stop_t})",
            )
            for event, channel in filtered
        ],
    ).run()
    if not results_array:
        log.warning(f"No events scheduled for recording on {selected_channel}.")
    else:
        print(results_array)
        dvrdb.schedule_recording(results_array)
        log.info(f"Recording scheduled on {selected_channel}.")


def show_recording_plan(just_today=False):
    """Display events scheduled for recording"""
    results = dvrdb.get_scheduled(just_today)
    if not results:
        log.warning("Nothing scheduled")
        return
    print_formatted_text(
        HTML(f"<green>{len(results)}</green> events scheduled:"), style=style
    )
    for event, channel in results:
        print_formatted_text(
            HTML(
                f"<green>{event.title: >45}</green> "
                f"(<b>{event.year: >4}</b>) -> <yellow>{event.start_t[:10]:>10}</yellow> "
                f"<pink>{event.start_t[10:]:>5}</pink> @ <i>{channel.name}</i>"
            ),
            style=style,
        )


def unschedule_recording():
    """Mark events as not scheduled for recording"""
    to_be_removed_from_schedule = checkboxlist_dialog(
        title="Select event to remove from schedule",
        text="Movies scheduled to be recorded",
        values=[
            (
                event.id,
                f"{event.title} ({event.year}) [{channel.name}] ({event.start_t}-{event.stop_t})",
            )
            for event, channel in dvrdb.get_scheduled()
        ],
    ).run()
    if not to_be_removed_from_schedule:
        log.warning("No events selected to be removed from recording schedule")
    else:
        dvrdb.unschedule_recording(to_be_removed_from_schedule)


def serve():
    """Periodically check if there's anything to do and do it :D"""
    log.remove()
    log.add(
        f"{CONFIG_DIR}/dvr.log",
        rotation="10 MB",
        retention="10 days",
        compression="zip",
    )
    log.info("Start :)")
    while True:
        check_plan_and_start_stop_recording_if_needed()
        sleep(30)


def check_epg(title: str):
    """Check if given title exists in DB"""
    for event in dvrdb.get_events(title):
        click.echo(click.style(event, fg="green"))

def perform_rec_test():
    # ensure all recorders are free
    rec_dir = Path(REC_DIR)
    log.debug("Stopping recording if any...")
    for recorder in recorders:
        if recorder.busy:
            log.debug(f"Stopping recording on recorder: {recorder.adapter}")
            recorder.stop_rec()
        sleep(1)
    for recorder in recorders:
        for channel in dvrdb.get_channels():
            log.debug(f"Recording channel '{channel.name}' on adapter {recorder.adapter}...")
            recorder.start_rec(
                channel=channel.name,
                recfile=(rec_dir / f"adapter_{recorder.adapter}__{channel.safe_name}.mts"))
            sleep(10)
            recorder.stop_rec()
            log.debug(f"Recording channel '{channel.name}' on adapter {recorder.adapter} stopped")
    log.debug("Test procedure finished. You can now examine the files")


@click.command()
@click.option("-a", "--action", type=str, help="Run action", default="")
@click.option("-t", "--title", type=str, help="Event title", default="", required=False)
@click.option(
    "-c", "--channel", type=str, help="Filter by channel", default="", required=False
)
@click.option(
    "-s",
    "--select",
    type=bool,
    help="Select single channel",
    default=False,
    is_flag=True,
)
@click.option("-f", "--fwid", type=str, help="Filmweb ID", default="", required=False)
def main(
    action: str, title: str, fwid: int, channel: str, select=bool
):  # pylint:disable=too-many-arguments,too-many-positional-arguments
    """App entrypoint"""
    action = action.lower()
    action_map = {
        "check": (check_epg, title),
        "epg": (get_epg, dvrdb),
        "ignore": (dvrdb.ignore, fwid),
        "plan": show_recording_plan,
        "today": (show_recording_plan, True),
        "remove": unschedule_recording,
        "scan": scan_for_channels,
        "sched": (schedule_for_recording, channel, select),
        "serve": serve,
        "test": perform_rec_test,
    }
    if action not in action_map:
        log.error(f"Action `{action}` unknown!")
        return
    job = action_map[action]
    if isinstance(job, tuple):  # there are some arguments
        job[0](*job[1:])
    else:
        job()


if __name__ == "__main__":
    main()
