# mpd backend
# https://python-mpd2.readthedocs.io/en/latest/
# https://github.com/Mic92/python-mpd2/blob/main/mpd/base.py
import os
import sys

import mpd

from .base import backend_abc

sys.path.append("..")
from utils import log, tryit


home_dir = os.path.expanduser("~") + "/"


class mpd_backend(backend_abc):
    """mpd backend."""
    settings: dict = {
        "address": "localhost",
        "port": 6600
    }
    server = mpd.MPDClient()
    # server.timeout = 10  # etc

    @tryit
    def connect(cls) -> None:
        """Connect to server
        TODO handle tcp vs unix socket
        check if server is running
        """
        try:
            cls.server.connect(cls.settings["address"], port=cls.settings["port"])
        except ConnectionRefusedError as e:
            print(f"{e}\nIs the mpd server running?")
            sys.exit(1)

    @tryit
    def disconnect(cls) -> None:
        """Disconnect from server"""
        cls.server.close()
        cls.server.disconnect()

    @tryit
    def play_pause(cls) -> None:
        """Toggle play pause"""
        cls.connect()
        # why does this work? mpc pause only pauses and play only plays. mpc has toggle but python-mpd2 doesn't?
        cls.server.pause()
        cls.disconnect()

    @tryit
    def stop(cls) -> None:
        """Stop song and clear queue"""
        cls.connect()
        cls.server.stop()
        cls.disconnect()
        cls.clear_queue()

    @tryit
    def next(cls) -> None:
        """skip to next song in queue"""
        cls.connect()
        cls.server.next()
        cls.disconnect()

    @tryit
    def prev(cls) -> None:
        """skip to previous song in queue"""
        cls.connect()
        cls.server.previous()
        cls.disconnect()

    @tryit
    def enqueue(cls, song: str) -> None:
        """add song to queue"""
        cls.connect()
        cls.server.add("file://" + song)
        cls.disconnect()

    @tryit
    def clear_queue(cls) -> None:
        """Clear queue"""
        cls.connect()
        cls.server.clear()
        cls.disconnect()

    @tryit
    def set_vol(cls, value: int) -> None:
        """Set relative volume"""
        cls.connect()
        cls.server.volume(value)
        cls.disconnect()

    @tryit
    def get_vol(cls) -> None:
        """Placeholder method since mpd gets its volume from the main sync method"""
        pass

    @tryit
    def seek(cls, stime: int) -> None:
        """seek song to time"""
        cls.connect()
        # NOTE force '+' in front of positive int for relative seek
        cls.server.seekcur(str(stime) if stime < 0 else f"+{stime}")
        cls.disconnect()

    @tryit
    def start_queue(cls) -> None:
        """Start playing the first song in the queue"""
        cls.connect()
        cls.server.play()
        cls.disconnect()

    @tryit
    def sync(cls) -> dict:
        """sync status with the server"""
        d = {'State': '',
             'File': '',
             'Title': '',
             'Artist': '',
             'SongTitle': '',
             'Album': '',
             'TotalTime': '0',
             'TimeLeft': '0',
             'TotalSec': '1',  # avoid ZeroDivisionError
             'CurrentTime': '0',
             'CurrentSec': '0',
             'Bitrate': '0',
             'AvgBitrate': '0',
             'Rate': '0',
             'Volume': '0'
             }
        cls.connect()
        status = cls.server.status()
        cur_song = cls.server.currentsong()
        # log("mpd info")
        # log(status)
        # log(cur_song)
        cls.disconnect()
        try:
            d['State'] = status["state"].upper()
            if d["State"] != "STOP":
                d['File'] = cur_song["file"]
                d['Title'] = cur_song["title"] if "title" in cur_song else ""
                d['Artist'] = cur_song["artist"] if "artist" in cur_song else ""
                d['SongTitle'] = cur_song["title"] if "title" in cur_song else ""
                d['Album'] = cur_song["album"] if "album" in cur_song else ""
                d['TotalTime'] = f"{int((int(cur_song["time"]) / 60) % 60):02d}:{int(int(cur_song["time"]) % 60):02d}"
                d['TimeLeft'] = f"{int(((int(cur_song["time"]) - int(float(status["elapsed"]))) / 60) % 60):02d}:{int((int(cur_song["time"]) - int(float(status["elapsed"]))) % 60):02d}"
                d['TotalSec'] = cur_song["time"]
                d['CurrentTime'] = f"{int((float(status["elapsed"]) / (60)) % 60):02d}:{int(float(status["elapsed"]) % 60):02d}"
                d['CurrentSec'] = str(int(float(status["elapsed"])))
                d['Bitrate'] = status["bitrate"]
                d['AvgBitrate'] = '0'
                d['Rate'] = status["audio"] if "audio" in status else "0"
                d['Volume'] = status["volume"]
        except Exception as e:
            log("mpd sync error")
            log(e)
        # log(d)
        return d

    @tryit
    def update(cls) -> None:
        """Updates the music directory with new files
        since mpd doesn't do that automatically if the server isn't running (inotify)
        see also server.rescan() to force rescan all files"""
        cls.connect()
        cls.server.update()
        cls.disconnect()
