"""
Default configuration
"""

import os

SHIFT_BEFORE = int(os.getenv("SHIFT_BEFORE", "8"))
SHIFT_AFTER = int(os.getenv("SHIFT_AFTER", "10"))
CONFIG_DIR = os.getenv("CONFIG_DIR", "../config")
DONGLE_NUM = int(os.getenv("DONGLE_NUM", "1"))
DVB_CC = os.getenv("DVB_CC", "PL")
DVB_TOOL = "/usr/bin/dvbv5"
DVB_FRONT = 1
DVB_LNA = 1
MOVIES_DIR = os.getenv("MOVIES_DIR")
REC_DIR = os.getenv("REC_DIR", "./rec")
DB_CONN = os.getenv("DB_CONN")
TO_SHORT_LIMIT = int(os.getenv("TO_SHORT_LIMIT", "45"))
