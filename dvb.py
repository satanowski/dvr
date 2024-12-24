"""
Handle DVB stuff
"""

import shutil
from configparser import ConfigParser
from pathlib import Path
from subprocess import call
from tempfile import gettempdir
from time import sleep

from loguru import logger as log

from defaults import CONFIG_DIR, DVB_FRONT, DVB_LNA, DVB_TOOL


class DVB:
    """Wrapper for dvbtools"""

    MUX_FILE = "mux.cfg"
    CHNL_FILE = "channels.cfg"

    @staticmethod
    def fabs(f: str | Path) -> str:
        """Return given path as string. Format for absloute form if given as Path object"""
        if isinstance(f, Path):
            return f.absolute()
        return f

    @staticmethod
    def scan_cmd(
        adapter: int, front: int, mux: str | Path, channels: str | Path
    ) -> str:
        """Rerturn base form of scan command"""
        return f"{DVB_TOOL}-scan -a {adapter} -f {front} -v {DVB.fabs(mux)} -o {DVB.fabs(channels)}"

    @staticmethod
    def zap_cmd(
        adapter: int,
        channel: str,
        output_file: str | Path,
        lna=DVB_LNA,
        front=DVB_FRONT,
    ) -> str:
        """Rerturn base form of zap command"""
        return (
            f"{DVB_TOOL}-zap -a {adapter} -f {front} --lna={lna} "
            f'-c {Path(CONFIG_DIR)/DVB.CHNL_FILE} "{channel}" -r '
            f'-o "{DVB.fabs(output_file)}"'
        )

    @staticmethod
    def is_ch_ok(channel_name: str) -> bool:
        """Sidekick function to filterout unusable channels"""
        for token in ("default", "radio", " fm", "eurosport", "MHz#"):
            if token in channel_name.lower():
                return False
        return True

    @staticmethod
    def scan(adapter=0, front=DVB_FRONT) -> dict:
        """Perform channels scanning on given adapter"""
        mux_config_file = Path(CONFIG_DIR) / DVB.MUX_FILE

        if not mux_config_file.exists():
            log.error(
                "No MUX configuration provided!!! "
                f"Please provide file `{mux_config_file.absolute()}`"
            )
            return {}
        temp_channels_file = Path(gettempdir()) / DVB.CHNL_FILE
        scan_cmd = DVB.scan_cmd(adapter, front, mux_config_file, temp_channels_file)
        log.warning("In a moment scanning on first DVB device will begin...")
        sleep(5)
        call(scan_cmd, shell=True)

        scanned_channels = ConfigParser(strict=False)
        scanned_channels.read(temp_channels_file.absolute())
        return {
            channel: values
            for channel, values in scanned_channels.items()
            if DVB.is_ch_ok(channel)
        }

    @staticmethod
    def save_channels_config(channels_cfg: dict):
        """Write given configuration to channels.cfg file"""
        channels_cfg_file = Path(CONFIG_DIR) / DVB.CHNL_FILE
        if channels_cfg_file.exists():
            log.info(f"Make backup of file {channels_cfg_file.absolute()}")
            shutil.copy(channels_cfg_file, f"{channels_cfg_file.absolute()}.bkp")
        # write new config
        new_config = ConfigParser(strict=False)
        for channel, values in channels_cfg.items():
            new_config[channel] = values

        with channels_cfg_file.open("w") as cfg_file:
            new_config.write(cfg_file)
        log.info(f"New channels writen to {channels_cfg_file.absolute()}")
