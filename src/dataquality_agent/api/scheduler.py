"""APScheduler 定时调度：无人值守定时巡检。"""
from apscheduler.schedulers.background import BackgroundScheduler


def create_scheduler(runtime, interval_minutes: int = 60) -> BackgroundScheduler:
    """创建后台调度器，每 interval_minutes 触发一次巡检（高危进审批队列，低危/报告自动完成）。"""
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(runtime.trigger, "interval", minutes=interval_minutes, id="patrol")
    return scheduler
