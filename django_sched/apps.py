from django.apps import AppConfig
from django.db.backends.signals import connection_created
import logging
import sys


class DjangoSchedConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'django_sched'
    _scheduler_started = False

    def ready(self):
        logger = logging.getLogger(self.name)
        if not logger.handlers:  # 避免重复添加
            handler = logging.StreamHandler()
            formatter = logging.Formatter("[%(levelname)s] %(asctime)s %(name)s %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

        if "runserver" not in sys.argv and "gunicorn" not in sys.argv:
            return

        if self._scheduler_started:
            return

        def launch_scheduler(sender, connection, **kwargs):
            connection_created.disconnect(
                launch_scheduler, dispatch_uid="start-scheduler"
            )
            from .sched import start_scheduler
            start_scheduler()

        connection_created.connect(launch_scheduler, dispatch_uid="start-scheduler")
        self._scheduler_started = True
