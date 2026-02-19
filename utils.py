"""Utility functions etc."""
import os
import time


home_dir = os.path.expanduser("~") + "/"


def log(i):
    """Logging function"""
    with open(f"{home_dir}synthia/test.log", "a") as f:
        f.write(f"{time.asctime()}: {str(i)}\n")


def tryit(func):
    """try except decorator @"""
    def inner(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            log(f"tryit '{func.__name__}' error:")
            log(e)
    return inner
