"""SQL Models definitions"""

import re
from dataclasses import dataclass
from datetime import datetime
from time import localtime, strftime
from typing import List, Optional

from sqlmodel import Field, Index, Relationship, SQLModel

sch = re.compile(r"[^a-zA-Z\d]")


def ts2tm(ts: int) -> str:
    """Convert timestamp to time string"""
    return strftime("%Y-%m-%d %H:%M", localtime(ts))


class Channel(SQLModel, table=True):
    """Channel model"""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    key: str = Field(unique=True)
    events: List["Event"] = Relationship(back_populates="channel")

    @property
    def safe_name(self) -> str:
        """Return channel name in safe form (suitable for filenames)"""
        return sch.sub("_", str(self.name).lower())


class Ignored(SQLModel, table=True):
    """Ignored Event model"""

    id: Optional[int] = Field(default=None, primary_key=True)
    fid: int = Field(foreign_key="event.fid")


class Event(SQLModel, table=True):
    """Event model"""

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field()
    year: int = Field()
    fid: int = Field()
    start: int = Field()
    stop: int = Field()
    duration: int = Field()
    channel_id: int = Field(default=None, foreign_key="channel.id")
    channel: Channel = Relationship(back_populates="events")
    record: bool = Field(default=False)
    recorder: int = Field(default=-1)

    __table_args__ = (
        Index(
            "compound_index_title_year_fid_start",
            "title",
            "year",
            "fid",
            "start",
            unique=True,
        ),
    )

    @property
    def safe_title(self) -> str:
        """Return event title in form safe for filenames"""
        return sch.sub("_", str(self.title).lower())

    @property
    def start_t(self) -> str:
        """Return start time as time string"""
        return ts2tm(self.start)

    @property
    def stop_t(self) -> str:
        """Return end time as time string"""
        return ts2tm(self.stop)

    @property
    def rec_file_name(self) -> str:
        """Create name for record file"""
        return f"{self.safe_title}_{self.year}.mts"

    def __str__(self) -> str:
        return f"Event({self.title} ({self.year}) [{self.start_t} - {self.stop_t}])"


@dataclass
class RawEvent:
    """Class for holding raw data from epg"""

    channel: str
    title: str
    fid: int
    year: int
    start: datetime
    end: datetime

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

    def __repr__(self):
        return f"Event({self.channel}, {self.title})"

    @property
    def safe_title(self) -> str:
        """Return title in forma suitable for filenames"""
        return self.title.replace(" ", "_").lower()
