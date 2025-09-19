# django_sched/core.py
import time
import logging
import traceback
import warnings
from datetime import timedelta, datetime
from django.db import transaction, IntegrityError
from django.utils import timezone
from abc import ABC, abstractmethod
from threading import Thread, Event
from django_sched import signals, models
from django.conf import settings
from django.utils.module_loading import import_string
from typing import TypedDict, Literal

try:
    from billiard import ensure_multiprocessing
    from billiard.context import Process
except ImportError:
    warnings.warn("billiard not available")
    Process = None
    def ensure_multiprocessing():
        raise NotImplementedError("multiprocessing not available")


logger = logging.getLogger("django_sched")


class SchedulerException(Exception):
    pass


class SchedulerKwargs(TypedDict):
    ENABLED: bool
    ENABLE_LOGGING: bool
    LOGGING_LEVEL: Literal["SUCCESS", "ERROR"] | None
    INTERVAL: int | float | timedelta


class BaseScheduler(ABC):
    name: str = None
    enabled: bool = True
    enable_logging: bool = True
    logging_level: Literal["SUCCESS", "ERROR"] | None = None
    interval: int | timedelta = timedelta(seconds=1)
    last_schedule_time: datetime = timezone.now()
    model = None

    def __init__(self, model: models.Scheduler = None, **kwargs):
        self.update_kwargs(**kwargs)
        if self.name is None:
            self.name = self.__class__.__name__
        self.model = model or self.model or models.Scheduler(
            name=self.name,
            interval=self.interval,
        )

    def update_kwargs(self, **kwargs):
        protected_kwargs = ["SCHEDULERS"]
        for k, v in kwargs.items():
            if k.upper() in protected_kwargs:
                continue
            if k.upper() not in SchedulerKwargs.__annotations__:
                raise SchedulerException(f"invalid kwarg: {k} = {v}")
            setattr(self, k.lower(), v)
        if isinstance(self.interval, timedelta):
            self.interval = int(self.interval.total_seconds())

    @property
    def logger(self):
        return logger

    @abstractmethod
    def schedule(self, now):
        """
        执行调度任务
        :return:
        """

    def is_due(self, now=None):
        now = now
        elapsed = (now - self.last_schedule_time).total_seconds()
        delay = max(self.interval - elapsed, 0)
        ready = elapsed >= self.interval
        return ready, delay

    def tick(self) -> tuple[models.SchedulerLog | None, int | float]:
        now = timezone.now()
        is_due, delay = self.is_due(now=now)
        if is_due:
            log = self._schedule(now)
            self.last_schedule_time = now
            return log, self.interval
        return None, delay

    def _schedule(self, now) -> models.SchedulerLog:
        log = models.SchedulerLog(scheduler=self.name, started_at=now, owner=self.model.owner, success=True)
        try:
            self.schedule(now)
        except Exception as e:
            logger.exception(e)
            message = traceback.format_exc()
            log.message = message
            log.success = False
        log.finished_at = timezone.now()
        log.duration = (log.finished_at - log.started_at).total_seconds()
        if self.enable_logging:
            if self.logging_level == "ERROR" and log.success:
                logger.debug(f"{self.name} schedule finished in {log.duration}s, success: {log.success}")
            else:
                log.save()
        else:
            logger.debug(f"{self.name} schedule finished in {log.duration}s, success: {log.success}")
        return log


def load_schedulers() -> list[BaseScheduler]:
    """
    Load scheduler classes defined in settings.DJANGO_SCHED['SCHEDULERS'].
    Each class must be a subclass of BaseScheduler.
    """
    scheduler_classes = getattr(settings, "DJANGO_SCHED", {}).get("SCHEDULERS", {})
    if not scheduler_classes:
        logger.warning("No schedulers configured in settings.DJANGO_SCHED['SCHEDULERS']")
        return []
    schedulers = []
    for cls_path, kwargs in scheduler_classes.items():
        kwargs: SchedulerKwargs
        try:
            cls = import_string(cls_path)
        except ImportError as e:
            logger.error(f"Failed to import scheduler {cls_path}: {e}")
            continue

        if not issubclass(cls, BaseScheduler):
            logger.warning(f"{cls_path} is not a subclass of BaseScheduler")
            continue
        try:
            scheduler_instance = cls(**kwargs)
            if scheduler_instance.enabled:
                schedulers.append(scheduler_instance)
                logger.info(f"Loaded scheduler: {cls_path}")
            else:
                logger.info(f"Scheduler {cls_path} is disabled, skipping.")
        except Exception as e:
            logger.error(f"Failed to initialize scheduler {cls_path}: {e}")
    return schedulers


class Scheduler(BaseScheduler):
    interval: float | int | timedelta = timedelta(seconds=1)

    def __init__(self, model=None):
        super(Scheduler, self).__init__(model=model)
        self._is_shutdown = Event()
        self._is_stopped = Event()
        self.schedulers: list[BaseScheduler] = []

    def schedule(self, now):
        intervals = []
        for scheduler in self.schedulers:
            log, interval = scheduler.tick()
            intervals.append(interval)
        if intervals:
            sleep_time = min(intervals)
            time.sleep(sleep_time)

    def _schedule(self, now) -> models.SchedulerLog:
        log = super()._schedule(now)
        self.model.last_tick_time = timezone.now()
        self.model.save(update_fields=["last_tick_time"])
        return log

    def start(self, embedded_process=False):
        kwargs = getattr(settings, "DJANGO_SCHED", {})
        self.update_kwargs(**kwargs)
        if not self.enabled:
            logger.warning("❌ Scheduler is disabled in settings, exiting.")
            return None
        self.schedulers = load_schedulers()
        if not self.schedulers:
            logger.warning("❌ no schedulers loaded, exiting.")
            return None
        scheduler_model = acquirer_scheduler(name=self.name, max_interval=min([x.interval for x in self.schedulers]))
        if not scheduler_model:
            logger.warning("❌ another scheduler is already running, giving up.")
            return None
        logger.info(f"✅ lock acquired, scheduler started as {scheduler_model.owner}")
        self.model = scheduler_model
        if embedded_process:
            signals.scheduler_embedded_init.send(sender=self)
        try:
            while not self._is_shutdown.is_set():
                log, interval = self.tick()
                logger.debug(f"{self.name} tick: schedule -> {log.success if log else '-'}, sleep {interval}s")
                time.sleep(interval)
        except (KeyboardInterrupt, SystemExit):
            self._is_shutdown.set()
        finally:
            scheduler_model.locked = False
            scheduler_model.save(update_fields=["locked"])

    def stop(self, wait=False):
        logger.info('beat: Shutting down...')
        self._is_shutdown.set()
        wait and self._is_stopped.wait()  # block until shutdown done.


class _Threaded(Thread):
    """Embedded task scheduler using threading."""

    def __init__(self, **kwargs):
        super().__init__()
        self.scheduler = Scheduler(**kwargs)
        self.daemon = True
        self.name = 'Scheduler'

    def run(self):
        self.scheduler.start()

    def stop(self):
        self.scheduler.stop(wait=True)


try:
    ensure_multiprocessing()
except NotImplementedError:     # pragma: no cover
    _Process = None
else:
    class _Process(Process):

        def __init__(self, **kwargs):
            super().__init__()
            self.scheduler = Scheduler(**kwargs)
            self.name = 'Scheduler'

        def run(self):
            self.scheduler.start(embedded_process=True)

        def stop(self):
            self.scheduler.stop()
            self.terminate()


def acquirer_scheduler(name, max_interval=10) -> models.Scheduler | None:
    now = timezone.now()
    try:
        with transaction.atomic():
            # 尝试创建新锁
            return models.Scheduler.objects.create(name=name, locked=True, locked_time=now)
    except IntegrityError:
        # 已经有锁，看看是否过期
        try:
            # 获得操作锁，防止并发
            lock = models.Scheduler.objects.create(name="__lock__", locked=True, locked_time=now)
        except IntegrityError:
            updated = models.Scheduler.objects.filter(name="__lock__", locked_time__lt=now - timedelta(seconds=max_interval)).update(locked_time=now)
            if updated:
                lock = models.Scheduler.objects.get(name="__lock__")
            else:
                logger.info("lock is held by another acquirer, giving up.")
                return None
        try:
            scheduler = models.Scheduler.objects.get(name=name)
            scheduler.interval = max_interval
            if scheduler.is_lock_expired:
                # holder 死了 → 接管
                scheduler.owner = models.OWNER
                scheduler.locked = True
                scheduler.locked_time = now
                scheduler.save(update_fields=["locked", "locked_time", "owner"])
                logger.info(f"process<{scheduler.owner}> seems dead, scheduler lock acquired.")
                return scheduler
            else:
                last_heartbeat= scheduler.heartbeat
                expire_time = scheduler.lock_expire_time

                latest_scheduler = None
                while (now := timezone.now()) < expire_time:
                    # 这里要给操作锁续期
                    lock.locked_time = now
                    lock.save(update_fields=["locked_time"])
                    time.sleep(1)
                    # 等待 holder 心跳更新
                    logger.info(f"holder<{scheduler.owner}> is alive, waiting for it to finish, expire at {expire_time}.")
                    latest_scheduler = models.Scheduler.objects.get(pk=scheduler.pk)
                    if latest_scheduler.heartbeat != last_heartbeat:
                        # holder 还活着 → 放弃接管
                        logger.info(f"holder<{latest_scheduler.owner}> is still alive, giving up.")
                        break
                else:
                    # holder 死了 → 接管
                    latest_scheduler.owner = models.OWNER
                    latest_scheduler.locked = True
                    latest_scheduler.locked_time = timezone.now()
                    latest_scheduler.save(update_fields=["locked", "locked_time", "owner"])
                    logger.info(f"holder<{latest_scheduler.owner}> seems dead, scheduler lock acquired.")
                    return latest_scheduler
        finally:
            if lock:
                lock.delete()


def EmbeddedScheduler(thread=False, **kwargs):
    """Return embedded clock service.
    Arguments:
        thread (bool): Run threaded instead of as a separate process.
            Uses :mod:`multiprocessing` by default, if available.
    """
    if thread or _Process is None:
        # Need short max interval to be able to stop thread
        # in reasonable time.
        return _Threaded(**kwargs)
    return _Process(**kwargs)


def start_scheduler(embedded_process=False, thread=False, **kwargs):
    """Start the scheduler as a separate process or embedded thread.

    Arguments:
        embedded_process (bool): Run the scheduler in the current process.
            This will block the current process.
        thread (bool): Run the scheduler as an embedded thread instead of
            a separate process. Uses :mod:`multiprocessing` by default,
            if available.
    """
    if embedded_process:
        scheduler = Scheduler(**kwargs)
        scheduler.start(embedded_process=True)
    else:
        scheduler = EmbeddedScheduler(thread=thread, **kwargs)
        scheduler.start()
    return scheduler