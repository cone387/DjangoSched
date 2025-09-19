from django.contrib import admin
from .models import Scheduler, SchedulerLog


@admin.register(Scheduler)
class SchedulerAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "interval",
        "locked_time",
        "lock_expire_time",
        "locked",
        "last_tick_time",
        "owner",
        "update_time",
    )
    list_filter = ("interval", "create_time", "update_time")
    search_fields = ("name",)
    readonly_fields = ("name", "owner", "locked", "locked_time", "last_tick_time", "is_lock_expired", "lock_expire_time", "create_time", "update_time")
    ordering = ("-update_time",)

    fields = (
        "name",
        "interval",
        "locked",
        "is_lock_expired",
        "owner",
        "locked_time",
        "lock_expire_time",
        "last_tick_time",
        "create_time",
        "update_time",
    )

    def lock_expire_time(self, obj: Scheduler):
        return obj.lock_expire_time
    lock_expire_time.short_description = "锁过期时间"


@admin.register(SchedulerLog)
class SchedulerLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "scheduler",
        "success",
        "started_at",
        "finished_at",
        "duration",
        "owner",
        "create_time",
    )
    list_filter = ("success", "started_at", "finished_at")
    search_fields = ("scheduler", "message")
    readonly_fields = [f.name for f in SchedulerLog._meta.fields]

    def has_add_permission(self, request):
        return False  # 禁止手动新增

    def has_change_permission(self, request, obj=None):
        return False  # 禁止修改

    def has_delete_permission(self, request, obj=None):
        return False  # 禁止删除
