import os
import re
import asyncio
import discord
from discord.ext import commands
from discord.ui import View, Button, Select, Modal, TextInput

# Setup Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="?", intents=intents)

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def get_middleman_role(guild: discord.Guild):
    """Auto-detects the Middleman role by name ('middle man')."""
    return discord.utils.find(lambda r: r.name.lower() == "middle man", guild.roles)

def parse_time(time_str: str) -> int:
    """Parses time strings like '10s', '5m', '1h', '1d' into seconds."""
    match = re.match(r"^(\d+)\s*(s|sec|m|min|h|hr|d|day)?$", time_str.lower())
    if not match:
        return None
    amount, unit = match.groups()
    amount = int(amount)
    if not unit or unit in ['s', 'sec']:
        return amount
    elif unit in ['m', 'min']:
        return amount * 60
    elif unit in ['h', 'hr']:
        return amount * 3600
    elif unit in ['d', 'day']:
        return amount * 86400
    return None

# ==========================================
# UI COMPONENTS (MODAL, SELECT, VIEWS)
# ==========================================

class TicketDetailsModal(Modal, title="Middleman Trade Details"):
    giving = TextInput(
        label="What are you giving?",
        placeholder="e.g., Dragon Fruit in Blox Fruits",
        style=discord.TextStyle.short,
        required=True
    )
    receiving = TextInput(
        label="What are you receiving?",
        placeholder="e.g., $20 Gift Card / Robux",
        style=discord.TextStyle.short,
        required=True
    )

    def __init__(self, partner: discord.Member):
        super().__init__()
        self.partner = partner

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        creator = interaction.user
        partner = self.partner

        # Auto-detect Middleman Role
        mm_role = get_middleman_role(guild)
        if not mm_role:
            await interaction.followup.send(
                "❌ Error: Could not find a role named 'middle man' in this server.",
                ephemeral=True
            )
            return

        # Setup Category / Overwrites
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            creator: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            partner: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            mm_role: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        # Create Private Ticket Channel
        channel_name = f"ticket-{creator.name}-and-{partner.name}"
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            overwrites=overwrites
        )

        # Send initial ticket message with ping & controls
        embed = discord.Embed(
            title="🤝 Middleman Request Ticket",
            description=f"Welcome {creator.mention} and {partner.mention}!\nA middleman will be with you shortly.",
            color=discord.Color.blue()
        )
        embed.add_field(name="👤 Requester", value=creator.mention, inline=True)
        embed.add_field(name="👤 Trading Partner", value=partner.mention, inline=True)
        embed.add_field(name="📤 Giving", value=self.giving.value, inline=False)
        embed.add_field(name="📥 Receiving", value=self.receiving.value, inline=False)
        embed.set_footer(text="Status: Unclaimed | Valks Market")

        view = TicketControlView(creator_id=creator.id, partner_id=partner.id)
        
        await ticket_channel.send(
            content=f"{mm_role.mention} - New trade request!",
            embed=embed,
            view=view
        )

        await interaction.followup.send(
            f"✅ Ticket created successfully! Head over to {ticket_channel.mention}",
            ephemeral=True
        )


class UserSelectView(View):
    """Dropdown list containing server members with native search."""
    def __init__(self, members):
        super().__init__(timeout=180)
        select = Select(
            placeholder="Search and select your trading partner...",
            min_values=1,
            max_values=1
        )
        for member in members[:25]:  # Discord limits dropdowns to 25 items max
            select.add_option(
                label=f"{member.display_name} ({member.name})",
                value=str(member.id),
                description=f"ID: {member.id}"
            )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        selected_id = int(interaction.data["values"][0])
        partner = interaction.guild.get_member(selected_id)

        if partner.id == interaction.user.id:
            await interaction.response.send_message("❌ You cannot select yourself as a trading partner!", ephemeral=True)
            return
        if partner.bot:
            await interaction.response.send_message("❌ You cannot select a bot as a trading partner!", ephemeral=True)
            return

        # Open the modal details form
        await interaction.response.send_modal(TicketDetailsModal(partner=partner))


class TicketControlView(View):
    """Control panel inside the created ticket (Claim & Close)."""
    def __init__(self, creator_id: int, partner_id: int):
        super().__init__(timeout=None)
        self.claimed_by: discord.Member = None
        self.creator_id = creator_id
        self.partner_id = partner_id

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.green, custom_id="claim_ticket")
    async def claim_button(self, interaction: discord.Interaction, button: Button):
        mm_role = get_middleman_role(interaction.guild)
        if mm_role not in interaction.user.roles and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only Middlemen can claim this ticket!", ephemeral=True)
            return

        if self.claimed_by is not None:
            await interaction.response.send_message(f"❌ This ticket is already claimed by {self.claimed_by.mention}!", ephemeral=True)
            return

        self.claimed_by = interaction.user
        
        # Adjust channel permissions: Lock out other Middlemen
        channel = interaction.channel
        guild = interaction.guild
        creator = guild.get_member(self.creator_id)
        partner = guild.get_member(self.partner_id)

        # Remove general MM role view access, keep claimed MM, creator, and partner
        await channel.set_permissions(mm_role, read_messages=False)
        await channel.set_permissions(interaction.user, read_messages=True, send_messages=True)
        if creator:
            await channel.set_permissions(creator, read_messages=True, send_messages=True)
        if partner:
            await channel.set_permissions(partner, read_messages=True, send_messages=True)

        button.disabled = True
        button.label = f"Claimed by {interaction.user.display_name}"
        await interaction.response.edit_message(view=self)
        
        await channel.send(f"🔒 **Ticket Claimed!** {interaction.user.mention} is your middleman for this trade.")

    @discord.ui.button(label="Close", style=discord.ButtonStyle.red, custom_id="close_ticket")
    async def close_button(self, interaction: discord.Interaction, button: Button):
        mm_role = get_middleman_role(interaction.guild)
        if mm_role not in interaction.user.roles and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only Middlemen can close this ticket!", ephemeral=True)
            return

        await interaction.response.send_message("🔒 Closing ticket in 5 seconds...")
        await asyncio.sleep(5)
        await interaction.channel.delete()


class PanelView(View):
    """Persistent Panel view with the main Request Middleman button."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Request Middleman", style=discord.ButtonStyle.primary, custom_id="req_mm_btn")
    async def request_mm(self, interaction: discord.Interaction, button: Button):
        # Fetch non-bot members for the dropdown menu
        members = [m for m in interaction.guild.members if not m.bot and m.id != interaction.user.id]
        if not members:
            await interaction.response.send_message("❌ No eligible members found to trade with.", ephemeral=True)
            return

        await interaction.response.send_message(
            "Select your trading partner from the list below:",
            view=UserSelectView(members),
            ephemeral=True
        )

# ==========================================
# BOT EVENTS & COMMANDS
# ==========================================

@bot.event
async def on_ready():
    # Add persistent view so panel buttons survive restarts
    bot.add_view(PanelView())
    print(f"✅ Bot is live as {bot.user}")

@bot.command()
@commands.has_permissions(administrator=True)
async def mmpanel(ctx):
    """Sends the formatted Middleman panel."""
    await ctx.message.delete()
    
    embed = discord.Embed(
        title="🔒 Valks market middle man",
        description=(
            "🔸 To request a middleman from this server, click the blue **\"Request Middleman\"** button on this message.\n\n"
            "🤝 **How does middleman work?**\n"
            "🔸 *Example: Trade is Dragon Fruit for Robux.*\n"
            "1. Seller gives Dragon Fruit to Middleman.\n"
            "2. Buyer pays seller Robux (After middleman confirms receiving item).\n"
            "3. Middleman gives buyer Dragon Fruit (After seller confirms receiving payment).\n\n"
            "🔒 **NOTES:**\n"
            "1. You must both agree on the deal before using a middleman. **Troll tickets will have consequences.**\n"
            "2. Specify what you're trading clearly (e.g., *Dragon Fruit in Blox Fruits > $20 Gift Card*). Don't just put generic terms in the form."
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text="Secure trading • valks market")
    
    await ctx.send(embed=embed, view=PanelView())

@bot.command()
async def claim(ctx):
    """Command to claim a ticket channel."""
    mm_role = get_middleman_role(ctx.guild)
    if mm_role not in ctx.author.roles and not ctx.author.guild_permissions.administrator:
        return await ctx.send("❌ Only Middlemen can use this command.")

    # Hide channel from general MM role and assign explicitly to command user
    await ctx.channel.set_permissions(mm_role, read_messages=False)
    await ctx.channel.set_permissions(ctx.author, read_messages=True, send_messages=True)
    await ctx.send(f"🔒 Ticket claimed by {ctx.author.mention}!")

@bot.command()
async def unclaim(ctx):
    """Command to unclaim a ticket channel."""
    mm_role = get_middleman_role(ctx.guild)
    if mm_role not in ctx.author.roles and not ctx.author.guild_permissions.administrator:
        return await ctx.send("❌ Only Middlemen can use this command.")

    # Restore access to the general MM role and reset user specific override
    await ctx.channel.set_permissions(mm_role, read_messages=True, send_messages=True)
    await ctx.channel.set_permissions(ctx.author, overwrite=None)
    await ctx.send(f"🔓 Ticket unclaimed! Returned to the {mm_role.mention} queue.")

@bot.command()
async def transfer(ctx, new_mm: discord.Member):
    """Transfer ticket to another Middleman."""
    mm_role = get_middleman_role(ctx.guild)
    if mm_role not in ctx.author.roles and not ctx.author.guild_permissions.administrator:
        return await ctx.send("❌ Only Middlemen can transfer tickets.")

    if mm_role not in new_mm.roles:
        return await ctx.send("❌ Target member is not a Middleman!")

    # Revoke current author permission and set new MM permission
    await ctx.channel.set_permissions(ctx.author, overwrite=None)
    await ctx.channel.set_permissions(new_mm, read_messages=True, send_messages=True)
    await ctx.send(f"🔄 Ticket transferred to {new_mm.mention}!")

@bot.command()
async def adduser(ctx, member: discord.Member):
    """Add a user to the current ticket."""
    mm_role = get_middleman_role(ctx.guild)
    if mm_role not in ctx.author.roles and not ctx.author.guild_permissions.administrator:
        return await ctx.send("❌ Only Middlemen can add users.")

    await ctx.channel.set_permissions(member, read_messages=True, send_messages=True)
    await ctx.send(f"➕ Added {member.mention} to this ticket.")

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    """Ban a user: ?ban @user [reason]"""
    await member.ban(reason=reason)
    await ctx.send(f"🔨 Banned **{member.display_name}** | Reason: {reason}")

@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, duration: str, *, reason: str = "No reason provided"):
    """Mute/Timeout a user: ?mute @user 1sec or 1hr or 10m"""
    seconds = parse_time(duration)
    if not seconds:
        return await ctx.send("❌ Invalid duration format! Example: `10s`, `1hr`, `2d`.")

    time_delta = discord.utils.utcnow() + discord.utils.timedelta(seconds=seconds)
    await member.timeout(time_delta, reason=reason)
    await ctx.send(f"🔇 Muted **{member.display_name}** for `{duration}` | Reason: {reason}")

# Retrieve Token securely from Environment Variables
TOKEN = os.getenv('DISCORD_TOKEN')
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ DISCORD_TOKEN variable not found! Make sure to set it.")
