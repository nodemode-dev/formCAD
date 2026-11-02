import threading

_subscribers: list = []
_lock = threading.Lock()


def subscribe(fn) -> None:
    with _lock:
        if fn not in _subscribers:
            _subscribers.append(fn)


def unsubscribe(fn) -> None:
    with _lock:
        if fn in _subscribers:
            _subscribers.remove(fn)


def publish(message: dict) -> None:
    with _lock:
        targets = list(_subscribers)
    for fn in targets:
        try:
            fn(message)
        except Exception:
            pass
    try:
        from app.routers.events import hub
    except Exception:
        return
    try:
        hub.publish(message)
    except Exception:
        pass
