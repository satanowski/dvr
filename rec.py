"""Handle running dvbv5-zap"""

import os
from subprocess import PIPE, TimeoutExpired

import psutil
from loguru import logger as log

from dvb import DVB


class Recorder:
    """Handles recording"""

    def __init__(self, adapter: int):
        self.adapter = adapter
        self.proc = None

    def _rec(self, cmd: str):
        log.debug(f"ZAP: {cmd}")

    def start_rec(self, channel: str, recfile: str) -> bool:
        """Start recording, return PID of the process"""
        cmd = DVB.zap_cmd(self.adapter, channel, recfile)
        log.debug(f"Executing command: `{cmd}`")
        self.proc = psutil.Popen(
            f"exec {cmd}", shell=True, stdout=PIPE, preexec_fn=os.setsid
        )
        log.debug(f"Proces: {self.proc} started!")
        return self.proc is not None

    @property
    def busy(self) -> bool:
        """Check if process is still present"""
        return self.proc.is_running() if self.proc else False

    def stop_rec(self) -> bool:
        """Kill the recording process"""
        log.debug(f"Trying to stop process [{self.proc}]")
        if not self.busy:
            log.debug(f"It seems the proc {self.proc} is not alive")
            return False
        try:
            self.proc.communicate(timeout=2)
        except TimeoutExpired:
            self.proc.kill()
            self.proc.terminate()
            self.proc.communicate()
        return not self.proc.is_running()
