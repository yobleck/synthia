#!/usr/bin/env python3
from functools import partial
import itertools
import json
import math
import os
import signal
import subprocess
import sys
import termios
import threading

import setproctitle
import wcwidth

import utils


if len(sys.argv) > 1 and sys.argv[1] in ["h", "-h", "help", "-help", "--help"]:
    print("""SYNTHIA HELP SCREEN:
args:
    -h, --help:     shows this screen

keybinds:
    q:              quit
    space:          toggle play/pause
    s:              stop
    b/n:            previous/next song
    ,/.:            volume up/down
    enter:          enter folder/add song and all songs after it in folder to queue
    left/right:     seek +/-2 seconds
    up/down:        scroll song list
    pgup/pgdn:      scroll song list by 10
    m:              cycle sort mode
    M:              toggle sort reverse mode

backends:
    mocp (mocp is currently broken on my computer)
    xmms2 (mostly functional)
    mpd (recommended)

notes:
    only use full absolute file paths in settings.json and m3u8 playlist files
    all #EXT info in m3u8 files is ignored

TODO:
    make keybinds a config file
    home end keys to go to top and bottom of folder
    add songs before cursor to end of playlist or add repeat option
    add more info to status bar like volume, repeat, shuffle
    path to config file cmd arg""")
    sys.exit(0)


# Misc global variables
u_esc: str = "\x1b["  # no backslashes in f strings
invt_clr: str = "\x1b[7m"  # move to UI?


# Functions
def sig_handler(sig, frame):
    if sig == signal.SIGINT:
        timer.cancel()
        print("\x1b[2J\x1b[H\x1b[?25h", end="")
        sys.exit(0)
    elif sig == signal.SIGWINCH:
        old_scrn_h = UI.scrn_size[1]
        UI.scrn_size = list(os.get_terminal_size())  # TODO minimum size?
        UI.scrn_size[1] -= 1
        UI.list_slice[1] = UI.list_slice[1] - (old_scrn_h - UI.scrn_size[1])
        UI.draw_list()
        UI.draw_status_bar()


def getch(blocking: bool = True, bytes_to_read: int = 1) -> str:
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    new = list(old_settings)
    new[3] &= ~(termios.ICANON | termios.ECHO)
    new[6][termios.VMIN] = 1 if blocking else 0
    new[6][termios.VTIME] = 0  # 0 is faster but inputs appear on screen?
    termios.tcsetattr(fd, termios.TCSADRAIN, new)
    try:
        ch = sys.stdin.read(bytes_to_read)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


esc_chars = {"[A": "up", "[B": "dn", "[C": "rt", "[D": "lf", "[F": "end", "[H": "home", "[[A": "F1",
             "[[B": "F2", "[[C": "F3", "OS": "F4", "[Z": "shft+tb", "[5~": "pgup", "[6~": "pgdn",  # "OR": "F3"
             "[15~": "F5", "[17~": "F6", "[18~": "F7", "[19~": "F8", "[20~": "F9", "[21~": "F10",
             "[23~": "F11", "[24~": "F12"}  # TODO fix more F keys


def handle_esc() -> str:  # TODO only using keys with length 3?
    """https://en.wikipedia.org/wiki/ANSI_escape_code
    I don't know if this holds across all computers/keyboards
    or if my setup just weird?
    BUG: holding down key that uses less than 4 esc chars will capture
    first char of next sequence early so next characters are captured as plain text"""
    a = getch(False, 4)
    if a in esc_chars.keys():
        # utils.log("key: " + a)
        return esc_chars[a]
    elif a == "":
        return "esc"
    # utils.log("failed " + a)
    return ""


def folder_sort(folder: str, sort_mode: str, reverse: bool = False) -> list:
    """Get files, sort them, filter only audio files"""
    do_sort = False if sort_mode == "name" else True
    files: list = subprocess.run(f"LC_COLLATE=en_US.utf8 ls -1pA{'r' * reverse} {'--sort=' * do_sort}{sort_mode * do_sort} "
                                 f"--group-directories-first '{folder}'",
                                 shell=True, stdout=subprocess.PIPE).stdout.decode().splitlines()
    # TODO replace all the below with find or awk?
    to_remove = []  # removing files from a list while iterating over it causes skips
    for i, f in enumerate(files):
        if f[-1] == "/":
            continue
        elif f[-4:] not in [".aac", "flac", ".mp3", "m3u8", ".m4a", ".ogg", ".oga", ".wav", ".wma"]:
            to_remove.append(f)
    for r in to_remove:
        files.remove(r)
    files.insert(0, "../")
    print("\x1b[2J\x1b[H")  # NOTE why is this here?
    return files


def open_m3u8(file: str) -> list:
    """Open m3u8 playlist file and pretend its a folder
    https://en.wikipedia.org/wiki/M3U
    """
    utils.log("WARNING: parsing m3u8. make sure this is from a trusted source. this program has no security against injection attacks")
    with open(file, "r") as pl:
        files: list = ["../"]
        for line in pl.readlines():
            line2 = line.removesuffix("\n")
            if line2[0] != "#":  # skip comment lines. there shouldn't be comments on same line as file path
                if os.path.isfile(line2):  # check if file is valid. don't forget to strip \n
                    files.append(line2)
                else:
                    utils.log(f"{line2} is not a valid file path")
    return files


def add_songs_to_queue_and_play(songs: list, start_pos: int, folder: str) -> None:
    """not sure how to explain why I'm doing it like this"""
    # TODO mocp fix first song not playing until done. make this function a background thread (threading or multiprocessing?) kill thread with sig handler for clean socket writing
    # if "STOP" not in UI.current_song_info["State"]:
    if config["backend"] != "mocp" or "STOP" not in UI.current_song_info["State"]:  # handle mocp crash when sending stop while stopped
        backend.stop()  # stop currently playing and clear queue
    for s in songs[start_pos:]:  # TODO loop around. len(list) = 10. list[5:] + list[:5] etc. how to get 5?
        if s[-1] != "/" and s[-4:] != "m3u8":
            # utils.log(f"song path: {folder + s}")
            backend.enqueue(folder + s)

    backend.start_queue()


# TODO should this be function called in main?
config: dict = {  # default config values that don't rely on any other code for their definition
    "backend": None,  # options: "mocp", "xmms2", "mpd"
    "update_rate": 1,  # seconds
    "volume": 50,  # 0-100%  # currently unused
    "starting_folder": utils.home_dir,
    "sort_mode": "name",  # options: "name", "time", and "size"
    "sort_reversed": False,  # options: True, False
    "main_clr": "32",  # these colors are ansi colors in the format "\u001b[foreground_color;background_color"
    "dir_clr": "31",  # https://gist.github.com/fnky/458719343aabd01cfb17a3a4f7296797#color-codes
    "file_clr": "32",
    "m3u8_clr": "34",
    "bg_clr": "40",  # background color uses the background color code
    "misc_clr": "36",
    "mocp_settings": {},
    "mpd_settings": {"address": "localhost", "port": 6600},  # TODO written in 3 places. simplify
    "xmms2_settings": {"address": ""}
    # TODO volume seek and scroll to home/end
}

# parse config file. NOTE This has to be done here because other bits of code rely on this happening before main
if os.path.exists(f"{utils.home_dir}synthia/synthia_settings.json"):
    with open(f"{utils.home_dir}synthia/synthia_settings.json", "r") as f:
        temp_dict: dict = json.load(f)
    for k in temp_dict.keys():
        if k in config.keys():
            config[k] = temp_dict[k]

# TODO start server if it isn't running?
if config["backend"] == "mocp":
    from backends.mocp import mocp_backend
    backend = mocp_backend()
    backend.settings = config["mocp_settings"]
elif config["backend"] == "mpd":
    from backends.mpd import mpd_backend
    backend = mpd_backend()
    backend.settings = config["mpd_settings"]
    backend.update()  # NOTE server doesn't do this automatically if not running
elif config["backend"] == "xmms2":
    from backends.xmms2 import xmms2_backend
    backend = xmms2_backend()
    backend.settings = config["xmms2_settings"]
else:
    print("\x1b[2J\x1b[H\x1b[?25h", end="")
    print("Error: back end not found or not specified or server not running")
    sys.exit(1)


class UI():
    scrn_size: list = list(os.get_terminal_size())
    scrn_size[1] -= 1  # - 1 for kitty weirdness?
    current_folder: str = config["starting_folder"]

    sort_cycle = itertools.cycle(["name", "size", "time"])
    sort_mode = config["sort_mode"]
    while True:
        if sort_mode == next(sort_cycle):
            break
    sort_reversed: bool = config["sort_reversed"]

    song_list: list = folder_sort(current_folder, sort_mode, sort_reversed)
    list_slice: list = [0, scrn_size[1] - 6]  # (top, bottom). - x for progress bar
    selected_song: int = 0  # between 0 and len(song_list)  TODO save selected song from parent folder for when going back to it?
    current_song_info: dict = backend.sync()
    # volume: int = config["volume"]

    @classmethod
    def draw_list(cls) -> None:
        """draw borders, slice of list of files, highlight currently playing and selected, play/pause/stop state
        then call update_prog_bar
        """
        # TODO handle file names longer than screen width
        print(f"\x1b[0;0H\x1b[K{u_esc + config['main_clr'] + 'm'}┌─┤SYNTHIA├{'─' * 10}┤{cls.current_folder}├"
              f"{'─' * (cls.scrn_size[0] - len(cls.current_folder) - 24)}┐")  # ┌─┐

        for num, song in enumerate(cls.song_list[cls.list_slice[0]:cls.list_slice[1] + 1]):  # + 1 to include last item
            # line color
            if song[-1] == "/":
                line_color = u_esc + config["dir_clr"] + "m"
            elif song[-4:] == "m3u8":
                line_color = u_esc + config["m3u8_clr"] + "m"
            else:
                line_color = u_esc + config["file_clr"] + "m"
            # list of files
            print(f"\x1b[K│{num + cls.list_slice[0]:04d} {line_color}{invt_clr * (num + cls.list_slice[0] == cls.selected_song)}{song}"
                  f"\x1b[27m{' ' * (cls.scrn_size[0] - wcwidth.wcswidth(song) - 7)}{u_esc + config['main_clr'] + 'm'}│")
        for _ in range(cls.scrn_size[1] - num - 6):
            # filler border if files < height of window
            print(f"\x1b[K{u_esc}{config['main_clr'] + 'm'}│{' ' * (cls.scrn_size[0] - 2)}│{u_esc + config['main_clr'] + 'm'}")
        # bottom of list
        print(f"\x1b[K{u_esc}{config['main_clr'] + 'm'}├{'─' * (cls.scrn_size[0] - 2)}┤{u_esc + config['main_clr'] + 'm'}")

    @classmethod
    def draw_status_bar(cls) -> None:
        # https://cloford.com/resources/charcodes/utf-8_box-drawing.htm
        cls.current_song_info = backend.sync()

        # status and name of song
        if cls.current_song_info['Title'] or cls.current_song_info['Artist']:
            title_or_file = f"{cls.current_song_info['Artist']} - {cls.current_song_info['Title']}"
        else:
            title_or_file = cls.current_song_info['File']

        print(f"\x1b[{cls.scrn_size[1] - 2};0H\x1b[K{u_esc + config['main_clr'] + 'm'}"
              f"│{cls.current_song_info['State']} > {title_or_file}"
              f"{' ' * (cls.scrn_size[0] - len(cls.current_song_info['State']) - wcwidth.wcswidth(title_or_file) - 5)}"
              f"│{u_esc + config['main_clr'] + 'm'}")

        # sort mode TODO other info like volume, repeat etc.
        print(f"\x1b[{cls.scrn_size[1] - 1};0H\x1b[K│{u_esc}{config['misc_clr'] + 'm'}"
              f"sort mode: [{cls.sort_mode}]  reversed: [{cls.sort_reversed}]"
              f" vol: [{int(cls.current_song_info['Volume']):03d}%]"
              f"{' ' * (cls.scrn_size[0] - len(cls.sort_mode + str(cls.sort_reversed)) - 41)}{u_esc + config['main_clr'] + 'm'}│")

        # progress bar
        print(f"\x1b[{cls.scrn_size[1]};0H\x1b[K{u_esc + config['main_clr'] + 'm'}"
              f"├─┤{cls.current_song_info['CurrentTime']} {cls.current_song_info['TimeLeft']}"
              f" [{cls.current_song_info['TotalTime']}]─{cls.progress_bar()}")
        print(f"\x1b[K{u_esc}{config['main_clr'] + 'm'}└{'─' * (cls.scrn_size[0] - 2)}┘{u_esc + config['main_clr'] + 'm'}", end="")
        sys.stdout.flush()  # BUG flickering caused by last line? replace end with ANSI go up line?

    @classmethod
    def progress_bar(cls) -> str:
        """calculate what the progress bar should look like"""
        bar_width: int = cls.scrn_size[0] - 12 - len(cls.current_song_info["CurrentTime"]) -\
            len(cls.current_song_info["TimeLeft"]) - len(cls.current_song_info["TotalTime"])  # other characters on line add up to 12
        percent: float = int(cls.current_song_info["CurrentSec"]) / int(cls.current_song_info["TotalSec"])
        bar: str = f"┤{'█' * math.floor(percent * bar_width)}{' ' * (bar_width - math.floor(percent * bar_width))}├─┤"
        # █ = \u2588, ┤ = \u2524, ├ = \u251c
        return bar

    @classmethod
    def scroll(cls, amount: int) -> None:
        # NOTE outer if statement allows for scrolling cursor to last values. inner ifs correct for over shooting
        if 0 <= cls.selected_song < len(cls.song_list):
            cls.selected_song += amount
            if cls.selected_song < 0:  # scroll up
                cls.selected_song = 0
            elif cls.selected_song > len(cls.song_list) - 1:  # scroll down
                cls.selected_song = len(cls.song_list) - 1

        # handles scrolling the entire screen to keep cursor visible
        if cls.selected_song > cls.list_slice[1]:  # scroll down
            shift = cls.selected_song - cls.list_slice[1]
            cls.list_slice = [cls.list_slice[0] + shift, cls.list_slice[1] + shift]
        elif cls.selected_song < cls.list_slice[0]:  # scroll up
            shift = cls.list_slice[0] - cls.selected_song
            cls.list_slice = [cls.list_slice[0] - shift, cls.list_slice[1] - shift]

    @classmethod
    def enter(cls) -> None:
        """enter folder, handle .m3u8 file or play song"""
        if cls.song_list[cls.selected_song][-1] == "/":  # handle folders
            if cls.song_list[cls.selected_song][-3:] == "../":  # go up a folder
                cls.current_folder = cls.current_folder.rsplit("/", 2)[0] + "/"  # BUG goes up one folder to far when in m3u8 file
                cls.song_list = folder_sort(cls.current_folder, cls.sort_mode, cls.sort_reversed)
                cls.selected_song = 0

            else:  # go into a folder
                cls.current_folder = cls.current_folder + cls.song_list[cls.selected_song]
                cls.song_list = folder_sort(cls.current_folder, cls.sort_mode, cls.sort_reversed)
                cls.selected_song = 0

        elif cls.song_list[cls.selected_song][-4:] == "m3u8":  # open playlist file
            cls.current_folder = cls.current_folder + cls.song_list[cls.selected_song]
            cls.song_list = open_m3u8(cls.current_folder)
            cls.selected_song = 0

        else:  # play song and add other songs to play queue
            if cls.current_folder[-4:] == "m3u8":  # NOTE m3u8 file already has full file path so ignore folder arg
                add_songs_to_queue_and_play(cls.song_list, cls.selected_song, "")
            else:
                add_songs_to_queue_and_play(cls.song_list, cls.selected_song, cls.current_folder)

    @classmethod
    def cycle_sort(cls):
        cls.sort_mode = next(cls.sort_cycle)
        cls.song_list = folder_sort(cls.current_folder, cls.sort_mode, cls.sort_reversed)

    @classmethod
    def reverse_sort(cls):
        cls.sort_reversed = not cls.sort_reversed
        cls.song_list = folder_sort(cls.current_folder, cls.sort_mode, cls.sort_reversed)


# TODO make the keybinds a config file?
config.update({  # default config values that have to be defined after UI() and backend
    "key_binds": {" ": partial(backend.play_pause),  # play/pause
                  "s": partial(backend.stop),  # stop and clear playlist

                  "n": partial(backend.next),  # next song
                  # BUG back only works with playlist, not queue
                  "b": partial(backend.prev),  # previous song
                  # TODO get volume info
                  ",": partial(backend.set_vol, -5),  # vol -5%
                  ".": partial(backend.set_vol, 5),  # vol +5%

                  "up": partial(UI.scroll, -1),  # scroll up
                  "dn": partial(UI.scroll, 1),  # scroll down
                  "pgup": partial(UI.scroll, -10),  # scroll up 10 at a time
                  "pgdn": partial(UI.scroll, 10),  # scroll down 10 at a time

                  "lf": partial(backend.seek, -2),  # seek -1 s
                  "rt": partial(backend.seek, 2),  # seek +1 s

                  "\n": partial(UI.enter),  # play song or enter folder. TODO handle .m3u8

                  "m": partial(UI.cycle_sort),  # cycle sort modes
                  "M": partial(UI.reverse_sort),  # toggle sort reverse
                  # TODO
                  # "c": clear playlist? happens automatically when stopping or changing playlist
                  # "/": search function?
                  # "r" repeat mode
                  # shuffle mode
                  # goto folder of currently playing song
                  "T": partial(backend.start_queue),  # testing
                  "Y": partial(backend.seek, 5),  # testing
                  },
})


class RepeatTimer(threading.Timer):  # TODO sync timer to song start? EV_AUDIO_START/STOP
    # paused = false
    def run(self):
        while not self.finished.wait(self.interval):
            # if not paused:
            self.function(*self.args, **self.kwargs)


if __name__ == "__main__":
    setproctitle.setproctitle("synthia")  # these are here because they only matter when the program is looping
    for signum in [signal.SIGINT, signal.SIGWINCH]:
        signal.signal(signum, sig_handler)

    timer = RepeatTimer(config["update_rate"], UI.draw_status_bar)
    timer.start()

    print("\x1b[2J\x1b[H\x1b[?25l")
    UI.draw_list()
    UI.draw_status_bar()

    while True:
        char = getch()
        if char == "\x1b":
            char = handle_esc()
            if char == "esc":
                break
            elif char in config["key_binds"].keys():
                config["key_binds"][char]()
        elif char == "q":
            break
        elif char in config["key_binds"].keys():
            config["key_binds"][char]()

        UI.draw_list()
        UI.draw_status_bar()

    # TODO write certain values back out to the config file
    timer.cancel()
    print("\x1b[2J\x1b[H\x1b[?25h", end="")
