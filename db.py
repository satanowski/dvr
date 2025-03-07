"""Handle DB operations"""

# pylint: disable=singleton-comparison

from datetime import datetime, timedelta
from functools import lru_cache
from typing import List

from loguru import logger as log
from prompt_toolkit import HTML, print_formatted_text
from prompt_toolkit.styles import Style
from sqlalchemy import and_, create_engine, func, select
from sqlalchemy.orm import sessionmaker

from defaults import DB_CONN, SHIFT_AFTER, SHIFT_BEFORE
from filmweb import CHANNELS
from models import EPG, Base, Channel, Filmweb

style = Style.from_dict(
    {
        "red": "#ff0066",
        "green": "#44ff00 italic",
    }
)


class DvrDB:  # pylint: disable=too-many-public-methods
    """Handle DB operations"""

    REC_SHIFT_BEFORE = 60 * SHIFT_BEFORE  # minutes
    REC_SHIFT_AFTER = 60 * SHIFT_AFTER  # minutes

    def __init__(self, db_connection=DB_CONN):
        self.engine = create_engine(db_connection, echo=False)
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(self.engine, autoflush=True)
        self.add_channels()

    def add_channels(self, channels=CHANNELS):
        """Add list of channels to the database if they are not already defined."""
        if self.channels_defined:
            return
        with self.session() as session:
            for ch_key, ch_name in channels:
                session.add(Channel(name=ch_name, key=ch_key))
                log.debug(f"Adding channel {ch_name}...")
            session.commit()
            session.flush()

    @property
    def channels_defined(self) -> bool:
        """Are there any channels in DB"""
        return len(self.get_channels()) > 0

    @lru_cache
    def get_channels(self) -> List[Channel]:
        """Get all channels"""
        with self.session() as session:
            return session.scalars(select(Channel)).all()

    @lru_cache
    def get_channel_keys(self) -> List[str]:
        """Get all channel's keys"""
        return list(map(lambda ch: ch.key, self.get_channels()))

    @lru_cache
    def get_channel_by_key(self, key: str) -> Channel:
        """Retrieve a channel by its unique key"""
        with self.session() as session:
            return session.scalars(select(Channel).where(Channel.key == key)).first()

    @lru_cache
    def get_channel_by_id(self, ch_id: int) -> Channel:
        """Retrieve a channel by its unique ID"""
        with self.session() as session:
            return session.scalars(select(Channel).where(Channel.id == ch_id)).first()

    def add_filmweb_entry(self, filmweb_id: int, title: str, year: int):
        """Adds a new entry to the Filmweb table with the given parameters."""
        with self.session() as session:
            session.add(
                Filmweb(
                    id=filmweb_id, title=title, year=year, ignored=False, recorded=False
                )
            )
            session.commit()
            session.flush()

    def get_filmweb_entry(self, fw_id: int) -> Filmweb:
        """Retrieves a Filmweb entry from the database by its Filmweb ID"""
        with self.session() as session:
            return session.scalars(select(Filmweb).where(Filmweb.id == fw_id)).first()

    def get_epg(self, fw_id: int, start_time: datetime):
        """Retrieves an EPG entry by Filmweb ID and start time."""
        with self.session() as session:
            return session.scalars(
                select(EPG).where(
                    and_(EPG.fw_id == fw_id, EPG.start_time == start_time)
                )
            ).first()

    def get_epg_by_id(self, epg_id: int):
        """Retrieve an EPG entry by its unique identifier"""
        with self.session() as session:
            return session.scalars(select(EPG).where(EPG.id == epg_id)).first()

    def add_epg(self, fw_id: int, start: datetime, stop: datetime, channel_key: str):
        """Adds an EPG entry to the database for a specified channel and time range."""
        channel = self.get_channel_by_key(channel_key)
        if not channel:
            log.error(f"Cannot get Channel record! ({channel_key})")
            raise ValueError

        entry = EPG(
            fw_id=fw_id, channel_id=channel.id, start_time=start, stop_time=stop
        )
        with self.session() as session:
            session.add(entry)
            session.commit()
            session.flush()

    def get_epgs_by_title(self, title: str) -> List[EPG]:
        """Get events of given title"""
        with self.session() as session:
            return session.scalars(
                select(EPG)
                .join(Channel)
                .join(Filmweb)
                .where(func.lower(Filmweb.title).like(func.lower(f"%{title}%")))
            ).all()

    def get_events_for_schedule(self, channel=None) -> List[EPG]:
        """Get events suitable for recording"""
        query = select(EPG).join(Channel).join(Filmweb)
        if channel:
            query = query.where(Channel.name == channel)

        query = (
            query.where(and_(EPG.scheduled == False, EPG.start_time > datetime.now()))
            .where(Filmweb.ignored == False)
            .distinct(Filmweb.title)
            .order_by(Filmweb.title.asc())
        )
        with self.session() as session:
            return session.scalars(query).all()

    def get_scheduled(self, just_today=False) -> List[EPG]:
        """Get events scheduled to be recorded"""
        if just_today:
            midnight = (datetime.today() + timedelta(days=1)).replace(
                hour=0, minute=0, second=0
            )
        query = (
            select(EPG)
            .join(Channel)
            .join(Filmweb)
            .where(
                and_(
                    EPG.scheduled == True,
                    EPG.start_time
                    > datetime.now() - timedelta(minutes=self.REC_SHIFT_BEFORE),
                )
            )
            .order_by(Filmweb.title.asc())
        )
        if just_today:
            query = query.where(EPG.stop_time <= midnight)

        query = query.order_by(EPG.start_time.asc())  # pylint:disable=no-member
        with self.session() as session:
            return session.scalars(query).all()

    def schedule_recording(self, epg_ids: List[int]):
        """Schedule events of given ids for recording"""
        with self.session() as session:
            for epg_id in epg_ids:
                session.query(EPG).filter_by(id=epg_id).update({"scheduled": True})
                session.commit()
                epg = self.get_epg_by_id(epg_id)
                print_formatted_text(
                    HTML(
                        f"Event <green>{epg.filmweb.title}</green> "
                        f"(<b>{epg.filmweb.year}</b>) scheduled for <red>recording</red>"
                    ),
                    style=style,
                )

    def unschedule_recording(self, epg_ids: List[int]):
        """Schedule events of given ids for recording"""
        with self.session() as session:
            for epg_id in epg_ids:
                session.query(EPG).filter_by(id=epg_id).update(
                    {"scheduled": False, "recorder": -1}
                )
                session.commit()
                epg = self.get_epg_by_id(epg_id)
                print_formatted_text(
                    HTML(
                        f"Event <green>{epg.filmweb.title}</green> "
                        f"(<b>{epg.filmweb.year}</b>) unscheduled from <red>recording</red>"
                    ),
                    style=style,
                )

    def ignore(self, fw_id: int):
        """Marks a Filmweb entry as ignored by updating its status in the database."""
        fw_entry = self.get_filmweb_entry(fw_id)
        if not fw_entry:
            log.error(f"No such Filmweb entry ({fw_id})!")
            return
        with self.session() as session:
            session.query(Filmweb).filter_by(id=fw_id).update({"ignored": True})
            session.commit()
            log.info(f'Movie "{fw_entry.title}" ({fw_entry.year}) marked as ignored.')

    def get_event_to_start_recording(self) -> List[EPG]:
        """Get events which should be start right now"""
        query = (
            select(EPG)
            .join(Channel)
            .join(Filmweb)
            .where(EPG.scheduled == True)
            .where(EPG.recorder == -1)
            .where(
                EPG.start_time
                >= datetime.now() - timedelta(minutes=self.REC_SHIFT_BEFORE)
            )
            .where(EPG.start_time < datetime.now() + timedelta(seconds=10))
        )
        with self.session() as session:
            return session.scalars(query).all()

    def get_event_to_stop_recording(self) -> List[EPG]:
        """Get events which should be stoped right now"""
        query = (
            select(EPG)
            .join(Channel)
            .join(Filmweb)
            .where(EPG.scheduled == True)
            .where(EPG.recorder >= 0)
            .where(
                EPG.stop_time
                <= datetime.now() - timedelta(minutes=self.REC_SHIFT_AFTER)
            )
        )
        with self.session() as session:
            return session.scalars(query).all()

    def marked_as_being_recorded(self, epg_id: int, recorder=-1):
        """Mark event as being recorded."""
        with self.session() as session:
            session.query(EPG).filter_by(id=epg_id).update(
                {"recorder": -1 if recorder is None else recorder}
            )
            session.commit()
            log.debug(f"Marked event as being recorded on recorder number:{recorder})")

    def marked_as_recorded(self, fw_id: int):
        """Mark event as being recorded."""
        with self.session() as session:
            session.query(Filmweb).filter_by(id=fw_id).update({"recorded": True})
            session.commit()


if __name__ == "__main__":
    db = DvrDB()
    # e = db.get_events_for_schedule()[0]
    # print(e)
    # print(e.fw_entry)
    # print(e.channel)
