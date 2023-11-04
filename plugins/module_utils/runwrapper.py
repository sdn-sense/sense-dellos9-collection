import time
from ansible.utils.display import Display

display = Display()

def functionwrapper(func):
    def wrapper(*args, **kwargs):
        if display.verbosity > 5:
            display.vvvvvv(f"[WRAPPER][{time.time()}] Enter {func.__qualname__}, {func.__code__.co_filename}")
            start_time = time.perf_counter()
            result = func(*args, **kwargs)
            end_time = time.perf_counter()
            total_time = end_time - start_time
            display.vvvvvv(f"[WRAPPER][{time.time()}] Function {func.__qualname__} {args} {kwargs} Took {total_time:.4f} seconds")
            display.vvvvvv(f"[WRAPPER][{time.time()}] Leave {func.__qualname__}")
        else:
            result = func(*args, **kwargs)
        return result

    return wrapper

def classwrapper(cls):
    for name, method in cls.__dict__.items():
        if callable(method) and name != "__init__":
            setattr(cls, name, functionwrapper(method))
    return cls