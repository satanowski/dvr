"""Handle DB operations"""

import os
from datetime import datetime, timedelta
from functools import lru_cache
from typing import List

from loguru import logger as log
from prompt_toolkit import HTML, print_formatted_text
from prompt_toolkit.styles import Style
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, and_, create_engine, select

from filmweb import CHANNELS
from models import Channel, Event, Ignored
from defaults import CONFIG_DIR, SHIFT_BEFORE, SHIFT_AFTER

DBFILE = f"{CONFIG_DIR}/{os.getenv('DB_FILE', 'dvr.sqlite')}"

style = Style.from_dict(
    {
        "red": "#ff0066",
        "green": "#44ff00 italic",
    }
)


class DvrDB:
    """Handle DB operations"""

    REC_SHIFT_BEFORE = 60 * SHIFT_BEFORE  # minutes
    REC_SHIFT_AFTER = 60 * SHIFT_AFTER # minutes

    def __init__(self, dbfile=DBFILE):
        self.engine = create_engine(f"sqlite:///{dbfile}", echo=False)
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        if not self.channels_defined:
            self.add_channels(CHANNELS)

    @property
    def channels_defined(self) -> bool:
        """Are there any channels in DB"""
        return len(self.get_channels()) > 0

    def add_channels(self, channels):
        """Inital creation of channel table"""
        try:
            for ch_key, ch_name in channels:
                self.session.add(Channel(name=ch_name, key=ch_key))
                log.debug(f"Adding channel {ch_name}...")
            self.session.commit()
        except IntegrityError as err:
            log.warning(err)

    @lru_cache
    def channel_by_key(self, channel_key: str) -> Channel:
        """Get channel record by channel key"""
        query = select(Channel).where(Channel.key == channel_key)
        return self.session.exec(query).first()

    @lru_cache
    def get_channels(self, sort=None) -> List[Channel]:
        """Get all channels"""
        query = select(Channel)
        if not sort is None:
            sorting = Channel.name.asc() if sort else Channel.name.desc()
            query = query.order_by(sorting)
        return self.session.exec(query).all()

    @lru_cache
    def channel_by_id(self, channel_id: int) -> Channel:
        """Get single channel of given ID"""
        query = select(Channel).where(Channel.id == channel_id)
        return self.session.exec(query).first()

    @lru_cache
    def get_channel_keys(self) -> List[str]:
        """Get all channel's keys"""
        rows = self.session.exec(select(Channel)).all()
        return list(map(lambda c: c.key, rows))

    @lru_cache
    def is_ignored(self, fid: int) -> bool:
        """Check if movie of given id (filmweb id) is present in 'ignored' table."""
        query = select(Ignored).where(Ignored.fid == fid)
        return self.session.exec(query).first() is not None

    def ignore(self, fid: int):
        """Add given movie id to ignored table."""
        try:
            self.session.add(Ignored(fid=fid))
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            log.warning(f"Already ignored {fid}")

    def add_event(  # pylint:disable=too-many-arguments,too-many-positional-arguments
        self,
        title: str,
        fid: int,
        year: int,
        start: int,
        stop: int,
        duration: int,
        channel_key: str,
    ):
        """Add event to db"""
        if self.is_ignored(fid):
            log.debug(f"Ignoring event {title} ({year})")
            return -1
        log.debug(f"Adding event {title}...")

        try:
            event = Event(
                title=title,
                year=year,
                fid=fid,
                start=start,
                stop=stop,
                duration=duration,
                channel_id=self.channel_by_key(channel_key).id,
            )
            self.session.add(event)
            self.session.commit()
            self.session.refresh(event)
            return event.id
        except IntegrityError:
            self.session.rollback()
            log.warning(f"Event {title}({year}) alredy in db")
        return -1

    def get_events(self, title: str) -> List[Event]:
        """Get events of given title"""
        query = select(Event).where(Event.title == title)
        return self.session.exec(query).all()

    def get_events_for_schedule(self, channel=None) -> List[Event]:
        """Get events suitable for recording"""
        query = select(Event, Channel).join(Channel)
        if channel:
            query = query.where(Channel.name == channel)

        query = query.where(
            and_(
                Event.record == False,  # pylint:disable=singleton-comparison
                Event.start > int(round(datetime.now().timestamp())),
            )
        ).order_by(Event.start.asc())

        return self.session.exec(query).all()

    def get_scheduled(self, just_today=False) -> List[Event]:
        """Get events scheduled to be recorded"""
        if just_today:
            midnight = (datetime.today() + timedelta(days=1)).replace(
                hour=0, minute=0, second=0
            )
            midnight = int(midnight.timestamp())
        query = (
            select(Event, Channel)
            .join(Channel)
            .where(
                and_(
                    Event.record == True,  # pylint:disable=singleton-comparison
                    Event.start
                    > int(round(datetime.now().timestamp()) - self.REC_SHIFT_BEFORE),
                )
            )
            .order_by(Event.title.asc())
        )
        if just_today:
            query = query.where(Event.stop <= midnight)

        query = query.order_by(Event.start.asc())  # pylint:disable=no-member
        return self.session.exec(query).all()

    def schedule_recording(self, ev_ids: List[int]):
        """Schedule events of given ids for recording"""
        for event_id in ev_ids:
            event = self.session.exec(select(Event).where(Event.id == event_id)).first()
            event.record = True
            self.session.commit()
            self.session.refresh(event)
            print_formatted_text(
                HTML(
                    f"Event <green>{event.title}</green> "
                    f"(<b>{event.year}</b>) scheduled for <red>recording</red>"
                ),
                style=style,
            )

    def unschedule_recording(self, ev_ids: List[int]):
        """Schedule events of given ids for recording"""
        for event_id in ev_ids:
            event = self.session.exec(select(Event).where(Event.id == event_id)).first()
            event.record = False
            self.session.commit()
            self.session.refresh(event)
            print_formatted_text(
                HTML(
                    f"Event <green>{event.title}</green> "
                    f"(<b>{event.year}</b>) unscheduled from <red>recording</red>"
                ),
                style=style,
            )

    def get_event_to_start_recording(self) -> List[Event]:
        """Get events which should be start right now"""
        query = (
            select(Event, Channel)
            .join(Channel)
            .where(Event.record == True)  # pylint:disable=singleton-comparison
            .where(Event.recorder == -1)
            .where(
                Event.start >= int(datetime.now().timestamp()) - self.REC_SHIFT_BEFORE
            )
            .where(Event.start < int(datetime.now().timestamp()) + 10)
        )
        return self.session.exec(query).all()

    def get_event_to_stop_recording(self) -> List[Event]:
        """Get events which should be stoped right now"""
        query = (
            select(Event, Channel)
            .join(Channel)
            .where(Event.record == True)  # pylint:disable=singleton-comparison
            .where(Event.recorder >= 0)
            .where(
                Event.stop <= (int(datetime.now().timestamp()) - self.REC_SHIFT_AFTER)
            )
        )
        return self.session.exec(query).all()

    def marked_as_being_recorded(self, event: Event, rec_number=-1):
        """Modify event as being recorded."""
        log.debug(f"Marking event as being recorded...1  rec_number={rec_number}")
        if rec_number is None:
            event.recorder = -1
        else:
            event.recorder = rec_number
        event.record = not rec_number is None
        log.debug("Marking event as being recorded...2")
        self.session.commit()
        log.debug("Marking event as being recorded...3")
        self.session.refresh(event)
        self.session.flush()
        log.debug(
            f"Marking event as being recorded...4 recorder:{event.recorder}, record:{event.record}"
        )
