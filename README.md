# DjangoSched

轻量级的 Django 定时任务调度框架。基于 Django ORM 与线程/进程实现，支持：
- 周期任务调度、任务运行日志（`SchedulerLog`）和锁竞争机制；
- 嵌入式线程或独立进程运行调度器；
- 与 Django Admin 集成查看调度器与运行日志。

核心实现与入口
- 调度器实现：[`django_sched.sched.Scheduler`](django_sched/sched.py)
- 启动入口：[`django_sched.sched.start_scheduler`](django_sched/sched.py)
- 应用自动启动：[`django_sched.apps.DjangoSchedConfig.ready`](django_sched/apps.py)（在 `runserver` 或 `gunicorn` 下自动启动）
- 模型：[`django_sched.models.Scheduler`](django_sched/models.py)、[`django_sched.models.SchedulerLog`](django_sched/models.py)
- 管理后台：[`django_sched.admin.SchedulerAdmin`](django_sched/admin.py)
- 信号：[`django_sched.signals.scheduler_init`](django_sched/signals.py)

快速开始
1. 安装（在虚拟环境中）：
```sh
pip install -e .
```

2. 在 Django 项目里加入 `django_sched` 到 `INSTALLED_APPS`（示例项目在 `demo` 中）：
```py
INSTALLED_APPS = [
    # ...
    'django_sched',
]
```

3. 迁移并启动：
```sh
python manage.py migrate
python manage.py runserver
```
在 `runserver` 或 `gunicorn` 下，应用会通过 `DjangoSchedConfig.ready()` 自动尝试启动调度器（可在日志中看到启动/竞态信息）。详情见 [`django_sched.apps.DjangoSchedConfig.ready`](django_sched/apps.py)。

以编程方式启动（例如在管理命令中）：
```py
from django_sched.sched import start_scheduler
# 在当前进程中以嵌入方式启动（会阻塞）
start_scheduler(embedded_process=True)
# 或作为线程/进程嵌入
start_scheduler(thread=True)
```

注意事项
- 锁机制基于数据库表 `django_sched_scheduler`，当检测到上次持有进程心跳过期时会尝试接管锁；
- 默认 timezone 配置会影响锁过期与日志时间，请根据项目配置调整；
- Admin 页面禁止手动新增/修改/删除日志。

贡献与授权
- 许可：MIT（见 LICENSE）
- 欢迎提 issue / PR