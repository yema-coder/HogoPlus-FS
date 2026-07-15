from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery = Celery(
    "hogo",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks"],
)
celery.conf.timezone = "UTC"
celery.conf.beat_schedule = {
    "escalation-sweep-every-30-min": {
        "task": "app.tasks.escalation_sweep",
        "schedule": crontab(minute="*/30"),
    },
    # every 4 hours at 00:30/04:30/08:30/12:30/16:30/20:30 IST (UTC = IST-5:30)
    "backup-every-4h": {
        "task": "app.tasks.nightly_backup",
        "schedule": crontab(hour="3,7,11,15,19,23", minute=0),
    },
    # 06:00 IST == 00:30 UTC
    "nightly-factory-report": {
        "task": "app.tasks.nightly_report",
        "schedule": crontab(hour=0, minute=30),
    },
}
