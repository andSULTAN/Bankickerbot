"""`tgguard` CLI (Typer). Runs locally with the service account session."""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from core.config import get_scoring_config, get_settings
from core.db.session import Database
from core.logging import setup_logging
from core.nsfw import get_classifier
from scanner.client import build_client
from scanner.service import ScannerService, Targets

app = typer.Typer(add_completion=False, help="TG-Guard skaner (Telethon, service account)")
console = Console()


def _resolve_channel(channel: str | None) -> str | int:
    settings = get_settings()
    if channel:
        return int(channel) if channel.lstrip("-").isdigit() else channel
    if settings.channel_id:
        return settings.channel_id
    raise typer.BadParameter("--channel bering yoki .env dagi CHANNEL_ID ni to'ldiring")


class _Context:
    """Builds every dependency once and cleans them up afterwards."""

    def __init__(self, *, need_bot: bool = True) -> None:
        self.settings = get_settings()
        self.cfg = get_scoring_config()
        self.db = Database(self.settings.database_url)
        self.client = build_client(self.settings)
        self.classifier = get_classifier(self.cfg.nsfw)
        self.bot = None
        self.need_bot = need_bot

    async def __aenter__(self) -> ScannerService:
        await self.client.start()
        if self.need_bot and self.settings.bot_token and self.settings.review_channel_id:
            from aiogram import Bot

            self.bot = Bot(self.settings.bot_token)
        return ScannerService(
            settings=self.settings,
            cfg=self.cfg,
            db=self.db,
            client=self.client,
            classifier=self.classifier,
            bot=self.bot,
        )

    async def __aexit__(self, *exc) -> None:
        if self.bot is not None:
            await self.bot.session.close()
        await self.client.disconnect()
        await self.db.dispose()


@app.callback()
def main(log_level: str = typer.Option("INFO", help="Log darajasi")) -> None:
    setup_logging(log_level, pretty=True)


@app.command()
def whoami() -> None:
    """Sessiya qaysi akkauntga tegishli ekanini ko'rsatadi."""

    async def _run() -> None:
        async with _Context(need_bot=False) as service:
            console.print(f"[bold green]{await service.whoami()}[/]")

    asyncio.run(_run())


@app.command()
def scan(
    channel: str | None = typer.Option(None, "--channel", "-c", help="Kanal id yoki @username"),
    limit: int | None = typer.Option(None, help="Faqat N ta foydalanuvchini tekshirish"),
    force: bool = typer.Option(
        False, "--force", help="Keshni e'tiborsiz qoldirib qayta tekshirish"
    ),
    no_review: bool = typer.Option(False, "--no-review", help="Review kanalga yubormaslik"),
    delay: float = typer.Option(0.35, help="Profil so'rovlari orasidagi pauza (soniya)"),
) -> None:
    """Kanal va muhokama guruhi a'zolarini to'liq tekshirish (uzilsa — davom etadi)."""
    target = _resolve_channel(channel)

    async def _run() -> None:
        async with _Context() as service:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Tekshirilmoqda", total=limit or 1)

                def _on_start(targets: Targets) -> None:
                    total = limit or targets.expected_total or 1
                    progress.update(
                        task,
                        total=total,
                        description=f"{targets.channel_title}",
                    )
                    console.print(
                        f"Kanal: [bold]{targets.channel_title}[/] "
                        f"({targets.channel_members} a'zo), "
                        f"guruh: {targets.group_id or 'yo`q'} ({targets.group_members} a'zo)"
                    )

                def _progress(stats, phase: str) -> None:
                    progress.update(
                        task,
                        completed=stats.seen,
                        description=f"{phase}: spam {stats.spam} / review {stats.review}",
                    )

                stats = await service.scan(
                    target,
                    limit=limit,
                    force=force,
                    push_review=not no_review,
                    profile_delay=delay,
                    progress_cb=_progress,
                    on_start=_on_start,
                )

            table = Table(title="Skan natijasi")
            table.add_column("Ko'rsatkich")
            table.add_column("Qiymat", justify="right")
            for key, value in stats.as_dict().items():
                table.add_row(key, str(value))
            console.print(table)
            if stats.capped:
                console.print(
                    "[yellow]⚠️ Kanal 10 000 dan katta: qidiruv orqali to'ldirildi, "
                    "ro'yxat 100% to'liq bo'lmasligi mumkin. Skanni takrorlab turing.[/]"
                )

    asyncio.run(_run())


@app.command()
def report() -> None:
    """Umumiy statistika: tekshirilgan / spam / review / haqiqiy / rasmsiz."""

    async def _run() -> None:
        async with _Context(need_bot=False) as service:
            data = await service.report()
            table = Table(title="TG-Guard hisobot")
            table.add_column("Ko'rsatkich")
            table.add_column("Qiymat", justify="right")
            table.add_row("Foydalanuvchilar", str(data["users"]))
            table.add_row("Rasmsiz", str(data["photoless"]))
            for verdict, count in sorted(data["checks_by_verdict"].items()):
                table.add_row(f"Tekshiruv: {verdict}", str(count))
            for verdict, count in sorted(data["decisions"].items()):
                table.add_row(f"Qaror: {verdict}", str(count))
            for action, count in sorted(data["actions"].items()):
                table.add_row(f"Amal: {action}", str(count))
            table.add_row("Kutayotgan review", str(data["pending_reviews"]))
            console.print(table)

            reasons = Table(title="Eng ko'p uchragan sabablar")
            reasons.add_column("Signal")
            reasons.add_column("Soni", justify="right")
            for name, count in data["top_reasons"]:
                reasons.add_row(name, str(count))
            console.print(reasons)

    asyncio.run(_run())


@app.command()
def apply(
    channel: str | None = typer.Option(None, "--channel", "-c"),
    execute: bool = typer.Option(
        False, "--execute", help="Haqiqatan ban qilish (sukut bo'yicha --dry-run)"
    ),
) -> None:
    """Oxirgi qarori `spam` bo'lganlarni kanal va guruhdan ban qiladi."""
    target = _resolve_channel(channel)

    async def _run() -> None:
        async with _Context(need_bot=False) as service:
            if execute:
                async with service.db.session() as session:
                    from core.db.repo import Repository

                    count = len(await Repository(session).spam_user_ids())
                console.print(
                    f"[bold red]{count}[/] ta foydalanuvchi ban qilinadi "
                    f"(kanal + guruh). Bu amal qaytarilishi mumkin: `tgguard unban <id>`."
                )
                answer = typer.prompt("Davom etish uchun 'yes' deb yozing")
                if answer.strip().lower() != "yes":
                    console.print("Bekor qilindi.")
                    return

            with Progress(console=console) as progress:
                task = progress.add_task("Ban", total=1)

                def _progress(index: int, total: int, banned: int) -> None:
                    progress.update(task, total=max(total, 1), completed=index)

                result = await service.apply(target, execute=execute, progress_cb=_progress)

            mode = "EXECUTE" if result["executed"] else "DRY-RUN"
            console.print(
                f"[bold]{mode}[/]: jami {result['total']}, "
                f"ban {result['banned']}, xato {result['failed']}"
            )

    asyncio.run(_run())


@app.command()
def unban(
    user_id: int = typer.Argument(..., help="Telegram user id"),
    channel: str | None = typer.Option(None, "--channel", "-c"),
) -> None:
    """Xavfsizlik klapani: banni bekor qiladi va oq ro'yxatga qo'shadi."""
    target = _resolve_channel(channel)

    async def _run() -> None:
        async with _Context(need_bot=False) as service:
            result = await service.unban(target, user_id)
            if result["ok"]:
                console.print(f"[green]{user_id} banni bekor qilindi va oq ro'yxatga qo'shildi.[/]")
            else:
                console.print(f"[red]Xatolik: {result['error']}[/]")

    asyncio.run(_run())


if __name__ == "__main__":
    app()
