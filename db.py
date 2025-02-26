"""Handle DB operations"""

import os
from datetime import datetime, timedelta
from functools import lru_cache
from typing import List

from loguru import logger as log
from prompt_toolkit import HTML, print_formatted_text
from prompt_toolkit.styles import Style
from psycopg2.errors import NotNullViolation
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, and_, create_engine, select

from defaults import SHIFT_AFTER, SHIFT_BEFORE, DB_CONN
from filmweb import CHANNELS
from models import VIEW_EVENTS_SQL, Channel, Event, FilmwebEntry


style = Style.from_dict(
    {
        "red": "#ff0066",
        "green": "#44ff00 italic",
    }
)


class DvrDB:
    """Handle DB operations"""

    REC_SHIFT_BEFORE = 60 * SHIFT_BEFORE  # minutes
    REC_SHIFT_AFTER = 60 * SHIFT_AFTER  # minutes

    def __init__(self, db_connection=DB_CONN):
        self.engine = create_engine(db_connection, echo=False)
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        if not self.channels_defined:
            self.add_channels(CHANNELS)

        # self.session.execute(VIEW_EVENTS_SQL)

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
            self.session.rollout()
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
        if sort is not None:
            sorting = Channel.name.asc() if sort else Channel.name.desc()
            query = query.order_by(sorting)
        return self.session.exec(query).all()

    @lru_cache
    def channel_by_id(self, channel_id: int) -> Channel:
        """Get single channel of given ID"""
        query = select(Channel).where(Channel.id == channel_id)
        return self.session.exec(query).first()

    @lru_cache
    def get_channels_keys(self) -> List[str]:
        """Get all channel's keys"""
        rows = self.session.exec(select(Channel)).all()
        return list(map(lambda c: c.key, rows))

    def ignore(self, fwid: int):
        """Mark filmweb entry of given ID as ignored."""
        fw_entry = self.get_filmweb_entry(fwid)
        fw_entry.ignored = True
        self.session.add(fw_entry)
        self.session.commit()

    @lru_cache
    def get_filmweb_entry(self, filmweb_id: int) -> FilmwebEntry | None:
        """Get Filmweb Entry based on its ID"""
        query = select(FilmwebEntry).where(FilmwebEntry.id == filmweb_id)
        entry = self.session.exec(query).first()
        return entry

    def add_or_get_filmweb_entry(
        self, filmweb_id: int, title: str, year: int
    ) -> FilmwebEntry | None:
        """Get Filmweb Entry based on its ID"""
        try:
            entry = FilmwebEntry(id=filmweb_id, title=title, year=year, ignored=False)
            self.session.add(entry)
            self.session.commit()
            self.session.refresh(entry)
            return entry
        except NotNullViolation as err:
            log.error(err)
            return None
        except IntegrityError:
            self.session.rollback()
            log.warning(f"Filmweb entry  {filmweb_id}/{title}({year}) alredy in db")
            return self.get_filmweb_entry(filmweb_id)

    def add_event(
        self, fw_entry: FilmwebEntry, start: int, stop: int, channel_key: str
    ) -> int:
        """Add event to db"""
        if fw_entry.ignored:
            log.debug(f"Ignoring event {fw_entry.title} ({fw_entry.year})")
            return -1
        log.debug(f"Adding recodable event {fw_entry}...")
        try:
            event = Event(
                filmweb_id=fw_entry.id,
                start_ts=start,
                stop_ts=stop,
                channel_id=self.channel_by_key(channel_key).id,
            )
            self.session.add(event)
            self.session.commit()
            self.session.refresh(event)
            return event.id
        except NotNullViolation as err:
            log.error(err)
            return -1
        except IntegrityError:
            self.session.rollback()
            log.warning(f"Event {fw_entry.title}({fw_entry.year}) alredy in db")
        return -1

    def get_events(self, title: str) -> List[Event]:
        """Get events of given title"""
        query = (
            select(Event)
            .join(Channel)
            .join(FilmwebEntry)
            .where(FilmwebEntry.title == title)
        )
        return self.session.exec(query).all()

    def get_events_for_schedule(self, channel=None) -> List[Event]:
        """Get events suitable for recording"""
        query = select(Event).join(Channel).join(FilmwebEntry)
        if channel:
            query = query.where(Channel.name == channel)

        query = (
            query.where(
                and_(
                    Event.to_be_recorded == False,
                    Event.start_ts > int(round(datetime.now().timestamp())),
                )
            ).where(FilmwebEntry.ignored == False)
            .distinct(FilmwebEntry.title)
            .order_by(FilmwebEntry.title.asc())
        )

        return self.session.exec(query).all()

    def get_scheduled(self, just_today=False) -> List[Event]:
        """Get events scheduled to be recorded"""
        if just_today:
            midnight = (datetime.today() + timedelta(days=1)).replace(
                hour=0, minute=0, second=0
            )
            midnight = int(midnight.timestamp())
        query = (
            select(Event)
            .join(Channel)
            .join(FilmwebEntry)
            .where(
                and_(
                    Event.to_be_recorded == True,  # pylint:disable=singleton-comparison
                    Event.start_ts
                    > int(round(datetime.now().timestamp()) - self.REC_SHIFT_BEFORE),
                )
            )
            .order_by(FilmwebEntry.title.asc())
        )
        if just_today:
            query = query.where(Event.stop_ts <= midnight)

        query = query.order_by(Event.start_ts.asc())  # pylint:disable=no-member
        return self.session.exec(query).all()

    def schedule_recording(self, ev_ids: List[int]):
        """Schedule events of given ids for recording"""
        for event_id in ev_ids:
            event = self.session.exec(select(Event).where(Event.id == event_id)).first()
            event.to_be_recorded = True
            self.session.commit()
            self.session.refresh(event)
            print_formatted_text(
                HTML(
                    f"Event <green>{event.fw_entry.title}</green> "
                    f"(<b>{event.fw_entry.year}</b>) scheduled for <red>recording</red>"
                ),
                style=style,
            )

    def unschedule_recording(self, ev_ids: List[int]):
        """Schedule events of given ids for recording"""
        for event_id in ev_ids:
            event = self.session.exec(select(Event).where(Event.id == event_id)).first()
            event.to_be_recorded = False
            self.session.commit()
            self.session.refresh(event)
            print_formatted_text(
                HTML(
                    f"Event <green>{event.fw_entry.title}</green> "
                    f"(<b>{event.fw_entry.year}</b>) unscheduled from <red>recording</red>"
                ),
                style=style,
            )

    def get_event_to_start_recording(self) -> List[Event]:
        """Get events which should be start right now"""
        query = (
            select(Event)
            .join(Channel)
            .join(FilmwebEntry)
            .where(Event.to_be_recorded == True)  # pylint:disable=singleton-comparison
            .where(Event.recorder == -1)
            .where(
                Event.start_ts
                >= int(datetime.now().timestamp()) - self.REC_SHIFT_BEFORE
            )
            .where(Event.start_ts < int(datetime.now().timestamp()) + 10)
        )
        return self.session.exec(query).all()

    def get_event_to_stop_recording(self) -> List[Event]:
        """Get events which should be stoped right now"""
        query = (
            select(Event)
            .join(Channel)
            .join(FilmwebEntry)
            .where(Event.to_be_recorded == True)  # pylint:disable=singleton-comparison
            .where(Event.recorder >= 0)
            .where(
                Event.stop_ts
                <= (int(datetime.now().timestamp()) - self.REC_SHIFT_AFTER)
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
        event.to_be_recorded = not rec_number is None
        log.debug("Marking event as being recorded...2")
        self.session.commit()
        log.debug("Marking event as being recorded...3")
        self.session.refresh(event)
        self.session.flush()
        log.debug(
            f"Marking event as being recorded...4 recorder:{event.recorder}, "
            f"record:{event.to_be_recorded}"
        )


# if __name__ == "__main__":
#     db = DvrDB()
#     e = db.get_events_for_schedule()[0]
#     print(e)
#     print(e.fw_entry)
#     print(e.channel)
