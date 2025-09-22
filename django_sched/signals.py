from django.dispatch import Signal


__all__ = [
    "scheduler_started",
    "scheduler_stopped",
    "tick_started",
    "tick_ended",
    "tick_error",
]


# 内置调度器的生命周期
scheduler_started = Signal()      # payload: instance, mode, pid
scheduler_stopped = Signal()    # payload: instance, reason

tick_started = Signal()         # payload: scheduler instance, tick_time
tick_ended = Signal()           # payload: scheduler instance, tick_time
tick_error = Signal()         # payload: scheduler instance, tick_time, traceback

