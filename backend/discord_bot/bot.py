"""Discord bot implementation with slash commands."""

import asyncio
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands

from backend.analyzers.risk_scorer import RiskScorer
from backend.config import settings
from backend.connectors.esi import ESIClient
from backend.connectors.zkill import ZKillClient
from backend.database import ReportRepository, WatchlistRepository, get_session
from backend.logging_config import get_logger

logger = get_logger(__name__)


class SentinelBot(commands.Bot):
    """EVE Sentinel Discord bot with slash commands."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix="!sentinel ",
            intents=intents,
            description="EVE Sentinel - Character Analysis Bot",
        )

        # Initialize clients
        self.esi_client = ESIClient()
        self.zkill_client = ZKillClient()
        self.risk_scorer = RiskScorer()

    async def setup_hook(self) -> None:
        """Set up the bot when it starts."""
        # Add cogs
        await self.add_cog(AnalysisCog(self))
        await self.add_cog(WatchlistCog(self))
        await self.add_cog(ReportsCog(self))

        # Sync commands to specific guilds or globally
        guild_ids = settings.get_discord_guild_ids()
        if guild_ids:
            for guild_id in guild_ids:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info(f"Synced commands to guild {guild_id}")
        else:
            await self.tree.sync()
            logger.info("Synced commands globally")

    async def on_ready(self) -> None:
        """Called when the bot is ready."""
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guilds")

        # Set presence
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="EVE Online recruitment",
            )
        )


class AnalysisCog(commands.Cog, name="Analysis"):
    """Commands for character analysis."""

    def __init__(self, bot: SentinelBot) -> None:
        self.bot = bot

    @app_commands.command(name="analyze", description="Analyze an EVE Online character")
    @app_commands.describe(character="Character name or ID to analyze")
    async def analyze(self, interaction: discord.Interaction, character: str) -> None:
        """Analyze a character and return risk assessment."""
        await interaction.response.defer(thinking=True)

        try:
            # Resolve character
            character_id = None
            if character.isdigit():
                character_id = int(character)
            else:
                character_id = await self.bot.esi_client.search_character(character)

            if not character_id:
                await interaction.followup.send(
                    embed=self._error_embed(f"Character '{character}' not found"),
                    ephemeral=True,
                )
                return

            # Run analysis
            applicant = await self.bot.esi_client.build_applicant(character_id)
            applicant = await self.bot.zkill_client.enrich_applicant(applicant)
            report = await self.bot.risk_scorer.analyze(
                applicant,
                requested_by=f"discord:{interaction.user.name}",
            )

            # Save report
            async with get_session() as session:
                repo = ReportRepository(session)
                await repo.save(report)

            # Build embed
            embed = self._report_embed(report)
            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            await interaction.followup.send(
                embed=self._error_embed(f"Analysis failed: {str(e)}"),
                ephemeral=True,
            )

    @app_commands.command(name="quick-check", description="Quick risk check for a character")
    @app_commands.describe(character="Character name or ID to check")
    async def quick_check(self, interaction: discord.Interaction, character: str) -> None:
        """Quick check without saving report."""
        await interaction.response.defer(thinking=True)

        try:
            character_id = None
            if character.isdigit():
                character_id = int(character)
            else:
                character_id = await self.bot.esi_client.search_character(character)

            if not character_id:
                await interaction.followup.send(
                    embed=self._error_embed(f"Character '{character}' not found"),
                    ephemeral=True,
                )
                return

            # Get basic info
            char_info = await self.bot.esi_client.get_character(character_id)
            corp_history = await self.bot.esi_client.get_character_corp_history(character_id)

            # Build quick summary embed
            embed = discord.Embed(
                title=f"Quick Check: {char_info.get('name', 'Unknown')}",
                color=discord.Color.blue(),
                timestamp=datetime.now(UTC),
            )

            # Character age
            birthday = char_info.get("birthday", "")
            if birthday:
                try:
                    birth_date = datetime.fromisoformat(birthday.replace("Z", "+00:00"))
                    age_days = (datetime.now(UTC) - birth_date).days
                    embed.add_field(
                        name="Character Age",
                        value=f"{age_days} days ({age_days // 365} years)",
                        inline=True,
                    )
                except ValueError:
                    pass

            # Corp history count
            embed.add_field(
                name="Corp History",
                value=f"{len(corp_history)} corporations",
                inline=True,
            )

            # Security status
            sec_status = char_info.get("security_status", 0)
            embed.add_field(
                name="Security Status",
                value=f"{sec_status:.2f}",
                inline=True,
            )

            embed.set_footer(text="Use /analyze for full analysis")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Quick check failed: {e}")
            await interaction.followup.send(
                embed=self._error_embed(f"Quick check failed: {str(e)}"),
                ephemeral=True,
            )

    def _report_embed(self, report) -> discord.Embed:
        """Build a Discord embed from an analysis report."""
        # Color based on risk
        color_map = {
            "RED": discord.Color.red(),
            "YELLOW": discord.Color.gold(),
            "GREEN": discord.Color.green(),
        }
        color = color_map.get(report.overall_risk.value, discord.Color.greyple())

        embed = discord.Embed(
            title=f"Analysis: {report.character_name}",
            description=f"**Risk Level: {report.overall_risk.value}** (Confidence: {report.confidence:.0%})",
            color=color,
            timestamp=report.created_at,
        )

        # Flag summary
        embed.add_field(
            name="Flags",
            value=f"🔴 {report.red_flag_count} Red | 🟡 {report.yellow_flag_count} Yellow | 🟢 {report.green_flag_count} Green",
            inline=False,
        )

        # Red flags (if any)
        red_flags = [f for f in report.flags if f.severity.value == "RED"]
        if red_flags:
            red_flag_text = "\n".join(f"• {f.title}" for f in red_flags[:5])
            if len(red_flags) > 5:
                red_flag_text += f"\n... and {len(red_flags) - 5} more"
            embed.add_field(name="🔴 Red Flags", value=red_flag_text, inline=False)

        # Yellow flags (if any)
        yellow_flags = [f for f in report.flags if f.severity.value == "YELLOW"]
        if yellow_flags:
            yellow_flag_text = "\n".join(f"• {f.title}" for f in yellow_flags[:3])
            if len(yellow_flags) > 3:
                yellow_flag_text += f"\n... and {len(yellow_flags) - 3} more"
            embed.add_field(name="🟡 Yellow Flags", value=yellow_flag_text, inline=False)

        # Recommendations
        if report.recommendations:
            rec_text = "\n".join(f"• {r}" for r in report.recommendations[:3])
            embed.add_field(name="Recommendations", value=rec_text, inline=False)

        # Link to full report
        if settings.base_url:
            embed.add_field(
                name="Full Report",
                value=f"[View Details]({settings.base_url}/reports/{report.report_id})",
                inline=False,
            )

        embed.set_footer(text=f"Report ID: {report.report_id}")

        return embed

    def _error_embed(self, message: str) -> discord.Embed:
        """Build an error embed."""
        return discord.Embed(
            title="Error",
            description=message,
            color=discord.Color.red(),
        )


class WatchlistCog(commands.Cog, name="Watchlist"):
    """Commands for watchlist management."""

    def __init__(self, bot: SentinelBot) -> None:
        self.bot = bot

    @app_commands.command(name="watch", description="Add a character to the watchlist")
    @app_commands.describe(
        character="Character name or ID to watch",
        priority="Priority level",
        reason="Reason for watching",
    )
    @app_commands.choices(
        priority=[
            app_commands.Choice(name="Low", value="low"),
            app_commands.Choice(name="Normal", value="normal"),
            app_commands.Choice(name="High", value="high"),
            app_commands.Choice(name="Critical", value="critical"),
        ]
    )
    async def watch(
        self,
        interaction: discord.Interaction,
        character: str,
        priority: str = "normal",
        reason: str | None = None,
    ) -> None:
        """Add a character to the watchlist."""
        await interaction.response.defer(ephemeral=True)

        try:
            # Resolve character
            character_id = None
            character_name = character
            if character.isdigit():
                character_id = int(character)
                char_info = await self.bot.esi_client.get_character(character_id)
                character_name = char_info.get("name", character)
            else:
                character_id = await self.bot.esi_client.search_character(character)
                if character_id:
                    char_info = await self.bot.esi_client.get_character(character_id)
                    character_name = char_info.get("name", character)

            if not character_id:
                await interaction.followup.send(
                    f"Character '{character}' not found",
                    ephemeral=True,
                )
                return

            # Add to watchlist
            async with get_session() as session:
                repo = WatchlistRepository(session)

                # Check if already watched
                existing = await repo.get_by_character_id(character_id)
                if existing:
                    await interaction.followup.send(
                        f"**{character_name}** is already on the watchlist",
                        ephemeral=True,
                    )
                    return

                entry = await repo.add(
                    character_id=character_id,
                    character_name=character_name,
                    added_by=f"discord:{interaction.user.name}",
                    reason=reason,
                    priority=priority,
                )

            embed = discord.Embed(
                title="Added to Watchlist",
                description=f"**{character_name}** has been added to the watchlist",
                color=discord.Color.green(),
            )
            embed.add_field(name="Priority", value=priority.title(), inline=True)
            if reason:
                embed.add_field(name="Reason", value=reason, inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Watch command failed: {e}")
            await interaction.followup.send(
                f"Failed to add to watchlist: {str(e)}",
                ephemeral=True,
            )

    @app_commands.command(name="unwatch", description="Remove a character from the watchlist")
    @app_commands.describe(character="Character name or ID to remove")
    async def unwatch(self, interaction: discord.Interaction, character: str) -> None:
        """Remove a character from the watchlist."""
        await interaction.response.defer(ephemeral=True)

        try:
            character_id = int(character) if character.isdigit() else None
            if not character_id:
                character_id = await self.bot.esi_client.search_character(character)

            if not character_id:
                await interaction.followup.send(
                    f"Character '{character}' not found",
                    ephemeral=True,
                )
                return

            async with get_session() as session:
                repo = WatchlistRepository(session)
                removed = await repo.remove_by_character_id(character_id)

            if removed:
                await interaction.followup.send(
                    f"Removed from watchlist",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"Character not found on watchlist",
                    ephemeral=True,
                )

        except Exception as e:
            logger.error(f"Unwatch command failed: {e}")
            await interaction.followup.send(
                f"Failed to remove from watchlist: {str(e)}",
                ephemeral=True,
            )

    @app_commands.command(name="watchlist", description="View the current watchlist")
    async def watchlist(self, interaction: discord.Interaction) -> None:
        """View the current watchlist."""
        await interaction.response.defer()

        try:
            async with get_session() as session:
                repo = WatchlistRepository(session)
                entries = await repo.list_all(limit=25)
                stats = {
                    "total": await repo.count(),
                    "critical": await repo.count(priority="critical"),
                    "high": await repo.count(priority="high"),
                }

            if not entries:
                await interaction.followup.send("Watchlist is empty")
                return

            embed = discord.Embed(
                title="EVE Sentinel Watchlist",
                description=f"Total: {stats['total']} | Critical: {stats['critical']} | High: {stats['high']}",
                color=discord.Color.blue(),
            )

            # Group by priority
            for priority in ["critical", "high", "normal", "low"]:
                priority_entries = [e for e in entries if e.priority == priority]
                if priority_entries:
                    value = "\n".join(
                        f"• {e.character_name} ({e.last_risk_level or 'Not analyzed'})"
                        for e in priority_entries[:5]
                    )
                    if len(priority_entries) > 5:
                        value += f"\n... and {len(priority_entries) - 5} more"
                    embed.add_field(
                        name=f"{priority.title()} Priority",
                        value=value,
                        inline=False,
                    )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Watchlist command failed: {e}")
            await interaction.followup.send(f"Failed to get watchlist: {str(e)}")


class ReportsCog(commands.Cog, name="Reports"):
    """Commands for viewing reports."""

    def __init__(self, bot: SentinelBot) -> None:
        self.bot = bot

    @app_commands.command(name="recent", description="View recent analysis reports")
    @app_commands.describe(count="Number of reports to show (1-10)")
    async def recent(self, interaction: discord.Interaction, count: int = 5) -> None:
        """View recent reports."""
        await interaction.response.defer()

        count = min(max(count, 1), 10)

        try:
            async with get_session() as session:
                repo = ReportRepository(session)
                reports = await repo.list_reports(limit=count)

            if not reports:
                await interaction.followup.send("No reports found")
                return

            embed = discord.Embed(
                title="Recent Analysis Reports",
                color=discord.Color.blue(),
            )

            for report in reports:
                risk_emoji = {"RED": "🔴", "YELLOW": "🟡", "GREEN": "🟢"}.get(
                    report.overall_risk.value, "⚪"
                )
                value = f"{risk_emoji} {report.overall_risk.value} | {report.red_flag_count}R {report.yellow_flag_count}Y {report.green_flag_count}G"
                embed.add_field(
                    name=report.character_name,
                    value=value,
                    inline=False,
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Recent command failed: {e}")
            await interaction.followup.send(f"Failed to get reports: {str(e)}")

    @app_commands.command(name="stats", description="View analysis statistics")
    async def stats(self, interaction: discord.Interaction) -> None:
        """View analysis statistics."""
        await interaction.response.defer()

        try:
            async with get_session() as session:
                repo = ReportRepository(session)
                from backend.models.report import OverallRisk

                total = await repo.count_reports()
                red = await repo.count_reports(OverallRisk.RED)
                yellow = await repo.count_reports(OverallRisk.YELLOW)
                green = await repo.count_reports(OverallRisk.GREEN)

            embed = discord.Embed(
                title="EVE Sentinel Statistics",
                color=discord.Color.blue(),
            )

            embed.add_field(name="Total Reports", value=str(total), inline=True)
            embed.add_field(name="🔴 Red", value=str(red), inline=True)
            embed.add_field(name="🟡 Yellow", value=str(yellow), inline=True)
            embed.add_field(name="🟢 Green", value=str(green), inline=True)

            if total > 0:
                embed.add_field(
                    name="Risk Distribution",
                    value=f"Red: {red/total:.1%} | Yellow: {yellow/total:.1%} | Green: {green/total:.1%}",
                    inline=False,
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Stats command failed: {e}")
            await interaction.followup.send(f"Failed to get stats: {str(e)}")


async def run_bot() -> None:
    """Run the Discord bot."""
    if not settings.discord_bot_token:
        logger.error("DISCORD_BOT_TOKEN not configured")
        return

    bot = SentinelBot()

    try:
        await bot.start(settings.discord_bot_token)
    except Exception as e:
        logger.error(f"Bot failed to start: {e}")
        raise


def main() -> None:
    """Entry point for running the bot standalone."""
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
