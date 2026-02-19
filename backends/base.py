from abc import ABC, abstractmethod


class backend_abc(ABC):

    @classmethod
    @abstractmethod
    def connect(cls) -> None:
        """Connect to server"""

    @classmethod
    @abstractmethod
    def disconnect(cls) -> None:
        """Disconnect from server"""

    @classmethod
    @abstractmethod
    def play_pause(cls) -> None:
        """Toggle play pause"""

    @classmethod
    @abstractmethod
    def stop(cls) -> None:
        """Stop song"""

    @classmethod
    @abstractmethod
    def next(cls) -> None:
        """skip to next song in queue"""

    @classmethod
    @abstractmethod
    def prev(cls) -> None:
        """skip to previous song in queue"""

    @classmethod
    @abstractmethod
    def enqueue(cls, song: str) -> None:
        """add song to queue"""

    @classmethod
    @abstractmethod
    def clear_queue(cls) -> None:
        """Clear queue"""

    @classmethod
    @abstractmethod
    def set_vol(cls, value: int) -> None:
        """Set relative volume"""

    @classmethod
    @abstractmethod
    def get_vol(cls, value: str) -> int:
        """Get volume"""

    @classmethod
    @abstractmethod
    def seek(cls, stime: int) -> None:
        """seek song to time"""

    @classmethod
    @abstractmethod
    def start_queue(cls) -> None:
        """Start playing the first song in the queue"""

    @classmethod
    @abstractmethod
    def sync(cls) -> dict:
        """sync status with the server"""
