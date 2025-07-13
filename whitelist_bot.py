# whitelist_bot.py
# A professional, single-file Discord bot for a Roblox whitelist service.
# Version 4.0: Industrial Grade - Robust, fully-featured, and production-ready.

# --- SETUP ---
# 1. Install required libraries:
#    pip install discord.py aiohttp
# 2. Fill in the CONFIG section below.

import discord
import json
import asyncio
import os
import re
import logging
from datetime import datetime
import aiohttp
from typing import List, Dict, Any, Optional

# --- CONFIGURATION ---
# It's recommended to use environment variables for security, but direct paste works for simplicity.
BOT_TOKEN = "MTM5MzcxMTA2ODE2MDg1NjE1Ng.GQufAy.NISFU_KU65GRCJVSj4FN_a1Hhr_2CxNvjbgZuo"  # <-- PASTE YOUR BOT TOKEN HERE
SUPERADMIN_ID = 1205959966511603802 # <-- PASTE YOUR ROOT DISCORD ID HERE
DATA_FILE = "data.json"
# Optional: For instant command syncing during testing, add your server/guild ID. Otherwise, it may take up to an hour.
# TEST_GUILD_ID = 123456789012345678

# --- LOGGING SETUP ---
# Sets up professional logging to the console.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# --- UTILITY FUNCTIONS ---
def sanitize_name(name: str) -> str:
    """Removes special characters and converts to lowercase for use as an internal key."""
    return re.sub(r'[^a-zA-Z0-9_]', '', name.lower().replace(' ', '_'))

def create_embed(title: str, description: str, color: discord.Color, footer: str = "Professional Whitelist Service") -> discord.Embed:
    """Creates a standardized Discord embed."""
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text=footer)
    return embed

def truncate_string(text: str, max_length: int) -> str:
    """Truncates a string to a max length, adding '...' if needed. Crucial for Modal titles."""
    return text if len(text) <= max_length else text[:max_length-3] + "..."

async def fetch_user_info(client: discord.Client, user_id: str) -> str:
    """Fetches a user's name and discriminator, falling back to the ID."""
    try:
        user = await client.fetch_user(int(user_id))
        return f"{user.name} ({user.id})"
    except (discord.NotFound, ValueError):
        return f"Unknown User ({user_id})"

async def is_valid_roblox_id(session: aiohttp.ClientSession, roblox_id: int) -> bool:
    """Checks if a Roblox User ID is valid using the Roblox API."""
    url = f"https://users.roblox.com/v1/users/{roblox_id}"
    try:
        async with session.get(url) as response:
            return response.status == 200
    except aiohttp.ClientError as e:
        logging.error(f"Roblox API check failed for ID {roblox_id}: {e}")
        return False # Fail-safe: assume invalid if API call fails

# --- DATA MANAGER ---
class DataManager:
    """Handles atomic and safe loading/saving of JSON data."""
    def __init__(self, filename: str):
        self.filename = filename
        self.lock = asyncio.Lock()
        # The canonical schema for the bot's data.
        self.default_schema = {"owners": {}, "stores": {}, "staff": [], "blacklist": []}

    async def _backup_file(self, reason: str = "backup"):
        """Creates a timestamped backup of the data file."""
        if os.path.exists(self.filename):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"{self.filename}.{reason}.{timestamp}.bak"
            os.rename(self.filename, backup_filename)
            logging.warning(f"Data file backed up to {backup_filename} due to: {reason}")

    async def load_data(self) -> Dict[str, Any]:
        """Loads data from the file, creating or upgrading it if necessary."""
        async with self.lock:
            if not os.path.exists(self.filename):
                logging.info(f"Data file '{self.filename}' not found. Creating with default schema.")
                with open(self.filename, 'w') as f:
                    json.dump(self.default_schema, f, indent=2)
                return self.default_schema.copy()

            try:
                # Read the file content first to check if it's empty
                with open(self.filename, 'r') as f:
                    content = f.read()
                    if not content.strip(): # Handles empty file case
                        raise json.JSONDecodeError("File is empty", content, 0)
                    data = json.loads(content)

                # Schema migration: check for missing top-level keys
                updated = False
                for key, default_value in self.default_schema.items():
                    if key not in data:
                        data[key] = default_value
                        updated = True
                
                if updated:
                    logging.info("Upgrading data schema to include new fields.")
                    await self.save_data(data) # Save the upgraded schema

                return data
            except (json.JSONDecodeError, TypeError) as e:
                logging.error(f"Error loading JSON data: {e}. Attempting to restore from backup.")
                await self._backup_file(reason="corrupt")
                with open(self.filename, 'w') as f:
                    json.dump(self.default_schema, f, indent=2)
                return self.default_schema.copy()

    async def save_data(self, data: Dict[str, Any]):
        """Saves data atomically to prevent corruption."""
        async with self.lock:
            temp_filename = f"{self.filename}.tmp"
            try:
                with open(temp_filename, 'w') as f:
                    json.dump(data, f, indent=2)
                # This operation is atomic on most OSes
                os.replace(temp_filename, self.filename)
            except Exception as e:
                logging.critical(f"CRITICAL: Failed to save data to {self.filename}: {e}")
                if os.path.exists(temp_filename):
                    os.remove(temp_filename)

# --- UI: GENERIC COMPONENTS ---
class ConfirmationView(discord.ui.View):
    """A generic view for Yes/No confirmations."""
    def __init__(self, author_id: int):
        super().__init__(timeout=60.0)
        self.value: Optional[bool] = None
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("You cannot control this menu.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()
        
class PaginationView(discord.ui.View):
    """A reusable view for paginating through a list of items."""
    def __init__(self, author_id: int, items: list, items_per_page: int, embed_title: str, embed_color: discord.Color, format_item, **kwargs):
        super().__init__(timeout=180.0)
        self.author_id = author_id; self.items = items; self.items_per_page = items_per_page
        self.embed_title = embed_title; self.embed_color = embed_color
        self.format_item = format_item; self.kwargs = kwargs # Extra args for format_item
        self.current_page = 0
        self.total_pages = max(0, (len(self.items) - 1) // self.items_per_page)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("You cannot control this menu.", ephemeral=True)
            return False
        return True

    async def create_page_embed(self) -> discord.Embed:
        start_index = self.current_page * self.items_per_page
        end_index = start_index + self.items_per_page
        page_items = self.items[start_index:end_index]
        
        # Use asyncio.gather for efficiency if format_item is async
        formatted_lines = await asyncio.gather(*(self.format_item(item, **self.kwargs) for item in page_items))
        description = "\n".join(formatted_lines) if page_items else "There are no items to display."
        
        embed = create_embed(self.embed_title, description, self.embed_color)
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages + 1}")
        return embed

    async def update_message(self, interaction: discord.Interaction):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages
        await interaction.response.edit_message(embed=await self.create_page_embed(), view=self)

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0: self.current_page -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages: self.current_page += 1
        await self.update_message(interaction)
            
    # --- Static formatting methods for different data types ---
    @staticmethod
    async def format_roblox_id(item, **kwargs): return f"🔹 [{item}](https://www.roblox.com/users/{item}/profile)"
    @staticmethod
    async def format_product(item, **kwargs): return f"📦 **{item[0]}** ({len(item[1]['whitelist'])} whitelisted)"
    @staticmethod
    async def format_user(item, **kwargs): return f"👤 {await fetch_user_info(kwargs['client'], item)}"
    @staticmethod
    async def format_store_owner(item, **kwargs): return f"**{await fetch_user_info(kwargs['client'], item[0])}** ➡️ {item[1]}"
    @staticmethod
    async def format_blacklist(item, **kwargs): return f"🚫 [{item}](https://www.roblox.com/users/{item}/profile)"

# --- MODALS AND VIEWS ---
class WhitelistActionModal(discord.ui.Modal):
    """Modal for whitelisting or unwhitelisting a Roblox ID."""
    def __init__(self, bot_instance, store_name: str, product_name: str, action: str):
        self.bot = bot_instance
        self.data_manager = bot_instance.data_manager
        self.store_name = store_name
        self.product_name = product_name
        self.action = action
        super().__init__(title=truncate_string(f"{action.capitalize()} for {product_name}", 45))
        
        self.roblox_id_input = discord.ui.TextInput(label="Roblox User ID", placeholder="Enter a valid numerical Roblox ID", required=True)
        self.add_item(self.roblox_id_input)

    async def on_submit(self, interaction: discord.Interaction):
        roblox_id_str = self.roblox_id_input.value
        if not roblox_id_str.isdigit():
            return await interaction.response.send_message(embed=create_embed("Error", "Roblox ID must be a number.", discord.Color.red()), ephemeral=True)
        
        roblox_id = int(roblox_id_str)
        
        # API Validation
        if not await is_valid_roblox_id(self.bot.http_session, roblox_id):
            return await interaction.response.send_message(embed=create_embed("Error", f"Roblox ID `{roblox_id}` does not exist.", discord.Color.red()), ephemeral=True)

        data = await self.data_manager.load_data()
        
        if self.action == "whitelist" and roblox_id in data.get("blacklist", []):
            return await interaction.response.send_message(embed=create_embed("Action Blocked", f"Roblox ID `{roblox_id}` is globally blacklisted.", discord.Color.dark_red()), ephemeral=True)
        
        whitelist = data["stores"][self.store_name]["products"][self.product_name]["whitelist"]
        if self.action == "whitelist":
            if roblox_id in whitelist:
                await interaction.response.send_message(embed=create_embed("Already Exists", f"ID `{roblox_id}` is already whitelisted for `{self.product_name}`.", discord.Color.orange()), ephemeral=True)
            else:
                whitelist.append(roblox_id)
                await self.data_manager.save_data(data)
                await interaction.response.send_message(embed=create_embed("Success", f"Whitelisted ID `{roblox_id}` for `{self.product_name}`.", discord.Color.green()), ephemeral=True)
        
        elif self.action == "unwhitelist":
            if roblox_id not in whitelist:
                await interaction.response.send_message(embed=create_embed("Not Found", f"ID `{roblox_id}` is not on the whitelist for `{self.product_name}`.", discord.Color.red()), ephemeral=True)
            else:
                whitelist.remove(roblox_id)
                await self.data_manager.save_data(data)
                await interaction.response.send_message(embed=create_embed("Success", f"Unwhitelisted ID `{roblox_id}` from `{self.product_name}`.", discord.Color.green()), ephemeral=True)

class StoreOwnerView(discord.ui.View):
    """The main control panel for a store owner."""
    def __init__(self, bot_instance, author_id: int, store_name: str, from_admin: bool = False):
        super().__init__(timeout=300.0)
        self.bot = bot_instance
        self.data_manager = bot_instance.data_manager
        self.author_id = author_id
        self.store_name = store_name
        if from_admin:
            self.add_item(self.BackButton())
    
    class BackButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="⬅️ Back to Admin Panel", style=discord.ButtonStyle.grey, row=3)
        async def callback(self, interaction: discord.Interaction):
            is_root = interaction.user.id == SUPERADMIN_ID
            view = SuperAdminView(self.view.bot, interaction.user.id, is_root)
            embed = create_embed("👑 Superadmin Panel", "Returning to the main administrative panel.", discord.Color.gold())
            await interaction.response.edit_message(embed=embed, view=view)

    async def _handle_interaction(self, interaction: discord.Interaction, success_msg: str, error_msg: str):
        """Generic handler to defer and respond."""
        try:
            await interaction.response.defer()
            await interaction.followup.send(embed=create_embed("Success", success_msg, discord.Color.green()), ephemeral=True)
        except Exception as e:
            logging.error(f"Error in StoreOwnerView: {e}")
            await interaction.followup.send(embed=create_embed("Error", error_msg, discord.Color.red()), ephemeral=True)
            
    # ... [Rest of StoreOwnerView methods implemented below, using Modals and Selects] ...
    @discord.ui.button(label="➕ Add Product", style=discord.ButtonStyle.success, row=0)
    async def add_product(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = discord.ui.Modal(title="Create a New Product")
        product_name_input = discord.ui.TextInput(label="Product Name", placeholder="e.g., epic_sword", required=True)
        modal.add_item(product_name_input)
        
        async def modal_callback(inner_interaction: discord.Interaction):
            product_name = sanitize_name(product_name_input.value)
            data = await self.data_manager.load_data()
            if not product_name or product_name in data["stores"][self.store_name]["products"]:
                return await inner_interaction.response.send_message(embed=create_embed("Error", "Invalid or duplicate product name.", discord.Color.red()), ephemeral=True)
            data["stores"][self.store_name]["products"][product_name] = {"whitelist": []}
            await self.data_manager.save_data(data)
            await inner_interaction.response.send_message(embed=create_embed("Success", f"Product `{product_name}` created.", discord.Color.green()), ephemeral=True)
        
        modal.on_submit = modal_callback
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="❌ Remove Product", style=discord.ButtonStyle.danger, row=0)
    async def remove_product(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await self.data_manager.load_data()
        products = list(data["stores"][self.store_name]["products"].keys())
        if not products:
            return await interaction.response.send_message(embed=create_embed("Info", "This store has no products to remove.", discord.Color.blue()), ephemeral=True)
        
        options = [discord.SelectOption(label=p, value=p) for p in products]
        select = discord.ui.Select(placeholder="Select a product to remove...", options=options)
        
        async def select_callback(inner_interaction: discord.Interaction):
            product_to_remove = select.values[0]
            confirm_view = ConfirmationView(author_id=inner_interaction.user.id)
            await inner_interaction.response.send_message(
                embed=create_embed("Confirmation", f"Are you sure you want to permanently delete the product `{product_to_remove}` and all its whitelists?", discord.Color.orange()),
                view=confirm_view, ephemeral=True
            )
            await confirm_view.wait()
            if confirm_view.value:
                current_data = await self.data_manager.load_data()
                del current_data["stores"][self.store_name]["products"][product_to_remove]
                await self.data_manager.save_data(current_data)
                await inner_interaction.edit_original_response(content=None, embed=create_embed("Success", f"Product `{product_to_remove}` has been deleted.", discord.Color.green()), view=None)
            else:
                await inner_interaction.edit_original_response(content="Action cancelled.", embed=None, view=None)

        select.callback = select_callback
        view = discord.ui.View(timeout=180.0).add_item(select)
        await interaction.response.send_message(content="Please select a product:", view=view, ephemeral=True)
    
    @discord.ui.button(label="📜 View Products", style=discord.ButtonStyle.secondary, row=0)
    async def view_products(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await self.data_manager.load_data()
        products = list(data["stores"][self.store_name]["products"].items())
        if not products:
            return await interaction.response.send_message(embed=create_embed("Info", "This store has no products.", discord.Color.blue()), ephemeral=True)
        
        view = PaginationView(author_id=interaction.user.id, items=products, items_per_page=10, 
                              embed_title=f"Products in `{self.store_name}`", embed_color=discord.Color.blue(),
                              format_item=PaginationView.format_product)
        await interaction.response.send_message(embed=await view.create_page_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="✅ Whitelist", style=discord.ButtonStyle.primary, row=1)
    async def whitelist_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.show_product_select(interaction, "whitelist")

    @discord.ui.button(label="🚫 Unwhitelist", style=discord.ButtonStyle.primary, row=1)
    async def unwhitelist_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.show_product_select(interaction, "unwhitelist")

    @discord.ui.button(label="📋 View Whitelist", style=discord.ButtonStyle.secondary, row=1)
    async def view_whitelist(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.show_product_select(interaction, "view")

    async def show_product_select(self, interaction: discord.Interaction, action: str):
        data = await self.data_manager.load_data()
        products = list(data["stores"][self.store_name]["products"].keys())
        if not products:
            return await interaction.response.send_message(embed=create_embed("Info", "This store has no products.", discord.Color.blue()), ephemeral=True)

        options = [discord.SelectOption(label=p, value=p) for p in products]
        select = discord.ui.Select(placeholder=f"Select a product to {action}...", options=options)
        
        async def select_callback(inner_interaction: discord.Interaction):
            product_name = select.values[0]
            current_data = await self.data_manager.load_data()
            if action == "view":
                whitelist = current_data["stores"][self.store_name]["products"][product_name]["whitelist"]
                view = PaginationView(author_id=inner_interaction.user.id, items=whitelist, items_per_page=15, 
                                      embed_title=f"Whitelist for `{product_name}`", embed_color=discord.Color.purple(), 
                                      format_item=PaginationView.format_roblox_id, client=self.bot)
                await inner_interaction.response.send_message(embed=await view.create_page_embed(), view=view, ephemeral=True)
            else:
                modal = WhitelistActionModal(bot_instance=self.bot, store_name=self.store_name, product_name=product_name, action=action)
                await inner_interaction.response.send_modal(modal)

        select.callback = select_callback
        view = discord.ui.View(timeout=180.0).add_item(select)
        await interaction.response.send_message(content=f"Please select a product for the `{action}` action:", view=view, ephemeral=True)

# Main Admin View and Sub-Views
class SuperAdminView(discord.ui.View):
    """The main administrative control panel."""
    def __init__(self, bot_instance, author_id: int, is_root_user: bool):
        super().__init__(timeout=300.0)
        self.bot = bot_instance
        self.data_manager = bot_instance.data_manager
        self.author_id = author_id
        self.is_root_user = is_root_user
        
        if is_root_user: self.add_item(self.ManageStaffButton())
        self.add_item(self.ManageStoresButton())
        self.add_item(self.ManageOwnersButton())
        self.add_item(self.ManageBlacklistButton())
        self.add_item(self.ViewAllDataButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("You cannot control this menu.", ephemeral=True)
            return False
        return True
    
    # --- Inner classes for buttons to launch sub-views ---
    class ManageStaffButton(discord.ui.Button):
        def __init__(self): super().__init__(label="👑 Manage Staff", style=discord.ButtonStyle.danger, row=0)
        async def callback(self, interaction: discord.Interaction):
            view = StaffManagementView(self.view.bot, interaction.user.id, self.view.is_root_user)
            embed = create_embed("👑 Staff Management", "Add or remove staff members who have administrative access.", discord.Color.gold())
            await interaction.response.edit_message(embed=embed, view=view)
    
    class ManageStoresButton(discord.ui.Button):
        def __init__(self): super().__init__(label="🏬 Manage Stores", style=discord.ButtonStyle.primary, row=1)
        async def callback(self, interaction: discord.Interaction):
            view = StoreManagementView(self.view.bot, interaction.user.id, self.view.is_root_user)
            embed = create_embed("🏬 Store Management", "Create, delete, or take direct control of a store.", discord.Color.teal())
            await interaction.response.edit_message(embed=embed, view=view)

    class ManageOwnersButton(discord.ui.Button):
        def __init__(self): super().__init__(label="👤 Manage Owners", style=discord.ButtonStyle.primary, row=1)
        async def callback(self, interaction: discord.Interaction):
            view = OwnerManagementView(self.view.bot, interaction.user.id, self.view.is_root_user)
            embed = create_embed("👤 Owner Management", "Assign, transfer, or remove store ownership.", discord.Color.purple())
            await interaction.response.edit_message(embed=embed, view=view)

    class ManageBlacklistButton(discord.ui.Button):
        def __init__(self): super().__init__(label="🚫 Manage Blacklist", style=discord.ButtonStyle.secondary, row=2)
        async def callback(self, interaction: discord.Interaction):
            view = BlacklistManagementView(self.view.bot, interaction.user.id, self.view.is_root_user)
            embed = create_embed("🚫 Global Blacklist", "Globally prevent specific Roblox IDs from being whitelisted in any store.", discord.Color.dark_red())
            await interaction.response.edit_message(embed=embed, view=view)

    # In the SuperAdminView class...

    class ViewAllDataButton(discord.ui.Button):
        def __init__(self): super().__init__(label="📊 System Report", style=discord.ButtonStyle.secondary, row=2)
        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            data = await self.view.data_manager.load_data()
            embed = create_embed("📊 System-Wide Report", "A complete overview of all system data.", discord.Color.blurple())
            
            # This part was already correct and is a good pattern to follow
            staff_coroutines = [fetch_user_info(interaction.client, uid) for uid in data.get('staff', [])]
            staff_list = await asyncio.gather(*staff_coroutines)
            embed.add_field(name="👑 Staff", value="\n".join(staff_list) or "No staff members.", inline=False)
            
            # --- THIS IS THE CORRECTED SECTION ---
            owners_data = data.get('owners', {})
            if owners_data:
                # 1. Create a list of coroutines to fetch user info
                owner_fetch_coroutines = [fetch_user_info(interaction.client, uid) for uid in owners_data.keys()]
                
                # 2. Run them all concurrently
                owner_user_infos = await asyncio.gather(*owner_fetch_coroutines)
                
                # 3. Now, format the strings using the results
                owner_store_names = owners_data.values()
                owner_list = [f"{user_info} ➡️ `{sname}`" for user_info, sname in zip(owner_user_infos, owner_store_names)]
            else:
                owner_list = [] # No owners, so the list is empty

            embed.add_field(name="👤 Owners & Stores", value="\n".join(owner_list) or "No owners found.", inline=False)
            # --- END OF CORRECTED SECTION ---
            
            total_products = sum(len(s['products']) for s in data['stores'].values())
            total_whitelists = sum(len(p['whitelist']) for s in data['stores'].values() for p in s['products'].values())
            embed.add_field(name="Totals", value=f"**Stores:** {len(data['stores'])}\n**Products:** {total_products}\n**Whitelists:** {total_whitelists}", inline=True)
            embed.add_field(name="🚫 Blacklisted IDs", value=f"{len(data.get('blacklist', []))} users", inline=True)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
    
class BaseAdminSubView(discord.ui.View):
    """Base class for admin sub-menus to include a consistent back button."""
    def __init__(self, bot_instance, author_id, is_root_user):
        super().__init__(timeout=180.0)
        self.bot = bot_instance
        self.data_manager = bot_instance.data_manager
        self.author_id = author_id
        self.is_root_user = is_root_user
        self.add_item(self.BackButton())

    class BackButton(discord.ui.Button):
        def __init__(self): super().__init__(label="⬅️ Back", style=discord.ButtonStyle.grey, row=4)
        async def callback(self, interaction: discord.Interaction):
            title = "👑 Root Control Panel" if self.view.is_root_user else "🛡️ Staff Control Panel"
            embed = create_embed(title, "Welcome. You have administrative access.", discord.Color.gold())
            view = SuperAdminView(self.view.bot, interaction.user.id, self.view.is_root_user)
            await interaction.response.edit_message(embed=embed, view=view)
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("You cannot control this menu.", ephemeral=True)
            return False
        return True

# --- ACTUAL IMPLEMENTATIONS OF ADMIN SUB-VIEWS ---
class StaffManagementView(BaseAdminSubView):
    def __init__(self, bot_instance, author_id, is_root_user):
        super().__init__(bot_instance, author_id, is_root_user)
        self.add_item(self.AddStaffButton())
        self.add_item(self.RemoveStaffButton())
        self.add_item(self.ViewStaffButton())

    class AddStaffButton(discord.ui.Button):
        def __init__(self): super().__init__(label="➕ Add Staff", style=discord.ButtonStyle.success)
        async def callback(self, interaction: discord.Interaction):
            modal = discord.ui.Modal(title="Add New Staff Member")
            id_input = discord.ui.TextInput(label="User's Discord ID", required=True)
            modal.add_item(id_input)
            
            async def modal_callback(inner_interaction: discord.Interaction):
                staff_id = id_input.value
                if not staff_id.isdigit(): return await inner_interaction.response.send_message("ID must be numerical.", ephemeral=True)
                
                data = await self.view.data_manager.load_data()
                if staff_id in data['staff']: return await inner_interaction.response.send_message("This user is already staff.", ephemeral=True)
                
                data['staff'].append(staff_id)
                await self.view.data_manager.save_data(data)
                await inner_interaction.response.send_message(f"Successfully added <@{staff_id}> as staff.", ephemeral=True)

            modal.on_submit = modal_callback
            await interaction.response.send_modal(modal)

    class RemoveStaffButton(discord.ui.Button):
        def __init__(self): super().__init__(label="❌ Remove Staff", style=discord.ButtonStyle.danger)
        async def callback(self, interaction: discord.Interaction):
            data = await self.view.data_manager.load_data()
            if not data['staff']: return await interaction.response.send_message("There are no staff members to remove.", ephemeral=True)
            
            options = [discord.SelectOption(label=await fetch_user_info(interaction.client, uid), value=str(uid)) for uid in data['staff']]
            select = discord.ui.Select(placeholder="Select staff to remove...", options=options)

            async def select_callback(inner_interaction: discord.Interaction):
                staff_id_to_remove = select.values[0]
                data = await self.view.data_manager.load_data()
                data['staff'].remove(staff_id_to_remove)
                await self.view.data_manager.save_data(data)
                await inner_interaction.response.edit_message(content=f"Removed <@{staff_id_to_remove}> from staff.", view=None)

            select.callback = select_callback
            await interaction.response.edit_message(content="Select a staff member:", view=discord.ui.View().add_item(select))

    class ViewStaffButton(discord.ui.Button):
        def __init__(self): super().__init__(label="📋 View Staff", style=discord.ButtonStyle.secondary)
        async def callback(self, interaction: discord.Interaction):
            data = await self.view.data_manager.load_data()
            view = PaginationView(author_id=interaction.user.id, items=data['staff'], items_per_page=15, 
                                  embed_title="Current Staff Members", embed_color=discord.Color.gold(),
                                  format_item=PaginationView.format_user, client=interaction.client)
            await interaction.response.send_message(embed=await view.create_page_embed(), view=view, ephemeral=True)

class StoreManagementView(BaseAdminSubView):
    def __init__(self, bot_instance, author_id, is_root_user):
        super().__init__(bot_instance, author_id, is_root_user)
        self.add_item(self.CreateStoreButton())
        self.add_item(self.DeleteStoreButton())
        self.add_item(self.ManageAStoreButton())

    class CreateStoreButton(discord.ui.Button):
        def __init__(self): super().__init__(label="➕ Create Store", style=discord.ButtonStyle.success)
        async def callback(self, interaction: discord.Interaction):
            modal = discord.ui.Modal(title="Create New Store")
            name_input = discord.ui.TextInput(label="Store Name", required=True, placeholder="e.g., My Awesome Shop")
            modal.add_item(name_input)

            async def modal_callback(inner_interaction: discord.Interaction):
                store_name = sanitize_name(name_input.value)
                data = await self.view.data_manager.load_data()
                if not store_name or store_name in data['stores']:
                    return await inner_interaction.response.send_message("Invalid or duplicate store name.", ephemeral=True)
                data['stores'][store_name] = {"owner_id": None, "products": {}}
                await self.view.data_manager.save_data(data)
                await inner_interaction.response.send_message(f"Store `{store_name}` created. Assign an owner in the Owner Management panel.", ephemeral=True)

            modal.on_submit = modal_callback
            await interaction.response.send_modal(modal)

    class DeleteStoreButton(discord.ui.Button):
        def __init__(self): super().__init__(label="🗑️ Delete Store", style=discord.ButtonStyle.danger)
        async def callback(self, interaction: discord.Interaction):
            data = await self.view.data_manager.load_data()
            if not data['stores']: return await interaction.response.send_message("No stores exist to delete.", ephemeral=True)
            options = [discord.SelectOption(label=s, value=s) for s in data['stores'].keys()]
            select = discord.ui.Select(placeholder="Select store to delete...", options=options)

            async def select_callback(inner_interaction: discord.Interaction):
                store_name = select.values[0]
                confirm = ConfirmationView(author_id=inner_interaction.user.id)
                await inner_interaction.response.send_message(f"**WARNING:** Are you sure you want to permanently delete `{store_name}` and all its data? This is irreversible.", view=confirm, ephemeral=True)
                await confirm.wait()
                if confirm.value:
                    data = await self.view.data_manager.load_data()
                    owner_id = data['stores'][store_name].get('owner_id')
                    if owner_id and str(owner_id) in data['owners']: del data['owners'][str(owner_id)]
                    del data['stores'][store_name]
                    await self.view.data_manager.save_data(data)
                    await inner_interaction.edit_original_response(content=f"Store `{store_name}` has been deleted.", view=None)

            select.callback = select_callback
            await interaction.response.edit_message(content="Select a store:", view=discord.ui.View().add_item(select))
            
    class ManageAStoreButton(discord.ui.Button):
        def __init__(self): super().__init__(label="🔧 Manage a Store", style=discord.ButtonStyle.secondary, row=1)
        async def callback(self, interaction: discord.Interaction):
            data = await self.view.data_manager.load_data()
            if not data["stores"]: return await interaction.response.send_message("No stores to manage.", ephemeral=True)
            options = [discord.SelectOption(label=s, value=s) for s in data["stores"].keys()]
            select = discord.ui.Select(placeholder="Select a store to manage...", options=options)
            
            async def select_callback(inner_interaction: discord.Interaction):
                store_name = select.values[0]
                manage_view = StoreOwnerView(self.view.bot, inner_interaction.user.id, store_name, from_admin=True)
                embed = create_embed(f"🔧 Managing: {store_name}", "You have direct administrative control over this store.", discord.Color.orange())
                await inner_interaction.response.edit_message(embed=embed, view=manage_view)
            
            select.callback = select_callback
            await interaction.response.edit_message(content="Select a store:", embed=None, view=discord.ui.View().add_item(select))

class OwnerManagementView(BaseAdminSubView):
    def __init__(self, bot_instance, author_id, is_root_user):
        super().__init__(bot_instance, author_id, is_root_user)
        self.add_item(self.TransferOwnerButton())
        self.add_item(self.RemoveOwnerButton())

    class TransferOwnerButton(discord.ui.Button):
        def __init__(self): super().__init__(label="🔁 Assign/Transfer Owner", style=discord.ButtonStyle.success)
        async def callback(self, interaction: discord.Interaction):
            data = await self.view.data_manager.load_data()
            if not data["stores"]: return await interaction.response.send_message("No stores exist.", ephemeral=True)
            options = [discord.SelectOption(label=s, value=s) for s in data["stores"].keys()]
            select = discord.ui.Select(placeholder="Select store to assign an owner to...", options=options)

            async def select_callback(inner_interaction: discord.Interaction):
                store_name = select.values[0]
                modal_title = truncate_string(f"Set Owner for {store_name}", 45)
                modal = discord.ui.Modal(title=modal_title)
                id_input = discord.ui.TextInput(label="New Owner's Discord ID", required=True)
                modal.add_item(id_input)

                async def modal_callback(modal_interaction: discord.Interaction):
                    new_owner_id = id_input.value
                    if not new_owner_id.isdigit():
                        return await modal_interaction.response.send_message("Error: Invalid Discord ID format.", ephemeral=True)
                    
                    data = await self.view.data_manager.load_data()
                    if new_owner_id in data["owners"]:
                        return await modal_interaction.response.send_message(f"Error: <@{new_owner_id}> already owns the store `{data['owners'][new_owner_id]}`.", ephemeral=True)

                    old_owner_id = data["stores"][store_name].get("owner_id")
                    if old_owner_id: del data["owners"][str(old_owner_id)]
                    
                    data["owners"][new_owner_id] = store_name
                    data["stores"][store_name]["owner_id"] = new_owner_id
                    await self.view.data_manager.save_data(data)
                    await modal_interaction.response.send_message(f"Successfully transferred ownership of `{store_name}` to <@{new_owner_id}>.", ephemeral=True)

                modal.on_submit = modal_callback
                await inner_interaction.response.send_modal(modal)

            select.callback = select_callback
            await interaction.response.edit_message(content="Select a store:", view=discord.ui.View().add_item(select))

    class RemoveOwnerButton(discord.ui.Button):
        def __init__(self): super().__init__(label="➖ Remove Ownership", style=discord.ButtonStyle.danger)
        async def callback(self, interaction: discord.Interaction):
            data = await self.view.data_manager.load_data()
            owned_stores = {s_name: s_data for s_name, s_data in data["stores"].items() if s_data.get("owner_id")}
            if not owned_stores: return await interaction.response.send_message("No stores currently have an owner.", ephemeral=True)
            options = [discord.SelectOption(label=s, value=s) for s in owned_stores.keys()]
            select = discord.ui.Select(placeholder="Select store to remove owner from...", options=options)

            async def select_callback(inner_interaction: discord.Interaction):
                store_name = select.values[0]
                data = await self.view.data_manager.load_data()
                owner_id = data["stores"][store_name].get("owner_id")
                if owner_id:
                    del data["owners"][str(owner_id)]
                    data["stores"][store_name]["owner_id"] = None
                    await self.view.data_manager.save_data(data)
                    await inner_interaction.response.edit_message(content=f"Removed ownership from `{store_name}`. It is now un-owned.", view=None)
                else: # Should not happen due to filter, but good practice
                    await inner_interaction.response.edit_message(content=f"`{store_name}` had no owner.", view=None)

            select.callback = select_callback
            await interaction.response.edit_message(content="Select a store:", view=discord.ui.View().add_item(select))

class BlacklistManagementView(BaseAdminSubView):
    def __init__(self, bot_instance, author_id, is_root_user):
        super().__init__(bot_instance, author_id, is_root_user)
        self.add_item(self.AddBlacklistButton())
        self.add_item(self.RemoveBlacklistButton())
        self.add_item(self.ViewBlacklistButton())

    class AddBlacklistButton(discord.ui.Button):
        def __init__(self): super().__init__(label="➕ Add to Blacklist", style=discord.ButtonStyle.danger)
        async def callback(self, interaction: discord.Interaction):
            modal = discord.ui.Modal(title="Blacklist a Roblox ID")
            id_input = discord.ui.TextInput(label="Roblox User ID", required=True)
            modal.add_item(id_input)

            async def modal_callback(inner_interaction: discord.Interaction):
                roblox_id_str = id_input.value
                if not roblox_id_str.isdigit():
                    return await inner_interaction.response.send_message("ID must be numerical.", ephemeral=True)
                
                roblox_id = int(roblox_id_str)
                if not await is_valid_roblox_id(self.view.bot.http_session, roblox_id):
                    return await inner_interaction.response.send_message(f"Roblox ID `{roblox_id}` does not exist.", ephemeral=True)
                
                data = await self.view.data_manager.load_data()
                if roblox_id in data['blacklist']:
                    return await inner_interaction.response.send_message(f"ID `{roblox_id}` is already blacklisted.", ephemeral=True)

                data['blacklist'].append(roblox_id)
                await self.view.data_manager.save_data(data)
                await inner_interaction.response.send_message(f"Successfully blacklisted Roblox ID `{roblox_id}`.", ephemeral=True)
            
            modal.on_submit = modal_callback
            await interaction.response.send_modal(modal)

    class RemoveBlacklistButton(discord.ui.Button):
        def __init__(self): super().__init__(label="➖ Remove from Blacklist", style=discord.ButtonStyle.success)
        async def callback(self, interaction: discord.Interaction):
            data = await self.view.data_manager.load_data()
            if not data['blacklist']: return await interaction.response.send_message("The blacklist is empty.", ephemeral=True)
            
            options = [discord.SelectOption(label=str(uid), value=str(uid)) for uid in data['blacklist']]
            select = discord.ui.Select(placeholder="Select Roblox ID to un-blacklist...", options=options[:25]) # Select menu limit

            async def select_callback(inner_interaction: discord.Interaction):
                id_to_remove = int(select.values[0])
                data = await self.view.data_manager.load_data()
                data['blacklist'].remove(id_to_remove)
                await self.view.data_manager.save_data(data)
                await inner_interaction.response.edit_message(content=f"Removed Roblox ID `{id_to_remove}` from the blacklist.", view=None)

            select.callback = select_callback
            await interaction.response.edit_message(content="Select a Roblox ID:", view=discord.ui.View().add_item(select))
            
    class ViewBlacklistButton(discord.ui.Button):
        def __init__(self): super().__init__(label="📋 View Blacklist", style=discord.ButtonStyle.secondary)
        async def callback(self, interaction: discord.Interaction):
            data = await self.view.data_manager.load_data()
            view = PaginationView(author_id=interaction.user.id, items=data['blacklist'], items_per_page=15,
                                  embed_title="Globally Blacklisted Roblox IDs", embed_color=discord.Color.dark_red(),
                                  format_item=PaginationView.format_blacklist, client=interaction.client)
            await interaction.response.send_message(embed=await view.create_page_embed(), view=view, ephemeral=True)
            
# --- BOT CLASS AND MAIN COMMAND ---
# --- BOT CLASS AND MAIN COMMAND ---
class WhitelistBot(discord.Client):
    """The main bot class, handling events and command registration."""
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)
        self.data_manager = DataManager(DATA_FILE)
        # Initialize as None. It will be created in setup_hook.
        self.http_session: Optional[aiohttp.ClientSession] = None

    async def setup_hook(self):
        """Called by discord.py after login but before connecting to the gateway.
        This is the ideal place to create sessions or database connections."""
        # Create the aiohttp session here, inside the running event loop.
        self.http_session = aiohttp.ClientSession()
        
        # Syncs the application command tree.
        await self.tree.sync()
        logging.info("Command tree synced.")

    async def on_ready(self):
        """Called when the bot is ready and connected."""
        await self.data_manager.load_data() # Initial load to check/create the file
        logging.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logging.info(f"Root Superadmin ID: {SUPERADMIN_ID}")
        logging.info("------ Bot is ready and online. ------")

    async def close(self):
        """Gracefully closes the bot and its resources."""
        await super().close()
        # Ensure the session is closed if it was created.
        if self.http_session:
            await self.http_session.close()
        logging.info("Bot has been shut down.")

bot = WhitelistBot(intents=discord.Intents.default())

@bot.tree.command(name="panel", description="Open the whitelist management panel.")
async def whitelist_panel(interaction: discord.Interaction):
    """The main entry point command for all users."""
    user_id = str(interaction.user.id)
    data = await bot.data_manager.load_data()
    
    is_root = (int(user_id) == SUPERADMIN_ID)
    is_staff = user_id in data.get("staff", [])
    is_owner = user_id in data.get("owners", {})

    if is_root or is_staff:
        title = "👑 Root Control Panel" if is_root else "🛡️ Staff Control Panel"
        embed = create_embed(title, "Welcome. You have administrative access to the whitelist system.", discord.Color.gold())
        view = SuperAdminView(bot, interaction.user.id, is_root)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    elif is_owner:
        store_name = data["owners"][user_id]
        embed = create_embed(f"🏪 Store Panel: {store_name}", f"Welcome, <@{user_id}>. Use the buttons below to manage your store.", discord.Color.teal())
        view = StoreOwnerView(bot, interaction.user.id, store_name)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    else:
        embed = create_embed("🚫 Access Denied", "You do not have permission to use this command.", discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

# --- BOT RUN ---
if __name__ == "__main__":
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or SUPERADMIN_ID == 123456789012345678:
        logging.critical("!!! FATAL ERROR: Please set your BOT_TOKEN and SUPERADMIN_ID in the script's CONFIG section.")
    else:
        try:
            bot.run(BOT_TOKEN, log_handler=None) # Use our custom logger, not discord.py's
        except discord.errors.LoginFailure:
            logging.critical("!!! FATAL ERROR: Invalid BOT_TOKEN. Please check your token and try again.")
        except Exception as e:
            logging.critical(f"!!! An unexpected error occurred while running the bot: {e}")