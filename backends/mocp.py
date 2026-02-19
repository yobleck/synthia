import os
import socket
import struct
import subprocess
import sys
import time

from .base import backend_abc

sys.path.append("..")
from utils import log, tryit


home_dir = os.path.expanduser("~") + "/"


class mocp_backend(backend_abc):
    """https://github.com/jonsafari/mocp/blob/master/protocol.h"""
    settings: dict = {}
    address: str = f"{home_dir}.moc/socket2"  # TODO config option
    sock = None

    @tryit
    def connect(cls):
        cls.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        cls.sock.connect(cls.address)

    @tryit
    def disconnect(cls):
        cls.sock.shutdown(socket.SHUT_RDWR)  # TODO sock.detach() ?
        cls.sock.close()

    @tryit
    def play_pause(cls):
        cls.connect()
        cls.sock.send(b'\x13\x00\x00\x00')
        while cls.sock.recv(1) != b'\x06':
            pass
        cls.sock.recv(3)

        ret = cls.sock.recv(4)
        if ret == b'\x01\x00\x00\x00':  # playing state
            cls.sock.send(b'\x05\x00\x00\x00')  # pause song
        elif ret == b'\x03\x00\x00\x00':  # paused state
            cls.sock.send(b'\x06\x00\x00\x00')  # play song

        cls.disconnect()

    @tryit
    def stop(cls):
        log("stopping")
        cls.connect()
        cls.sock.send(b'\x04\x00\x00\x00')  # stop song
        # wait for server state to finish updating
        # log(cls.sock.recv(64))
        while cls.sock.recv(1) != b'\x01':
            pass
        log("post stop loop")
        cls.sock.recv(3)
        cls.sock.send(b'\x3e\x00\x00\x00')  # clear queue
        cls.disconnect()

    @tryit
    def next(cls):
        cls.connect()
        cls.sock.send(b'\x10\x00\x00\x00')  # next song
        cls.disconnect()

    @tryit
    def prev(cls):  # BUG doesn't work with queue
        cls.connect()
        cls.sock.send(b'\x20\x00\x00\x00')  # prev song
        cls.disconnect()

    @tryit
    def enqueue(cls, song):
        log("queueing")
        time.sleep(0.01)  # NOTE to lazy to wait and ensure socket has been read from/cleared
        song = song.encode()
        cls.connect()
        cls.sock.send(b'\x3b\x00\x00\x00')  # send to queue
        cls.sock.send(struct.pack('I', len(song)))  # song file path size
        cls.sock.send(song)  # song file path
        while cls.sock.recv(4) != b'\xff\xff\xff\xff':  # clear out return info from server
            pass
        cls.sock.recv(16)
        cls.disconnect()

    @tryit
    def clear_queue(cls):
        cls.connect()
        cls.sock.send(b'\x3e\x00\x00\x00')  # clear queue
        cls.disconnect()

    @tryit
    def set_vol(cls, val: int):
        """Set relative volume"""
        cls.connect()
        # get current vol  NOTE made redundant by get_vol()?
        cls.sock.send(b'\x1a\x00\x00\x00')
        while cls.sock.recv(1) != b'\x06':
            pass
        cls.sock.recv(3)
        # adjust vol
        vol = struct.unpack("I", cls.sock.recv(4))[0] + val
        # clamp vol
        if vol < 0:
            vol = 0
        elif vol > 100:
            vol = 100
        cls.sock.send(b'\x1b\x00\x00\x00')  # set volume
        cls.sock.send(struct.pack('I', vol))  # volume value
        cls.disconnect()

    @tryit
    def get_vol(cls) -> int:
        """Get volume"""
        cls.connect()
        # get current vol
        cls.sock.send(b'\x1a\x00\x00\x00')
        while cls.sock.recv(1) != b'\x06':
            pass
        cls.sock.recv(3)
        vol = struct.unpack("I", cls.sock.recv(4))[0]
        cls.disconnect()
        return vol

    @tryit
    def seek(cls, stime):
        """amount to adjust volume by"""
        cls.connect()
        cls.sock.send(b'\x12\x00\x00\x00')  # set volume
        cls.sock.send(struct.pack('i', stime))  # volume value
        cls.disconnect()
        # UI.draw_status_bar()  # BUG flickering when holding key

    @tryit
    def start_queue(cls):
        log("start queue")
        cls.connect()
        cls.sock.send(b'\x06\x00\x00\x00')  # play
        cls.sock.send(b'\x00\x00\x00\x00')  # AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
        cls.sock.send(b'\x00\x00\x00\x00')  # AAAAAAAAAAAAAAAAAAAAAHHHHHHHHHHHHHHHHHHHHHH
        # BUG remove byte and it never finishes. have 12 bytes and server crashes buffer Overflow
        # caused by pulse audio patch?
        # compile og?
        cls.disconnect()

    @tryit
    def sync(cls) -> dict:
        """sync status with the server"""
        """sync with moc server via socket https://github.com/jonsafari/mocp/blob/master/protocol.h
        using subprocess mocp -i for now
        """
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
        in_list = subprocess.run("mocp -i", shell=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE).stdout.decode().splitlines()
        if in_list:  # NOTE list is empty if server not running
            for i in in_list:
                d[i.split(": ")[0]] = i.split(": ")[1]
            d["Volume"] = cls.get_vol()
        return d
