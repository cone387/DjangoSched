from django.db import models
from django.utils import timezone
from datetime import timedelta
import os
import socket
import uuid


def default_owner():
    """
    默认 owner: PID + hostname + 6位随机 UUID
    示例: 12345@node01:1a2b3c
    """
    pid = os.getpid()
    host = socket.gethostname()
    short_uuid = uuid.uuid4().hex[:6]
    return f"{pid}@{host}:{short_uuid}"


OWNER = default_owner()


class Scheduler(models.Model):
    name = models.CharField(max_length=200, unique=True, verbose_name="名称")
    interval = models.IntegerField(default=1, verbose_name="运行间隔(秒)")
    locked = models.BooleanField(default=False, verbose_name="是否被锁")
    owner = models.CharField(max_length=200, default=OWNER, verbose_name="锁持有者")
    locked_time = models.DateTimeField(null=True, blank=True, verbose_name="上锁时间")
    last_tick_time = models.DateTimeField(null=True, blank=True, verbose_name="上次tick时间")
    last_tick_success = models.BooleanField(default=True, verbose_name="上次调度是否成功")
    create_time = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    @property
    def heartbeat(self):
        return self.last_tick_time or self.locked_time

    @property
    def lock_expire_time(self):
        delta = timedelta(seconds=max(10, self.interval * 2))
        expired_time = timezone.now() - delta
        heartbeat = max([self.locked_time or expired_time, self.last_tick_time or expired_time])
        return heartbeat + delta

    @property
    def is_lock_expired(self):
        return not self.locked or self.lock_expire_time < timezone.now()

    class Meta:
        db_table = "django_sched_scheduler"
        verbose_name = verbose_name_plural = "调度器"

    def __str__(self):
        return f"{self.name} ({self.interval}s) {'🔓' if self.is_lock_expired else '🔐'}"


class SchedulerLog(models.Model):
    scheduler = models.CharField(max_length=100, verbose_name="调度")
    owner = models.CharField(max_length=200, verbose_name="执行者")
    success = models.BooleanField(default=True, verbose_name="是否成功")
    started_at = models.DateTimeField(default=timezone.now, verbose_name="开始时间")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="结束时间")
    message = models.TextField(blank=True, verbose_name="日志/异常信息")
    duration = models.FloatField(null=True, blank=True, verbose_name="耗时(秒)")
    create_time = models.DateTimeField(default=timezone.now, verbose_name="创建时间")

    class Meta:
        db_table = "django_sched_log"
        verbose_name = verbose_name_plural = "调度日志"
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.scheduler} @ {self.started_at:%Y-%m-%d %H:%M}"
