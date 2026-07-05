"""Sylqon Discord bot — slash commands + proactive post-game advice.

Phase 1 gateway (discord.py edition of the roadmap's discord-gw):
  /link, /utolsomeccs, /riport, /build, /matchup, /beallitas
plus the match watcher running inside the bot process, delivering advice
embeds with 👍/👎 feedback buttons. When no guild has an advice channel
configured, delivery falls back to the plain webhook notifier.

The bot is a thin async shell — all real work lives in the sync modules
(crawler/pipeline/report/builds) and runs via asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import builds, config, db, report, store
from app.advice.pipeline import AdviceNotPossible, get_or_generate_advice
from app.crawler import IngestService
from app.models import AdviceFeedback, GuildConfig, LinkedAccount, Match, MatchParticipant
from app.notifier import DiscordWebhookNotifier, build_embed
from app.ratelimit import build_rate_limiter
from app.riot_client import RiotClient
from app.watcher import MatchWatcher

log = logging.getLogger(__name__)

_T = {
    "hu": {
        "not_linked": "Előbb kösd össze a fiókod: `/link Név#TAG`",
        "bad_riot_id": "A Riot ID formátuma: `Név#TAG`",
        "unknown_riot_id": "Nem találom ezt a Riot ID-t: `{riot_id}`",
        "linked": "✅ Összekötve: **{riot_id}** — mostantól figyelem a meccseidet. "
                  "A meglévő meccstörténetet a háttérben töltöm be.",
        "no_recent": "Nincs tárolt meccsed még — játssz egyet, vagy próbáld pár perc múlva.",
        "no_build_data": "Még nincs elég saját adat **{champion}** buildjéhez (min. {n} meccs kell). "
                         "Ahogy nő az adatbázis, ez magától élesedik.",
        "no_matchup_data": "Még nincs elég lane-találkozás **{a} vs {b}** párosból (min. {n}).",
        "config_saved": "✅ Beállítva. Tanács-csatorna: {channel}, nyelv: {lang}.",
        "config_denied": "Ehhez `Szerver kezelése` jogosultság kell.",
        "vote_thanks": "Köszi a visszajelzést! 🙏",
        "vote_dupe": "Erre a tanácsra már szavaztál.",
        "build_title": "{champion} — saját meta ({games} meccs, {winrate_pct}% WR, {role})",
        "matchup_line": "**{a} vs {b}** (azonos lane): {games} meccs, {a} nyert {a_wins}-szer "
                        "(**{pct}%**) — saját adatból, nem globális statisztika.",
    },
    "en": {
        "not_linked": "Link your account first: `/link Name#TAG`",
        "bad_riot_id": "Riot ID format: `Name#TAG`",
        "unknown_riot_id": "Can't find this Riot ID: `{riot_id}`",
        "linked": "✅ Linked: **{riot_id}** — I'm watching your matches from now on. "
                  "Backfilling your recent history in the background.",
        "no_recent": "No stored matches yet — play one, or try again in a few minutes.",
        "no_build_data": "Not enough own data for **{champion}** yet (needs {n}+ games). "
                         "This sharpens automatically as the dataset grows.",
        "no_matchup_data": "Not enough lane meetings for **{a} vs {b}** yet (needs {n}+).",
        "config_saved": "✅ Saved. Advice channel: {channel}, language: {lang}.",
        "config_denied": "You need the `Manage Server` permission for this.",
        "vote_thanks": "Thanks for the feedback! 🙏",
        "vote_dupe": "You already voted on this advice.",
        "build_title": "{champion} — own meta ({games} games, {winrate_pct}% WR, {role})",
        "matchup_line": "**{a} vs {b}** (same lane): {games} games, {a} won {a_wins} "
                        "(**{pct}%**) — own data, not a global stat.",
    },
}


def _feedback_view(match_id: str, puuid: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(emoji="👍", style=discord.ButtonStyle.secondary,
                                    custom_id=f"fb:1:{match_id}:{puuid}"))
    view.add_item(discord.ui.Button(emoji="👎", style=discord.ButtonStyle.secondary,
                                    custom_id=f"fb:-1:{match_id}:{puuid}"))
    return view


class SylqonBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        engine = db.init_db()
        self.session_factory = db.get_session_factory(engine)
        self.riot = RiotClient(rate_limiter=build_rate_limiter())
        self.ingest = IngestService(self.riot, self.session_factory)
        self.webhook_notifier = DiscordWebhookNotifier()
        self.watcher = MatchWatcher(
            self.ingest, self.session_factory, _BotDelivery(self), lang=config.WATCH_LANG
        )
        self._synced = False
        register_commands(self)

    # -- lifecycle ---------------------------------------------------------

    async def on_ready(self) -> None:
        log.info("logged in as %s (%d guild(s))", self.user, len(self.guilds))
        if not self._synced:
            self._synced = True
            for guild in self.guilds:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)  # instant per-guild availability
            await self.tree.sync()
            log.info("slash commands synced")
            self._watch_task = asyncio.create_task(self._watch_loop())

    async def on_guild_join(self, guild: discord.Guild) -> None:
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        log.info("joined guild %s — commands synced", guild.name)

    async def _watch_loop(self) -> None:
        await asyncio.sleep(5)
        while not self.is_closed():
            try:
                delivered = await asyncio.to_thread(self.watcher.run_once)
                if delivered:
                    log.info("watcher delivered %d advice message(s)", delivered)
            except Exception:
                log.exception("watcher cycle failed")
            await asyncio.sleep(config.WATCH_POLL_SECONDS)

    # -- delivery targets ----------------------------------------------------

    def advice_channels(self) -> list[tuple[discord.abc.Messageable, str]]:
        out = []
        with self.session_factory() as session:
            for cfg in session.execute(select(GuildConfig)).scalars():
                if not cfg.advice_channel_id:
                    continue
                channel = self.get_channel(cfg.advice_channel_id)
                if channel is not None:
                    out.append((channel, cfg.lang or "hu"))
        return out

    # -- feedback buttons -----------------------------------------------------

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = (interaction.data or {}).get("custom_id", "")
        if not custom_id.startswith("fb:"):
            return
        _, vote, match_id, puuid = custom_id.split(":", 3)
        lang = _guild_lang(self, interaction)
        try:
            with self.session_factory() as session:
                session.add(
                    AdviceFeedback(
                        match_id=match_id,
                        puuid=puuid,
                        discord_user_id=interaction.user.id,
                        vote=int(vote),
                    )
                )
                session.commit()
            msg = _T[lang]["vote_thanks"]
        except IntegrityError:
            msg = _T[lang]["vote_dupe"]
        await interaction.response.send_message(msg, ephemeral=True)


class _BotDelivery:
    """Notifier-interface adapter: watcher (worker thread) → bot event loop.
    Posts to every configured guild channel with feedback buttons; falls back
    to the webhook when no channel is configured or the bot isn't ready."""

    def __init__(self, bot: SylqonBot) -> None:
        self._bot = bot

    def send(self, advice: dict, participant, lang: str | None = None) -> bool:
        if self._bot.is_closed() or not self._bot.is_ready():
            return self._bot.webhook_notifier.send(advice, participant, lang)
        future = asyncio.run_coroutine_threadsafe(
            self._send_async(advice, participant), self._bot.loop
        )
        try:
            return future.result(timeout=30)
        except Exception:
            log.exception("bot delivery failed")
            return False

    async def _send_async(self, advice: dict, participant) -> bool:
        targets = self._bot.advice_channels()
        if not targets:
            return self._bot.webhook_notifier.send(advice, participant, None)
        mention = None
        with self._bot.session_factory() as session:
            linked = session.scalar(
                select(LinkedAccount).where(LinkedAccount.puuid == advice["puuid"])
            )
            if linked:
                mention = f"<@{linked.discord_user_id}>"
        delivered = False
        for channel, lang in targets:
            payload = build_embed(
                {**advice, "text": advice["text_hu"] if lang == "hu" else advice["text_en"]},
                participant,
                lang,
            )
            embed = discord.Embed.from_dict(payload["embeds"][0])
            try:
                await channel.send(
                    content=mention,
                    embed=embed,
                    view=_feedback_view(advice["match_id"], advice["puuid"]),
                )
                delivered = True
            except discord.DiscordException:
                log.exception("failed to post advice to %s", channel)
        return delivered


# -- command plumbing -----------------------------------------------------------


def _guild_lang(bot: SylqonBot, interaction: discord.Interaction) -> str:
    if interaction.guild_id:
        with bot.session_factory() as session:
            cfg = session.get(GuildConfig, interaction.guild_id)
            if cfg and cfg.lang in _T:
                return cfg.lang
    return config.WATCH_LANG if config.WATCH_LANG in _T else "hu"


def _linked(bot: SylqonBot, discord_user_id: int) -> LinkedAccount | None:
    with bot.session_factory() as session:
        return session.get(LinkedAccount, discord_user_id)


def register_commands(bot: SylqonBot) -> None:
    tree = bot.tree

    @tree.command(name="link", description="Riot-fiók összekötése (Név#TAG)")
    @app_commands.describe(riot_id="Riot ID, pl. Név#TAG")
    async def link(interaction: discord.Interaction, riot_id: str):
        lang = _guild_lang(bot, interaction)
        await interaction.response.defer(ephemeral=True)
        game_name, _, tag_line = riot_id.partition("#")
        if not game_name or not tag_line:
            await interaction.followup.send(_T[lang]["bad_riot_id"], ephemeral=True)
            return
        account = await asyncio.to_thread(
            bot.riot.get_account_by_riot_id, game_name.strip(), tag_line.strip()
        )
        if not account or not account.get("puuid"):
            await interaction.followup.send(
                _T[lang]["unknown_riot_id"].format(riot_id=riot_id), ephemeral=True
            )
            return

        def _save():
            with bot.session_factory() as session:
                row = session.get(LinkedAccount, interaction.user.id) or LinkedAccount(
                    discord_user_id=interaction.user.id
                )
                row.puuid = account["puuid"]
                row.game_name = account.get("gameName", game_name)
                row.tag_line = account.get("tagLine", tag_line)
                row.lang = lang
                session.merge(row)
                session.commit()

        await asyncio.to_thread(_save)
        asyncio.create_task(  # backfill without blocking the reply
            asyncio.to_thread(bot.ingest.ingest_by_puuid, account["puuid"], None)
        )
        await interaction.followup.send(
            _T[lang]["linked"].format(riot_id=f"{account.get('gameName')}#{account.get('tagLine')}"),
            ephemeral=True,
        )

    @tree.command(name="utolsomeccs", description="Az utolsó meccsed tanulsága")
    async def utolsomeccs(interaction: discord.Interaction):
        lang = _guild_lang(bot, interaction)
        linked = _linked(bot, interaction.user.id)
        if linked is None:
            await interaction.response.send_message(_T[lang]["not_linked"], ephemeral=True)
            return
        await interaction.response.defer()
        await asyncio.to_thread(bot.ingest.ingest_by_puuid, linked.puuid, 5)

        def _advise():
            with bot.session_factory() as session:
                mid = session.execute(
                    select(MatchParticipant.match_id)
                    .join(Match, Match.match_id == MatchParticipant.match_id)
                    .where(MatchParticipant.puuid == linked.puuid)
                    .order_by(Match.game_creation.desc())
                    .limit(1)
                ).scalar()
                if mid is None:
                    return None, None
                advice = get_or_generate_advice(session, mid, linked.puuid, lang=lang)
                participant = store.get_participant(session, mid, linked.puuid)
                return advice, participant

        try:
            advice, participant = await asyncio.to_thread(_advise)
        except AdviceNotPossible:
            advice = None
        if advice is None:
            await interaction.followup.send(_T[lang]["no_recent"])
            return
        payload = build_embed(advice, participant, lang)
        await interaction.followup.send(
            embed=discord.Embed.from_dict(payload["embeds"][0]),
            view=_feedback_view(advice["match_id"], advice["puuid"]),
        )

    @tree.command(name="riport", description="Heti összefoglaló a meccseidből")
    @app_commands.describe(napok="Hány napra visszamenőleg (alap: 7)")
    async def riport(interaction: discord.Interaction, napok: int = 7):
        lang = _guild_lang(bot, interaction)
        linked = _linked(bot, interaction.user.id)
        if linked is None:
            await interaction.response.send_message(_T[lang]["not_linked"], ephemeral=True)
            return
        await interaction.response.defer()

        def _build():
            with bot.session_factory() as session:
                return report.build_report(session, linked.puuid, days=max(1, min(napok, 30)))

        data = await asyncio.to_thread(_build)
        if data is None:
            await interaction.followup.send(_T[lang]["no_recent"])
            return
        payload = report.build_report_payload(data, lang)
        await interaction.followup.send(embed=discord.Embed.from_dict(payload["embeds"][0]))

    async def _champion_autocomplete(interaction: discord.Interaction, current: str):
        def _names():
            with bot.session_factory() as session:
                return builds.champion_names(session, current)[:25]

        names = await asyncio.to_thread(_names)
        return [app_commands.Choice(name=n, value=n) for n in names]

    @tree.command(name="build", description="Aktuális build a saját adatbázisból")
    @app_commands.autocomplete(champion=_champion_autocomplete)
    async def build_cmd(interaction: discord.Interaction, champion: str):
        lang = _guild_lang(bot, interaction)
        await interaction.response.defer()

        def _get():
            with bot.session_factory() as session:
                return builds.build_for_champion(session, champion)

        data = await asyncio.to_thread(_get)
        if data is None:
            await interaction.followup.send(
                _T[lang]["no_build_data"].format(champion=champion, n=builds.MIN_BUILD_GAMES)
            )
            return
        lines = [
            f"{i+1}. **{item['name']}** — {item['pct']}% ({item['games']} meccs)"
            if lang == "hu"
            else f"{i+1}. **{item['name']}** — {item['pct']}% ({item['games']} games)"
            for i, item in enumerate(data["core_items"])
        ]
        embed = discord.Embed(
            title=_T[lang]["build_title"].format(**data),
            description="\n".join(lines) or "—",
            color=0x5865F2,
        )
        await interaction.followup.send(embed=embed)

    @tree.command(name="matchup", description="Két champion lane-mérlege a saját adatbázisból")
    @app_commands.autocomplete(champ1=_champion_autocomplete, champ2=_champion_autocomplete)
    async def matchup_cmd(interaction: discord.Interaction, champ1: str, champ2: str):
        lang = _guild_lang(bot, interaction)
        await interaction.response.defer()

        def _get():
            with bot.session_factory() as session:
                return builds.matchup(session, champ1, champ2)

        data = await asyncio.to_thread(_get)
        if data is None:
            await interaction.followup.send(
                _T[lang]["no_matchup_data"].format(a=champ1, b=champ2, n=builds.MIN_MATCHUP_GAMES)
            )
            return
        await interaction.followup.send(
            _T[lang]["matchup_line"].format(
                a=data["champ_a"], b=data["champ_b"], games=data["games"],
                a_wins=data["a_wins"], pct=data["a_winrate_pct"],
            )
        )

    @tree.command(name="beallitas", description="Bot-beállítások (tanács-csatorna, nyelv)")
    @app_commands.describe(csatorna="Ide posztolja a bot a meccs utáni tanácsokat",
                           nyelv="hu vagy en")
    @app_commands.choices(nyelv=[
        app_commands.Choice(name="magyar", value="hu"),
        app_commands.Choice(name="English", value="en"),
    ])
    async def beallitas(
        interaction: discord.Interaction,
        csatorna: discord.TextChannel | None = None,
        nyelv: app_commands.Choice[str] | None = None,
    ):
        lang = _guild_lang(bot, interaction)
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(_T[lang]["config_denied"], ephemeral=True)
            return

        def _save():
            with bot.session_factory() as session:
                cfg = session.get(GuildConfig, interaction.guild_id) or GuildConfig(
                    guild_id=interaction.guild_id
                )
                if csatorna is not None:
                    cfg.advice_channel_id = csatorna.id
                if nyelv is not None:
                    cfg.lang = nyelv.value
                session.merge(cfg)
                session.commit()
                return cfg

        cfg = await asyncio.to_thread(_save)
        new_lang = cfg.lang or lang
        channel_str = f"<#{cfg.advice_channel_id}>" if cfg.advice_channel_id else "—"
        await interaction.response.send_message(
            _T[new_lang]["config_saved"].format(channel=channel_str, lang=new_lang),
            ephemeral=True,
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.DISCORD_BOT_TOKEN:
        raise SystemExit("DISCORD_BOT_TOKEN is not set")
    if not config.RIOT_API_KEY:
        raise SystemExit("RIOT_API_KEY is not set")
    SylqonBot().run(config.DISCORD_BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
