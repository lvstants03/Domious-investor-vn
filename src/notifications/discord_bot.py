import asyncio
import logging
from typing import Optional
from src.config import settings

logger = logging.getLogger("dominus-investor.notifications.discord_bot")

class DiscordBotClient:
    def __init__(self):
        self.token = settings.DISCORD_BOT_TOKEN
        self.channel_id = settings.DISCORD_CHANNEL_ID
        self.client = None
        self._task = None

    async def start(self):
        if not settings.DISCORD_ENABLED or not self.token:
            logger.info("Discord Bot chua duoc kich hoat hoac thieu BOT_TOKEN.")
            return

        try:
            import discord
            from discord.ext import commands
            
            # Setup intents
            intents = discord.Intents.default()
            intents.message_content = True
            
            self.client = commands.Bot(command_prefix="/", intents=intents)
            
            @self.client.event
            async def on_ready():
                logger.info("Discord Bot '%s' dang hoat dong!", self.client.user)
                
            # Dinh nghia callback cho button click
            class ConfirmView(discord.ui.View):
                def __init__(self, symbol: str, price: float, score: float):
                    super().__init__(timeout=60.0)
                    self.symbol = symbol
                    self.price = price
                    self.score = score

                @discord.ui.button(label="Mua Paper", style=discord.ButtonStyle.green, custom_id="buy_paper")
                async def buy_paper_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
                    await interaction.response.defer()
                    # Goi API dat lenh paper trong local DB
                    from src.database.connection import get_db_session
                    from src.bot.paper_trader import PaperTrader
                    
                    async with get_db_session() as session:
                        trader = PaperTrader(session)
                        # Gia su dat lo mac dinh 100 co phieu
                        success = await trader.execute_buy(bot_config_id=1, symbol=self.symbol, qty=100, price=self.price)
                        
                    if success:
                        await interaction.followup.send(f"✅ Da khop lenh mua GIẢ LẬP 100 mã **{self.symbol}** o gia {self.price:,.0f} VND.")
                    else:
                        await interaction.followup.send("❌ Dat lenh gia lap that bai.")
                    self.stop()

                @discord.ui.button(label="Mua Live", style=discord.ButtonStyle.danger, custom_id="buy_live")
                async def buy_live_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
                    await interaction.response.defer()
                    # Live trading thuc te
                    from src.database.connection import get_db_session
                    from src.bot.live_trader import LiveTrader
                    
                    async with get_db_session() as session:
                        trader = LiveTrader(session)
                        success = await trader.execute_buy(bot_config_id=1, symbol=self.symbol, qty=100, price=self.price)
                        
                    if success:
                        await interaction.followup.send(f"🚀 Da gui lenh mua THẬT 100 mã **{self.symbol}** len sàn TCBS ở giá {self.price:,.0f} VND.")
                    else:
                        await interaction.followup.send("❌ Dat lenh that len TCBS that bai.")
                    self.stop()

                @discord.ui.button(label="Bo qua", style=discord.ButtonStyle.secondary, custom_id="ignore")
                async def ignore_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
                    await interaction.response.send_message("Da bo qua tin hieu nay.", ephemeral=True)
                    self.stop()

            self.ConfirmView = ConfirmView
            
            # Start client trong background task
            self._task = asyncio.create_task(self.client.start(self.token))
            
        except ImportError:
            logger.warning("Chua cai dat package 'discord.py'. Chức năng Discord Buttons dang hoat dong o che do giap lap log.")
        except Exception as e:
            logger.error("Loi khi khoi dong Discord Bot Client: %s", str(e))

    async def send_scan_alert(self, symbol: str, price: float, score: float, reasons: list):
        """Gui tin nhan thong bao kem cac nút tuong tac (Buttons)"""
        if not self.client or not self.client.is_ready():
            # Fallback sang log hoac webhook thong thuong
            logger.info("[SCAN ALERT MOCK BUTTONS] %s price: %s, score: %s, reasons: %s", symbol, price, score, reasons)
            return

        try:
            import discord
            channel = self.client.get_channel(int(self.channel_id))
            if not channel:
                logger.error("Khong tim thay Discord Channel ID: %s", self.channel_id)
                return

            embed = discord.Embed(
                title=f"🔍 Tín hiệu quét cổ phiếu: {symbol}",
                description=f"Cổ phiếu **{symbol}** đạt điểm tiềm năng rất cao!",
                color=discord.Color.blue()
            )
            embed.add_field(name="Điểm đánh giá", value=f"**{score}/100**", inline=True)
            embed.add_field(name="Giá hiện tại", value=f"**{price:,.0f} VND**", inline=True)
            embed.add_field(name="Các tiêu chí thoả mãn", value="\n".join([f"• {r}" for r in reasons]), inline=False)
            
            view = self.ConfirmView(symbol=symbol, price=price, score=score)
            await channel.send(embed=embed, view=view)
            
        except Exception as e:
            logger.error("Loi khi gui tin nhan qua Discord Bot: %s", str(e))

    async def stop(self):
        if self.client:
            await self.client.close()
        if self._task:
            self._task.cancel()

discord_bot = DiscordBotClient()
