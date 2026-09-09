from arq import run_worker

from .worker import WorkerSettings

if __name__ == "__main__":
    # `run_worker` is synchronous: it owns the event loop and returns the
    # finished Worker. Wrapping it in `asyncio.run` raised "a coroutine was
    # expected" on every start, and Fly restarted the process eight times a
    # day for as long as the project existed. The Control Plane's own entry
    # point has always called it bare.
    run_worker(WorkerSettings)
