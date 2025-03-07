"""SQL Models definitions"""

import re
from dataclasses import dataclass
from datetime import datetime
from time import localtime, strftime
from typing import List

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

sch = re.compile(r"[^a-zA-Z\d]")


def ts2tm(ts: int) -> str:
    """Convert timestamp to time string"""
    return strftime("%Y-%m-%d %H:%M", localtime(ts))


class Base(
    DeclarativeBase
):  # pylint: disable=missing-class-docstring, too-few-public-methods
    pass


class Filmweb(Base):
    """Filmweb entry base class"""

    __tablename__ = "filmweb"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    year: Mapped[int] = mapped_column(Integer)
    ignored: Mapped[bool] = mapped_column(Boolean, default=False)
    recorded: Mapped[bool] = mapped_column(Boolean, default=False)
    epg_events: Mapped[List["EPG"]] = relationship(
        back_populates="filmweb", cascade="all, delete-orphan"
    )

    @property
    def safe_title(self) -> str:
        """Return event title in form safe for filenames"""
        return sch.sub("_", str(self.title).lower())

    @property
    def rec_file_name(self) -> str:
        """Create name for record file"""
        return f"{self.safe_title}_{self.year}.mts"

    def __repr__(self):
        return (
            f"Filmweb(id:{self.id},title:{self.title}, "
            f"year:{self.year}, ignored:{self.ignored})"
        )

    def __str__(self):
        return (
            f"Filmweb(id:{self.id},title:{self.title}, "
            f"year:{self.year}, ignored:{self.ignored})"
        )


class Channel(Base):  # pylint: disable=too-few-public-methods
    """Channel base class"""

    __tablename__ = "channel"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(16))
    key: Mapped[str] = mapped_column(String(16))
    epg_events: Mapped[List["EPG"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )

    @property
    def safe_name(self) -> str:
        """Return channel name in safe form (suitable for filenames)"""
        return sch.sub("_", str(self.name).lower())


class EPG(Base):
    """EPG event base class"""

    SHORT_FMT = "%Y-%m-%d %H:%M"
    __tablename__ = "epg"

    id: Mapped[int] = mapped_column(primary_key=True)
    fw_id: Mapped[int] = mapped_column(ForeignKey("filmweb.id"))
    channel_id: Mapped[int] = mapped_column(ForeignKey("channel.id"))
    start_time: Mapped[int] = mapped_column(DateTime)
    stop_time: Mapped[int] = mapped_column(DateTime)
    scheduled: Mapped[bool] = mapped_column(Boolean, default=False)
    recorder: Mapped[int] = mapped_column(Integer, default=-1)
    filmweb: Mapped[Filmweb] = relationship(
        back_populates="epg_events", lazy="joined", innerjoin=True
    )
    channel: Mapped[Channel] = relationship(
        back_populates="epg_events", lazy="joined", innerjoin=True
    )

    @property
    def duration(self) -> int:
        """Return event duration in seconds"""
        return (self.stop_time - self.start_time).total_seconds()

    @property
    def start_time_short(self):
        """Return start time in shorter form"""
        return self.start_time.strftime(self.SHORT_FMT)

    @property
    def stop_time_short(self):
        """Return stop time in shorter form"""
        return self.stop_time.strftime(self.SHORT_FMT)


@dataclass
class RawEvent:
    """Class for holding raw data from epg"""

    channel: str
    title: str
    fid: int
    year: int
    start: datetime
    end: datetime

    def __repr__(self):
        return (
            f"RawEvent(fid:{self.fid} channel: {self.channel}, "
            f"title:{self.channel}, year:{self.year}, start:{self.start}, "
            f"end:{self.end})"
        )

    @property
    def duration(self) -> int:
        """Calculate event duration in seconds"""
        return (self.end - self.start).total_seconds()

    @property
    def start_ts(self) -> int:
        """Return start time as timestamp/epoch"""
        return int(round(self.start.timestamp()))

    @property
    def stop_ts(self) -> int:
        """Return stop time as timestamp/epoch"""
        return int(round(self.end.timestamp()))

    @property
    def safe_title(self) -> str:
        """Return title in forma suitable for filenames"""
        return self.title.replace(" ", "_").lower()


# VIEW_EVENTS_SQL = text(
#     """
# CREATE OR REPLACE VIEW v_events AS
# SELECT
# 	channel.name,
# 	event.id,
# 	event.start_ts,
# 	event.stop_ts,
# 	filmwebentry.id as fw_id,
# 	filmwebentry.title,
# 	filmwebentry.year,
# 	filmwebentry.ignored,
# 	event.to_be_recorded,
# 	event.recorder
# FROM event
# 	INNER JOIN filmwebentry
# 		ON event.filmweb_id = filmwebentry.id
# 	INNER JOIN channel
# 		ON event.channel_id = channel.id

# """
# )
