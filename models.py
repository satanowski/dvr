"""SQL Models definitions"""

import re
from dataclasses import dataclass
from datetime import datetime
from time import localtime, strftime
from typing import List

from sqlalchemy import text
from sqlmodel import Field, Index, Relationship, SQLModel

sch = re.compile(r"[^a-zA-Z\d]")


def ts2tm(ts: int) -> str:
    """Convert timestamp to time string"""
    return strftime("%Y-%m-%d %H:%M", localtime(ts))


class FilmwebEntry(SQLModel, table=True):
    """Filmweb Entry model"""

    id: int = Field(default=None, primary_key=True, unique=True)
    title: str = Field(unique=False)
    year: int = Field(unique=False)
    ignored: bool = Field(default=False)

    events: List["Event"] = Relationship(back_populates="fw_entry")

    def __repr__(self):
        return (
            f"FilmwebEntry(id:{self.id},title:{self.title}, "
            f"year:{self.year}, ignored:{self.ignored})"
        )

    def __str__(self):
        return (
            f"FilmwebEntry(id:{self.id},title:{self.title}, "
            f"year:{self.year}, ignored:{self.ignored})"
        )

    @property
    def safe_title(self) -> str:
        """Return event title in form safe for filenames"""
        return sch.sub("_", str(self.title).lower())

    @property
    def rec_file_name(self) -> str:
        """Create name for record file"""
        return f"{self.safe_title}_{self.year}.mts"


class Channel(SQLModel, table=True):
    """Channel model"""

    id: int = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    key: str = Field(unique=True)

    events: List["Event"] = Relationship(back_populates="channel")

    @property
    def safe_name(self) -> str:
        """Return channel name in safe form (suitable for filenames)"""
        return sch.sub("_", str(self.name).lower())


class Event(SQLModel, table=True):
    """Event model"""

    id: int | None = Field(default=None, primary_key=True)
    filmweb_id: int = Field(default=None, foreign_key="filmwebentry.id")
    start_ts: int = Field()
    stop_ts: int = Field()
    channel_id: int = Field(default=None, foreign_key="channel.id")
    to_be_recorded: bool = Field(default=False)
    recorder: int = Field(default=-1)
    fw_entry: FilmwebEntry = Relationship(back_populates="events")
    channel: Channel = Relationship(back_populates="events")

    __table_args__ = (
        Index(
            "compound_index_fid_start",
            "filmweb_id",
            "start_ts",
            unique=True,
        ),
    )

    @property
    def duration(self) -> int:
        """Return event duration in seconds"""
        return self.stop_ts - self.start_ts

    @property
    def start_t(self) -> str:
        """Return start time as time string"""
        return ts2tm(self.start_ts)

    @property
    def stop_t(self) -> str:
        """Return end time as time string"""
        return ts2tm(self.stop_ts)


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


VIEW_EVENTS_SQL = text(
    """
CREATE OR REPLACE VIEW v_events AS
SELECT
	channel.name,
	event.id,
	event.start_ts,
	event.stop_ts,
	filmwebentry.id as fw_id,
	filmwebentry.title,
	filmwebentry.year,
	filmwebentry.ignored,
	event.to_be_recorded,
	event.recorder
FROM event
	INNER JOIN filmwebentry
		ON event.filmweb_id = filmwebentry.id
	INNER JOIN channel
		ON event.channel_id = channel.id
	
"""
)
