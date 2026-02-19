# xmms2 backend
# source code:  https://github.com/xmms2/xmms2-stable/blob/master/src/clients/lib/python/xmmsapi.pyx
# tutorial: https://github.com/xmms2/xmms2-tutorial/tree/master/python
import getpass
import os
import sys

import xmmsclient

from .base import backend_abc

sys.path.append("..")
from utils import log, tryit


home_dir = os.path.expanduser("~") + "/"

status_dict: dict = {0: "STOP", 1: "PLAY", 2: "PAUSE"}


class xmms2_backend(backend_abc):
    """xmms2 backend"""
    settings: dict = {"address": ""}
    server = xmmsclient.XMMS("synthia")

    def get_results(cls, func: callable):
        # TODO all the result.wait stuff is tedious. condense into one function?
        r = func()
        r.wait()
        if r.is_error():
            log(f"xmms2 {func} error: {r.get_error()}")
        return r.value()

    @tryit
    def connect(cls) -> None:
        """Connect to server
        TODO handle XMMS_PATH env var and get username for /tmp
        check if server is running
        """
        try:
            cls.server.connect(f"/tmp/xmms-ipc-{getpass.getuser()}" if not cls.settings["address"] else cls.settings["address"])
        except IOError as e:
            # NOTE full traceback info: https://stackoverflow.com/questions/3702675/catch-and-print-full-python-exception-traceback-without-halting-exiting-the-prog
            print(f"{e}\nIs the xmms2 server running?")
            sys.exit(1)

    @tryit
    def disconnect(cls) -> None:
        """Disconnect from server"""
        cls.server.disconnect()

    @tryit
    def play_pause(cls) -> None:
        """Toggle play pause"""
        cls.connect()
        result = cls.server.playback_status()
        result.wait()
        if result.iserror():
            log(f"play/pause error: {result.get_error()}")
        # log(f"playback status: {result.value()}")
        if result.value() == 1:  # playing
            r = cls.server.playback_pause()
            r.wait()
        elif result.value() == 2:  # paused
            r = cls.server.playback_start()
            r.wait()
        # TODO handle playing from stopped? prob not, stop should clear queue?
        cls.disconnect()

    @tryit
    def stop(cls) -> None:
        """Stop song and clear queue"""
        cls.connect()
        r = cls.server.playback_stop()
        r.wait()
        # TODO clear queue?
        cls.disconnect()
        cls.clear_queue()

    @tryit
    def next(cls) -> None:
        """skip to next song in queue"""
        cls.connect()
        result = cls.server.playlist_set_next_rel(1)
        result.wait()
        result = cls.server.playback_tickle()
        result.wait()
        cls.disconnect()

    @tryit
    def prev(cls) -> None:
        """skip to previous song in queue"""
        cls.connect()
        result = cls.server.playlist_set_next_rel(-1)
        result.wait()
        result = cls.server.playback_tickle()
        result.wait()
        cls.disconnect()

    @tryit
    def enqueue(cls, song: str) -> None:
        """add song to queue"""
        cls.connect()
        result = cls.server.playlist_add_url("file://" + song)
        result.wait()
        if result.iserror():
            log(f"enqueue error: {result.get_error()}")
        cls.disconnect()

    @tryit
    def clear_queue(cls) -> None:
        """Clear queue"""
        cls.connect()
        result = cls.server.playlist_clear()
        result.wait()
        cls.disconnect()

    @tryit
    def set_vol(cls, value: int) -> None:
        """Set relative volume"""
        cls.connect()
        result = cls.server.playback_volume_get()  # redundant with get volume?
        result.wait()
        # log(f"vol before: {result.value()}")
        vol = result.value()["master"] + value
        if vol < 0:
            vol = 0
        elif vol > 100:
            vol = 100
        result = cls.server.playback_volume_set("master", vol)
        result.wait()
        cls.disconnect()

    @tryit
    def get_vol(cls) -> int:
        cls.connect()
        volume = 0
        result = cls.server.playback_volume_get()
        result.wait()
        volume = result.value()["master"]
        cls.disconnect()
        return volume

    @tryit
    def seek(cls, stime: int) -> None:
        """seek song to time"""
        stime = stime * 1000  # convert to milliseconds
        cls.connect()
        result = cls.server.playback_playtime()  # no relative seek? get current time and do math instead
        result.wait()
        stime = result.value() + stime
        result = cls.server.playback_seek_ms(stime)
        result.wait()
        cls.disconnect()

    @tryit
    def start_queue(cls) -> None:
        """Start playing the first song in the queue"""
        # TODO unknown bug when starting queue
        cls.connect()
        result = cls.server.playback_start()
        result.wait()
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
        r = cls.server.playback_current_id()
        r.wait()  # TODO handle potential connection errors
        # TODO clean this mess up
        if r.is_error():
            log(1)
            log(r.get_error())
            return
        cur_song = r.value()
        r = cls.server.playback_playtime()
        r.wait()
        if r.is_error():
            log(2)
            log(r.get_error())
            return
        p_time = r.value()
        r = cls.server.playback_status()
        r.wait()
        if r.is_error():
            log(3)
            log(r.get_error())
            return
        status = r.value()
        r = cls.server.medialib_get_info(cur_song)
        r.wait()
        if r.is_error():
            # this one doesnt have get_error
            pass
        info = r.value()
        log("xmms info")
        log(cur_song)
        log(p_time)
        log(status)
        log(info)
        cls.disconnect()
        # TODO handle tags only existing on some songs
        d['State'] = status_dict[status]
        if d["State"] != "STOP":
            d['File'] = info[('server', 'url')]
            d['Title'] = info[('plugin/id3v2', 'title')] if ('plugin/id3v2', 'title') in info else ""
            d['Artist'] = info[('plugin/id3v2', 'artist')] if ('plugin/id3v2', 'artist') in info else ""
            d['SongTitle'] = info[('plugin/id3v2', 'title')] if ('plugin/id3v2', 'title') in info else ""
            d['Album'] = info[('plugin/id3v2', 'album')] if ('plugin/id3v2', 'album') in info else ""
            # BUG with :02d causing the status bar to overshoot the line and scroll the page
            d['TotalTime'] = f"{int((info[('plugin/mad', 'duration')] / (1000 * 60)) % 60):02d}:{int((info[('plugin/mad', 'duration')] / 1000) % 60):02d}"
            d['TimeLeft'] = f"{int(((info[('plugin/mad', 'duration')] - p_time) / (1000 * 60)) % 60):02d}:{int(((info[('plugin/mad', 'duration')] - p_time) / 1000) % 60):02d}"
            d['TotalSec'] = str(int(info[('plugin/mad', 'duration')] / 1000))
            d['CurrentTime'] = f"{int((p_time / (1000 * 60)) % 60):02d}:{int((p_time / 1000) % 60):02d}"
            d['CurrentSec'] = str(int(p_time / 1000))
            d['Bitrate'] = str(info[('plugin/mad', 'bitrate')])
            d['AvgBitrate'] = '0'
            d['Rate'] = str(info[('plugin/mad', 'samplerate')])
            d['Volume'] = str(cls.get_vol())  # BUG when changing song causes invalid result?
        # log(d)
        return d
