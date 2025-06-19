from time import sleep
from typing import Callable

BACKOFF_TIME = 31


def handle_rate_limit(func: Callable) -> int:
    sleep(BACKOFF_TIME)
    func()
