"""`tgguard` CLI (Typer). Runs locally with the service account session."""

from __future__ import annotations

import asyncio
import csv
import html
import sys
from pathlib import Path
from time import perf_counter

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

from core import strings
from core.config import get_scoring_config, get_settings
from core.db.session import Database
from core.logging import setup_logging
from core.nsfw import get_classifier
from scanner.client import build_client
from scanner.service import ScannerService, Targets


def _force_utf8_output() -> None:
    """Windows consoles default to a legacy code page, and spam profiles are
    full of emoji: printing one must never crash the CLI."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):  # pragma: no cover - platform dependent
            pass


_force_utf8_output()

app = typer.Typer(add_completion=False, help="TG-Guard skaner (Telethon, service account)")
console = Console()


def format_duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} soat {minutes} daq"
    if minutes:
        return f"{minutes} daq {secs} son"
    return f"{secs} son"


def build_scan_summary(stats, *, title: str, seconds: float) -> str:
    """The Telegram message sent to the admins when a scan finishes."""
    data = stats.as_dict()
    flagged = data["spam"] + data["review"]
    next_step = strings.SCAN_NEXT_STEP_SPAM if flagged else strings.SCAN_NEXT_STEP_CLEAN
    if data["capped"]:
        next_step += strings.SCAN_CAPPED
    return strings.SCAN_SUMMARY.format(
        title=html.escape(title),
        seen=data["seen"],
        analyzed=data["analyzed"],
        cached=data["cached"],
        spam=data["spam"],
        review=data["review"],
        clean=data["clean"],
        photoless=data["photoless"],
        errors=data["errors"],
        duration=format_duration(seconds),
        next_step=next_step,
    )


def _resolve_channel(channel: str | None) -> str | int:
    settings = get_settings()
    if channel:
        return int(channel) if channel.lstrip("-").isdigit() else channel
    if settings.channel_id:
        return settings.channel_id
    raise typer.BadParameter("--channel bering yoki .env dagi CHANNEL_ID ni to'ldiring")


class _Context:
    """Builds every dependency once and cleans them up afterwards."""

    def __init__(self, *, need_bot: bool = True, need_client: bool = True) -> None:
        self.settings = get_settings()
        self.cfg = get_scoring_config()
        self.db = Database(self.settings.database_url)
        # DB-only commands (list/report) must work without Telegram credentials.
        self.client = build_client(self.settings) if need_client else None
        self.classifier = get_classifier(self.cfg.nsfw)
        self.bot = None
        self.need_bot = need_bot

    async def __aenter__(self) -> ScannerService:
        if self.client is not None:
            await self.client.start()
        # A bot token alone is enough: even without a review channel the
        # scanner can send its summary to the admins' private chats.
        if self.need_bot and self.settings.bot_token:
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
        if self.client is not None:
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
def chats(
    query: str | None = typer.Argument(None, help="Nom bo'yicha filtr (ixtiyoriy)"),
) -> None:
    """Akkaunt a'zo bo'lgan kanal/guruhlar va ularning `.env` uchun id lari."""

    async def _run() -> None:
        async with _Context(need_bot=False) as service:
            rows = await service.list_chats(query=query)
            if not rows:
                console.print("[yellow]Hech narsa topilmadi.[/]")
                return
            table = Table(title="Kanal va guruhlar")
            table.add_column("ID (.env uchun)", no_wrap=True)
            table.add_column("Turi", no_wrap=True)
            table.add_column("Nomi")
            table.add_column("Username")
            table.add_column("A'zolar", justify="right")
            table.add_column("Admin?", no_wrap=True)
            for row in rows:
                table.add_row(
                    str(row["id"]),
                    row["kind"],
                    (row["title"] or "-")[:32],
                    f"@{row['username']}" if row["username"] else "-",
                    str(row["members"]) if row["members"] else "-",
                    "ha" if row["admin"] else "yo'q",
                )
            console.print(table)
            console.print(
                "Kanal -> [bold]CHANNEL_ID[/], muhokama guruhi -> "
                "[bold]DISCUSSION_GROUP_ID[/], yopiq review kanal -> "
                "[bold]REVIEW_CHANNEL_ID[/]"
            )

    asyncio.run(_run())


@app.command()
def scan(
    channel: str | None = typer.Option(None, "--channel", "-c", help="Kanal id yoki @username"),
    limit: int | None = typer.Option(None, help="Faqat N ta foydalanuvchini tekshirish"),
    force: bool = typer.Option(
        False, "--force", help="Keshni e'tiborsiz qoldirib qayta tekshirish"
    ),
    no_review: bool = typer.Option(False, "--no-review", help="Review kanalga yubormaslik"),
    no_notify: bool = typer.Option(
        False, "--no-notify", help="Yakuniy xulosani Telegram'ga yubormaslik"
    ),
    delay: float = typer.Option(0.35, help="Profil so'rovlari orasidagi pauza (soniya)"),
    save_photos: Path | None = typer.Option(
        None,
        "--save-photos",
        help="Profil rasmlarini shu papkaga saqlash (kalibrlash uchun; sukut: saqlanmaydi)",
    ),
) -> None:
    """Kanal va muhokama guruhi a'zolarini to'liq tekshirish (uzilsa — davom etadi)."""
    target = _resolve_channel(channel)
    started = perf_counter()
    title = {"value": str(target)}

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
                    title["value"] = targets.channel_title
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
                    save_photos=save_photos,
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

            if not no_notify:
                summary = build_scan_summary(
                    stats, title=title["value"], seconds=perf_counter() - started
                )
                sent = await service.notify_admins(summary)
                if sent:
                    console.print(f"[green]Xulosa Telegram'ga yuborildi ({sent} ta admin).[/]")

    asyncio.run(_run())


# CLI verdict aliases -> the verdict stored on a check row.
VERDICT_ALIASES = {
    "spam": "ban",
    "ban": "ban",
    "review": "review",
    "shubhali": "review",
    "ignore": "ignore",
    "toza": "ignore",
    "all": None,
    "hammasi": None,
}


@app.command("list")
def list_users(
    verdict: str = typer.Option(
        "spam", "--verdict", "-v", help="spam | review | toza | all"
    ),
    limit: int = typer.Option(50, "--limit", "-n", help="Nechta qator ko'rsatilsin"),
    min_score: float | None = typer.Option(None, "--min-score", help="Shu balldan yuqorilar"),
    undecided: bool = typer.Option(
        False, "--undecided", help="Faqat siz hali qaror qilmaganlar"
    ),
    channel: str | None = typer.Option(None, "--channel", "-c", help="Faqat shu kanal bo'yicha"),
    csv_path: Path | None = typer.Option(None, "--csv", help="Natijani CSV faylga yozish"),
) -> None:
    """Belgilangan profillar ro'yxati: havola, ball va sabab bilan (bazadan)."""
    key = verdict.strip().lower()
    if key not in VERDICT_ALIASES:
        raise typer.BadParameter("verdict: spam | review | toza | all")
    channel_id: int | None = None
    if channel:
        resolved = _resolve_channel(channel)
        if not isinstance(resolved, int):
            raise typer.BadParameter("--channel bu buyruqda raqamli id bo'lishi kerak")
        channel_id = resolved

    async def _run() -> None:
        async with _Context(need_bot=False, need_client=False) as service:
            rows = await service.list_users(
                verdict=VERDICT_ALIASES[key],
                min_score=min_score,
                channel_id=channel_id,
                undecided_only=undecided,
                limit=limit,
            )
            if not rows:
                console.print(
                    "[yellow]Hech narsa topilmadi. Avval `tgguard scan` ni ishga tushiring.[/]"
                )
                return

            table = Table(title=f"Profillar ({key}, {len(rows)} ta)")
            table.add_column("ID", style="dim", no_wrap=True)
            table.add_column("Ism", max_width=18, overflow="ellipsis")
            # The link must stay complete so it can be copied out of the terminal.
            table.add_column("Havola", overflow="fold", min_width=24)
            table.add_column("Ball", justify="right", no_wrap=True)
            table.add_column("Holat", no_wrap=True)
            table.add_column("Qaror", no_wrap=True)
            table.add_column("Sabab", max_width=30, overflow="ellipsis")
            for row in rows:
                table.add_row(
                    str(row["user_id"]),
                    (row["name"] or "-")[:24],
                    row["profile_url"],
                    f"{row['score']:.2f}",
                    row["verdict"],
                    row["decision"] or "-",
                    ", ".join(row["reasons"])[:60],
                )
            console.print(table)
            console.print(
                "Ban qilish uchun: [bold]tgguard apply --dry-run[/] → "
                "[bold]tgguard apply --execute[/]; bittasini oqlash: "
                "[bold]tgguard unban <id>[/]"
            )

            if csv_path:
                _write_csv(csv_path, rows)
                console.print(f"CSV yozildi: [bold]{csv_path}[/]")

    asyncio.run(_run())


def _write_csv(path: Path, rows: list[dict]) -> None:
    """utf-8-sig: Excel CSV ni kirill/lotin harflari bilan to'g'ri ochsin."""
    fields = [
        "user_id",
        "name",
        "username",
        "profile_url",
        "score",
        "verdict",
        "decision",
        "decision_source",
        "has_photo",
        "checked_at",
        "reasons",
        "bio",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "reasons": "; ".join(row["reasons"])})


@app.command()
def report() -> None:
    """Umumiy statistika: tekshirilgan / spam / review / haqiqiy / rasmsiz."""

    async def _run() -> None:
        async with _Context(need_bot=False, need_client=False) as service:
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
