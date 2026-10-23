"""
Fumi RPG module for the existing Discord bot.
Separate SQLite database: rpg.db (does not modify moderation.db).
Requires discord.py 2.x.
"""
import random
import sqlite3
from datetime import date, datetime, timedelta

import discord
from discord.ext import commands

RPG_DATABASE_FILE = "rpg.db"

# EDIT THESE VALUES so they exactly match the manually created channel names.
RPG_CHANNELS = {
    "menu": "rpg-menu",
    "gacha": "gacha",
    "adventure": "adventure",
    "boss": "boss-hunt",
    "coop": "party-coop",
    "pvp": "pvp-arena",
}

DIFFICULTIES = {
    "basic": {"hp": 1.0, "atk": 1.0, "reward": 1.0, "label": "Basic"},
    "hard": {"hp": 2.5, "atk": 1.8, "reward": 2.0, "label": "Hard"},
    "nightmare": {"hp": 5.0, "atk": 3.0, "reward": 3.5, "label": "Nightmare"},
}

# This is initial balancing data. Secret bosses are beyond Nightmare.
SECRET_BOSSES = {
    "varkhaz": {
        "name": "Varkhaz — The Fallen Sovereign", "hp": 50000, "atk": 1800,
        "drop": "Fragment of the Forgotten Crown", "mechanic": "Sovereign's Guard",
    },
    "noxvyr": {
        "name": "Noxvyr — The Abyssal Devourer", "hp": 65000, "atk": 2200,
        "drop": "Noxvyr Relic", "mechanic": "Abyssal Devour",
    },
    "eclipsara": {
        "name": "Eclipsara — The Last Eclipse", "hp": 80000, "atk": 2600,
        "drop": "Eternal Night Core", "mechanic": "Eclipse Phase",
    },
}

BANNERS = {
    "coin": {
        "name": "Common Banner", "currency": "gold_coin", "display_currency": "Gold Coin",
        "cost": 100, "rarity": "Common",
        "characters": [("Iron Vanguard", "Warrior"), ("Apprentice Mage", "Mage"),
                       ("Forest Scout", "Archer"), ("Field Medic", "Healer")],
    },
    "mana": {
        "name": "Rare Banner", "currency": "mana_crystal", "display_currency": "Mana Crystal",
        "cost": 1, "rarity": "Rare",
        "characters": [("Frostblade", "Warrior"), ("Astral Mage", "Mage"),
                       ("Phantom Huntress", "Archer"), ("Moon Cleric", "Healer")],
    },
    "orb": {
        "name": "Epic Banner", "currency": "summoning_orb", "display_currency": "Summoning Orb",
        "cost": 1, "rarity": "Epic",
        "characters": [("Dawn Saint", "Healer"), ("Crimson Reaper", "Assassin"),
                       ("Storm Sovereign", "Mage"), ("Obsidian Knight", "Warrior")],
    },
    "void": {
        "name": "Secret Banner", "currency": "void_seal", "display_currency": "Void Seal",
        "cost": 1, "rarity": "Secret",
        "characters": [("Abyssal Warden", "Warrior"), ("Eclipse Oracle", "Mage"),
                       ("Void Stalker", "Assassin")],
    },
}

# Base combat templates. Shared formula keeps code maintainable.
MONSTERS = {
    "slime": {"name": "Cave Slime", "hp": 120, "atk": 12, "def": 3, "exp": 25, "gold": 20},
    "goblin": {"name": "Goblin Raider", "hp": 220, "atk": 22, "def": 7, "exp": 45, "gold": 35},
    "wolf": {"name": "Shadow Wolf", "hp": 360, "atk": 34, "def": 12, "exp": 70, "gold": 55},
    "knight": {"name": "Fallen Knight", "hp": 750, "atk": 65, "def": 25, "exp": 140, "gold": 110},
    "wraith": {"name": "Nightmare Wraith", "hp": 1300, "atk": 105, "def": 45, "exp": 260, "gold": 220},
}
MONSTER_BY_DIFFICULTY = {
    "basic": ["slime", "goblin"],
    "hard": ["goblin", "wolf", "knight"],
    "nightmare": ["knight", "wraith"],
}

CLASSES = {
    "Warrior": {"hp": 150, "mp": 35, "atk": 24, "def": 16, "skill": "Power Strike"},
    "Mage": {"hp": 90, "mp": 100, "atk": 32, "def": 7, "skill": "Arcane Burst"},
    "Archer": {"hp": 110, "mp": 60, "atk": 28, "def": 10, "skill": "Piercing Shot"},
    "Healer": {"hp": 120, "mp": 90, "atk": 17, "def": 12, "skill": "Radiant Mend"},
    "Assassin": {"hp": 100, "mp": 65, "atk": 35, "def": 8, "skill": "Shadow Strike"},
}

CLASS_EQUIPMENT = {
 "Warrior":[("Recruit Sword","weapon","Basic",12,0,0),("Iron Guard","armor","Basic",0,90,8),("Bronze Cleaver","weapon","Basic",18,0,0),("Patrol Mail","armor","Basic",0,130,12),("Lionheart Edge","weapon","Rare",55,0,0),("Vanguard Plate","armor","Rare",0,420,35),("War Drum Axe","weapon","Rare",70,0,0),("Crimson Oath","weapon","Epic",180,0,0),("Bastion of Dawn","armor","Epic",0,1500,110),("Titanbreaker","weapon","Epic",220,0,0),("Worldsplitter","weapon","Mythic",520,0,0),("Aegis of the First King","armor","Mythic",0,5000,360)],
 "Mage":[("Apprentice Wand","weapon","Basic",14,0,0),("Novice Robe","armor","Basic",0,65,5),("Ember Staff","weapon","Basic",20,0,0),("Runic Mantle","armor","Basic",0,100,8),("Frostweave Rod","weapon","Rare",60,0,0),("Astral Vestment","armor","Rare",0,350,25),("Stormcall Scepter","weapon","Rare",76,0,0),("Cometbinder","weapon","Epic",190,0,0),("Voidthread Robe","armor","Epic",0,1250,85),("Archon's Focus","weapon","Epic",230,0,0),("Starfall Grimoire","weapon","Mythic",550,0,0),("Mantle of the Cosmos","armor","Mythic",0,4200,300)],
 "Archer":[("Hunting Bow","weapon","Basic",13,0,0),("Scout Leathers","armor","Basic",0,80,6),("Reed Longbow","weapon","Basic",19,0,0),("Windrunner Vest","armor","Basic",0,115,9),("Falconstring","weapon","Rare",58,0,0),("Moontrail Garb","armor","Rare",0,380,28),("Piercing Yew","weapon","Rare",74,0,0),("Tempest Bow","weapon","Epic",185,0,0),("Nightstalker Cuirass","armor","Epic",0,1350,95),("Skybreaker Recurve","weapon","Epic",225,0,0),("Worldroot Bow","weapon","Mythic",530,0,0),("Cloak of the Last Hunt","armor","Mythic",0,4400,310)],
 "Healer":[("Pilgrim Mace","weapon","Basic",9,0,0),("Acolyte Vestments","armor","Basic",0,100,8),("Dawnwood Staff","weapon","Basic",15,0,0),("Sanctuary Cape","armor","Basic",0,140,12),("Mercy Rod","weapon","Rare",42,0,0),("Lifebloom Robe","armor","Rare",0,450,32),("Sunlit Crook","weapon","Rare",55,0,0),("Seraphic Scepter","weapon","Epic",150,0,0),("Sanctum Aegis","armor","Epic",0,1600,120),("Grace of Sol","weapon","Epic",180,0,0),("Dawn Eternal","weapon","Mythic",420,0,0),("Raiment of the First Saint","armor","Mythic",0,5200,380)],
 "Assassin":[("Rookie Daggers","weapon","Basic",16,0,0),("Duskrunner Wraps","armor","Basic",0,70,5),("Blacksteel Knife","weapon","Basic",22,0,0),("Silentstep Vest","armor","Basic",0,105,8),("Phantom Fang","weapon","Rare",68,0,0),("Shadeweave Armor","armor","Rare",0,330,22),("Venomkiss","weapon","Rare",82,0,0),("Red Eclipse","weapon","Epic",205,0,0),("Umbral Carapace","armor","Epic",0,1200,80),("Soulpiercer","weapon","Epic",245,0,0),("Last Whisper","weapon","Mythic",580,0,0),("Mantle of the Unseen King","armor","Mythic",0,4000,280)]
}
EQUIPMENT_SHOP = {"Recruit Sword":180,"Iron Guard":220,"Bronze Cleaver":260,"Apprentice Wand":180,"Novice Robe":200,"Hunting Bow":190,"Scout Leathers":210,"Pilgrim Mace":160,"Acolyte Vestments":210,"Rookie Daggers":200,"Duskrunner Wraps":190}
EQUIPMENT_GACHA_COST = 250
EQUIPMENT_GACHA_ODDS = (("Basic",50),("Rare",27),("Epic",18),("Mythic",5))
FIELD_BOSSES = {
 "basic1":{"name":"Mossfang, Raja Rimba","difficulty":"Basic","hp":550,"atk":32,"def":12,"exp":100,"gold":120,"drop":"Mossfang Hide Armor","chance":0.35},
 "basic2":{"name":"Golem Penjaga Reruntuhan","difficulty":"Basic","hp":780,"atk":38,"def":18,"exp":140,"gold":160,"drop":"Runestone Blade","chance":0.30},
 "hard1":{"name":"Dreadfang Alpha","difficulty":"Hard","hp":2600,"atk":125,"def":45,"exp":500,"gold":500,"drop":"Dreadfang Mantle","chance":0.25},
 "hard2":{"name":"Ironmaw, Colossus Perang","difficulty":"Hard","hp":3400,"atk":145,"def":65,"exp":650,"gold":650,"drop":"Ironmaw Greatsword","chance":0.22},
 "nightmare1":{"name":"Abyssal Drake, Pemakan Cahaya","difficulty":"Nightmare","hp":9500,"atk":320,"def":110,"exp":1800,"gold":1800,"drop":"Abyssal Drakeplate","chance":0.12}
}
LIMITED_EQUIPMENT = {
 "Mossfang Hide Armor":("armor","Limited",0,320,24),"Runestone Blade":("weapon","Limited",95,0,0),
 "Dreadfang Mantle":("armor","Limited",0,1100,85),"Ironmaw Greatsword":("weapon","Limited",260,0,0),
 "Abyssal Drakeplate":("armor","Limited",0,3800,260)
}

SECRET_CLASS = "The Night Ruler"

# Statistik bertambah otomatis setiap level. Angka ini adalah bonus per level
# di atas level 1; statistik dasar tetap mengikuti class yang dipilih.
STAT_GROWTH = {"hp": 12, "mp": 5, "atk": 2, "def": 1}

def stats_for_level(class_name, level):
    base = CLASSES.get(class_name, CLASSES["Warrior"])
    steps = max(0, int(level) - 1)
    return {
        "hp": base["hp"] + steps * STAT_GROWTH["hp"],
        "mp": base["mp"] + steps * STAT_GROWTH["mp"],
        "atk": base["atk"] + steps * STAT_GROWTH["atk"],
        "def": base["def"] + steps * STAT_GROWTH["def"],
    }

def sync_player_stats(user_id, *, refill=True):
    """Recalculate max stats from the saved class/level without resetting progress."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT level, class_name, hp, mp FROM rpg_players WHERE user_id=?",
            (str(user_id),)
        ).fetchone()
        if not row:
            return None
        level, class_name, old_hp, old_mp = row
        stats = stats_for_level(class_name, level)
        hp = stats["hp"] if refill else min(old_hp, stats["hp"])
        mp = stats["mp"] if refill else min(old_mp, stats["mp"])
        conn.execute(
            "UPDATE rpg_players SET hp=?, mp=?, atk=?, defense=? WHERE user_id=?",
            (hp, mp, stats["atk"], stats["def"], str(user_id))
        )
    return stats

def get_connection():
    return sqlite3.connect(RPG_DATABASE_FILE, timeout=10)

def setup_rpg_database():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_players (
                user_id TEXT PRIMARY KEY, username TEXT NOT NULL,
                level INTEGER NOT NULL DEFAULT 1, exp INTEGER NOT NULL DEFAULT 0,
                gold_coin INTEGER NOT NULL DEFAULT 500,
                mana_crystal INTEGER NOT NULL DEFAULT 2,
                summoning_orb INTEGER NOT NULL DEFAULT 1,
                void_seal INTEGER NOT NULL DEFAULT 0,
                class_name TEXT NOT NULL DEFAULT 'Warrior',
                hp INTEGER NOT NULL DEFAULT 150, mp INTEGER NOT NULL DEFAULT 35,
                atk INTEGER NOT NULL DEFAULT 24, defense INTEGER NOT NULL DEFAULT 16,
                wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0,
                last_daily TEXT
            )
        """)
        # Safe schema upgrades for users with the earlier prototype rpg.db.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(rpg_players)")}
        upgrades = {
            "class_name": "TEXT NOT NULL DEFAULT 'Warrior'", "hp": "INTEGER NOT NULL DEFAULT 150",
            "mp": "INTEGER NOT NULL DEFAULT 35", "atk": "INTEGER NOT NULL DEFAULT 24",
            "defense": "INTEGER NOT NULL DEFAULT 16", "wins": "INTEGER NOT NULL DEFAULT 0",
            "losses": "INTEGER NOT NULL DEFAULT 0",
        }
        for col, declaration in upgrades.items():
            if col not in cols:
                conn.execute(f"ALTER TABLE rpg_players ADD COLUMN {col} {declaration}")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
                name TEXT NOT NULL, role TEXT NOT NULL, rarity TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1, shards INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_gacha_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
                banner TEXT NOT NULL, character_name TEXT NOT NULL,
                rarity TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_boss_progress (
                user_id TEXT PRIMARY KEY, varkhaz INTEGER NOT NULL DEFAULT 0,
                noxvyr INTEGER NOT NULL DEFAULT 0, eclipsara INTEGER NOT NULL DEFAULT 0,
                trial_complete INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_pvp_stats (
                user_id TEXT PRIMARY KEY, rating INTEGER NOT NULL DEFAULT 1000
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_boss_inventory (
                user_id TEXT NOT NULL, item_key TEXT NOT NULL, quantity INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(user_id, item_key)
            )
        """)

        conn.execute("""CREATE TABLE IF NOT EXISTS rpg_equipment_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, item_name TEXT NOT NULL,
            slot TEXT NOT NULL, rarity TEXT NOT NULL, atk_bonus INTEGER NOT NULL DEFAULT 0,
            hp_bonus INTEGER NOT NULL DEFAULT 0, def_bonus INTEGER NOT NULL DEFAULT 0,
            class_name TEXT NOT NULL DEFAULT 'Any', bound INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'gacha', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS rpg_equipment_loadout (
            user_id TEXT NOT NULL, slot TEXT NOT NULL, item_id INTEGER,
            PRIMARY KEY(user_id, slot))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS rpg_trade_offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, from_user TEXT NOT NULL, to_user TEXT NOT NULL,
            item_id INTEGER NOT NULL, gold_amount INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_rpg_characters_user ON rpg_characters(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rpg_history_user ON rpg_gacha_history(user_id)")

def ensure_player(user_id, username):
    uid = str(user_id)
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO rpg_players (user_id, username) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username=excluded.username
        """, (uid, username))
        row = conn.execute("""
            SELECT user_id, username, level, exp, gold_coin, mana_crystal,
                   summoning_orb, void_seal, class_name, hp, mp, atk, defense,
                   wins, losses, last_daily
            FROM rpg_players WHERE user_id=?
        """, (uid,)).fetchone()
        conn.execute("INSERT OR IGNORE INTO rpg_boss_progress (user_id) VALUES (?)", (uid,))
        conn.execute("INSERT OR IGNORE INTO rpg_pvp_stats (user_id) VALUES (?)", (uid,))
    return row

def get_characters(user_id):
    with get_connection() as conn:
        return conn.execute("""
            SELECT name, role, rarity, quantity, shards FROM rpg_characters
            WHERE user_id=? ORDER BY
                CASE rarity WHEN 'Secret' THEN 1 WHEN 'Epic' THEN 2
                WHEN 'Rare' THEN 3 ELSE 4 END, name COLLATE NOCASE
        """, (str(user_id),)).fetchall()


def equipment_stats(user_id):
    with get_connection() as conn:
        rows = conn.execute("SELECT e.atk_bonus,e.hp_bonus,e.def_bonus FROM rpg_equipment_loadout l JOIN rpg_equipment_inventory e ON e.id=l.item_id WHERE l.user_id=?", (str(user_id),)).fetchall()
    return tuple(sum(row[i] for row in rows) for i in range(3))

def add_equipment(user_id, item, class_name="Any", bound=0, source="gacha"):
    name, slot, rarity, atk, hp, defense = item
    with get_connection() as conn:
        cur = conn.execute("INSERT INTO rpg_equipment_inventory(user_id,item_name,slot,rarity,atk_bonus,hp_bonus,def_bonus,class_name,bound,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (str(user_id),name,slot,rarity,atk,hp,defense,class_name,int(bound),source))
        return cur.lastrowid

def owned_equipment(user_id):
    with get_connection() as conn:
        return conn.execute("SELECT id,item_name,slot,rarity,atk_bonus,hp_bonus,def_bonus,class_name,bound,source FROM rpg_equipment_inventory WHERE user_id=? ORDER BY id", (str(user_id),)).fetchall()

def equipment_item_by_name(name):
    return next((item for pool in CLASS_EQUIPMENT.values() for item in pool if item[0].casefold()==name.casefold()), None)

def gain_exp(user_id, amount):
    with get_connection() as conn:
        row = conn.execute("SELECT level, exp FROM rpg_players WHERE user_id=?", (str(user_id),)).fetchone()
        if not row:
            return None
        level, exp = row
        exp += amount
        gained = 0
        while exp >= level * 100:
            exp -= level * 100
            level += 1
            gained += 1
        conn.execute("UPDATE rpg_players SET level=?, exp=? WHERE user_id=?", (level, exp, str(user_id)))
        if gained:
            stats = stats_for_level(
                conn.execute("SELECT class_name FROM rpg_players WHERE user_id=?", (str(user_id),)).fetchone()[0],
                level,
            )
            conn.execute(
                "UPDATE rpg_players SET hp=?, mp=?, atk=?, defense=? WHERE user_id=?",
                (stats["hp"], stats["mp"], stats["atk"], stats["def"], str(user_id)),
            )
        return level, exp, gained

def channel_for(ctx, key):
    name = RPG_CHANNELS.get(key, "")
    if not ctx.guild:
        return None
    return discord.utils.get(ctx.guild.text_channels, name=name)

async def rpg_send(ctx, key, content=None, *, embed=None, view=None):
    channel = channel_for(ctx, key)
    target = channel or ctx.channel
    await target.send(content=content, embed=embed, view=view)

def scaled_monster(key, difficulty):
    base = MONSTERS[key]
    mult = DIFFICULTIES[difficulty]
    return {
        **base,
        "hp": int(base["hp"] * mult["hp"]),
        "atk": int(base["atk"] * mult["atk"]),
        "def": int(base["def"] * mult["hp"]),
        "exp": int(base["exp"] * mult["reward"]),
        "gold": int(base["gold"] * mult["reward"]),
    }

class AdventureView(discord.ui.View):
    def __init__(self, author, monster, difficulty):
        super().__init__(timeout=180)
        self.author_id = author.id
        self.monster = monster.copy()
        self.difficulty = difficulty
        self.hp = None
        self.max_hp = None
        self.mp = None
        self.max_mp = None
        self.player = None
        # Bonus equipment harus tersedia sebelum aksi pertarungan diproses.
        self.gear_atk = 0
        self.gear_hp = 0
        self.gear_def = 0
        self.finished = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Pertarungan ini milik pemain lain.", ephemeral=True)
            return False
        return True

    async def start(self):
        self.player = ensure_player(self.author_id, "player")
        self.gear_atk, self.gear_hp, self.gear_def = equipment_stats(self.author_id)
        self.max_hp = self.player[9] + self.gear_hp
        self.max_mp = self.player[10]
        self.hp, self.mp = self.max_hp, self.max_mp

    def disable_all_items(self):
        """Disable every Adventure button when the fight ends."""
        for item in self.children:
            item.disabled = True

    async def update_fight(self, interaction, action):
        # Reply to Discord immediately so the interaction does not expire while
        # SQLite or combat calculations are running.
        if self.finished:
            await interaction.response.send_message("Pertarungan sudah selesai.", ephemeral=True)
            return
        if action == "skill" and self.mp < 15:
            await interaction.response.send_message("MP tidak cukup untuk memakai skill.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            player = ensure_player(self.author_id, str(interaction.user))
            level, atk, defense = player[2], player[11] + self.gear_atk, player[12] + self.gear_def

            if action == "skill":
                self.mp -= 15
                damage = max(1, int(atk * (2.0 + level * 0.04) - self.monster["def"] * 0.35))
            elif action == "attack":
                damage = max(1, int(atk + level * 2 - self.monster["def"] * 0.25))
            else:  # Bertahan/Pulih
                self.hp = min(self.max_hp, self.hp + max(10, defense * 2))
                damage = 0

            self.monster["hp"] -= damage
            if self.monster["hp"] <= 0:
                self.finished = True
                reward_exp, reward_gold = self.monster["exp"], self.monster["gold"]
                gain_exp(self.author_id, reward_exp)
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE rpg_players SET gold_coin=gold_coin+?, wins=wins+1 WHERE user_id=?",
                        (reward_gold, str(self.author_id)),
                    )
                self.disable_all_items()
                await interaction.edit_original_response(
                    content=(f"🏆 **Menang!** {self.monster['name']} dikalahkan.\n"
                             f"Hadiah: **{reward_exp} EXP** dan **{reward_gold} Gold Coin**.\n"
                             f"HP tersisa: {self.hp}/{self.max_hp} · MP: {self.mp}/{self.max_mp}"),
                    view=self,
                )
                return

            incoming = max(1, int(self.monster["atk"] - defense * 0.4))
            # Bertahan/Pulih reduces incoming damage for this turn.
            if action == "heal":
                incoming = max(1, incoming // 2)
            self.hp -= incoming

            if self.hp <= 0:
                self.finished = True
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE rpg_players SET losses=losses+1 WHERE user_id=?",
                        (str(self.author_id),),
                    )
                self.disable_all_items()
                await interaction.edit_original_response(
                    content=(f"💀 **Kalah!** {self.monster['name']} masih memiliki {self.monster['hp']} HP.\n"
                             "Gunakan `!profile` untuk melihat statistik dan coba lagi setelah level-up."),
                    view=self,
                )
                return

            for item in self.children:
                item.disabled = False
            await interaction.edit_original_response(
                content=(f"⚔️ **Melawan {self.monster['name']}** · Kesulitan **{self.difficulty.title()}**\n"
                         f"Monster HP: **{self.monster['hp']}** · ATK: **{self.monster['atk']}**\n"
                         f"HP kamu: **{self.hp}/{self.max_hp}** · MP: **{self.mp}/{self.max_mp}**\n"
                         f"Aksi terakhir: {action.title()} menghasilkan **{damage} damage**."
                         + (f" Monster menyerang balik sebesar **{incoming}** damage." if action != "heal" else f" Kamu bertahan dan menerima **{incoming}** damage.")),
                view=self,
            )
        except Exception as exc:
            # Log the actual error in the hosting console and give the player
            # a visible response instead of leaving the interaction spinning.
            print(f"[Fumi RPG] Adventure action error ({action}): {exc!r}")
            try:
                await interaction.edit_original_response(
                    content="⚠️ Terjadi error saat memproses aksi. Coba mulai ulang dengan `!adventure basic`. Admin bisa memeriksa Console FadeHost.",
                    view=self,
                )
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Serang", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def attack_button(self, interaction, button):
        await self.update_fight(interaction, "attack")

    @discord.ui.button(label="Skill", style=discord.ButtonStyle.danger, emoji="✨")
    async def skill_button(self, interaction, button):
        await self.update_fight(interaction, "skill")

    @discord.ui.button(label="Bertahan/Pulih", style=discord.ButtonStyle.success, emoji="🛡️")
    async def heal_button(self, interaction, button):
        await self.update_fight(interaction, "heal")

class SecretBossView(discord.ui.View):
    """Turn-based solo or co-op Secret Boss battle. Rewards are granted once on victory."""
    def __init__(self, boss_key, boss, members):
        super().__init__(timeout=900)
        self.boss_key = boss_key
        self.boss = boss.copy()
        self.max_hp = boss["hp"]
        self.members = {}
        for m in members:
            p = ensure_player(m.id, str(m))
            _, gear_hp, _ = equipment_stats(m.id)
            self.members[m.id] = {"member": m, "hp": p[9]+gear_hp, "max_hp": p[9]+gear_hp,
                                  "mp": p[10], "max_mp": p[10]}
        self.turn = 0
        self.finished = False
        self.locked = False
        self.party_mode = len(members) > 1

    async def interaction_check(self, interaction):
        if interaction.user.id not in self.members:
            await interaction.response.send_message("Kamu bukan peserta pertarungan ini.", ephemeral=True)
            return False
        if self.finished:
            await interaction.response.send_message("Pertarungan sudah selesai.", ephemeral=True)
            return False
        if self.locked:
            await interaction.response.send_message("Aksi sebelumnya masih diproses, coba sebentar lagi.", ephemeral=True)
            return False
        return True

    def status_text(self, last=""):
        living = [d for d in self.members.values() if d["hp"] > 0]
        people = "\n".join(f"{d['member'].display_name}: ❤️ {max(0,d['hp'])}/{d['max_hp']} · 💧 {d['mp']}/{d['max_mp']}" for d in self.members.values())
        return (f"⚔️ **{self.boss['name']}** · {'Party/Co-op' if self.party_mode else 'Solo'}\n"
                f"👹 Boss HP: **{max(0,self.boss['hp']):,}/{self.max_hp:,}** · ATK {self.boss['atk']:,}\n"
                f"{people}\n{last}")

    async def act(self, interaction, action):
        self.locked = True
        await interaction.response.defer()
        try:
            d = self.members[interaction.user.id]
            player = ensure_player(interaction.user.id, str(interaction.user))
            gear_atk, _, gear_def = equipment_stats(interaction.user.id)
            level, atk, defense = player[2], player[11] + gear_atk, player[12] + gear_def
            if d["hp"] <= 0:
                await interaction.followup.send("Karakter kamu sudah tumbang dan tidak bisa beraksi lagi.", ephemeral=True)
                return
            if action == "skill" and d["mp"] < 15:
                await interaction.followup.send("MP tidak cukup; skill memerlukan 15 MP.", ephemeral=True)
                return
            if action == "skill":
                d["mp"] -= 15
                damage = max(1, int(atk * (2.0 + level * 0.04) - 25))
            elif action == "guard":
                d["hp"] = min(d["max_hp"], d["hp"] + max(12, defense * 2))
                damage = 0
            else:
                damage = max(1, int(atk + level * 2 - 15))
            # Special boss mechanics alter damage and attack patterns.
            if self.boss_key == "varkhaz" and self.turn % 3 == 2:
                damage = int(damage * 0.55)  # Sovereign's Guard
            if self.boss_key == "noxvyr" and self.turn % 4 == 3:
                damage = int(damage * 0.7)   # Abyssal Devour
            self.boss["hp"] -= damage
            self.turn += 1
            if self.boss["hp"] <= 0:
                self.finished = True
                self.stop()
                reward_gold = 2500 if self.boss_key == "varkhaz" else 3500 if self.boss_key == "noxvyr" else 5000
                reward_exp = 1800 if self.boss_key == "varkhaz" else 2500 if self.boss_key == "noxvyr" else 3500
                drop = SECRET_BOSSES[self.boss_key]["drop"]
                for uid, data in self.members.items():
                    if data["hp"] <= 0:
                        continue
                    gain_exp(uid, reward_exp)
                    with get_connection() as conn:
                        conn.execute("UPDATE rpg_players SET gold_coin=gold_coin+?, wins=wins+1 WHERE user_id=?", (reward_gold, str(uid)))
                        conn.execute("INSERT INTO rpg_boss_inventory(user_id,item_key,quantity) VALUES(?,?,1) ON CONFLICT(user_id,item_key) DO UPDATE SET quantity=quantity+1", (str(uid), self.boss_key))
                        conn.execute(f"UPDATE rpg_boss_progress SET {self.boss_key}=1 WHERE user_id=?", (str(uid),))
                for item in self.children: item.disabled = True
                await interaction.edit_original_response(content=(self.status_text(f"🏆 **Boss dikalahkan!** Peserta yang masih berdiri menerima **{reward_exp:,} EXP**, **{reward_gold:,} Gold**, dan drop **{drop} ×1**.\nGunakan `!bossinventory` untuk melihat drop. Setelah mengumpulkan ketiga drop unik, gunakan `!nighttrial` untuk menukar semuanya dengan role **The Night Ruler**.")), view=self)
                return
            # Boss retaliation: attacks the current actor; Eclipsara phases hit harder every third turn.
            incoming = max(1, int(self.boss["atk"] - defense * 0.4))
            if action == "guard": incoming = max(1, incoming // 2)
            if self.boss_key == "eclipsara" and self.turn % 3 == 0:
                incoming = int(incoming * 1.7)
            d["hp"] -= incoming
            if d["hp"] <= 0:
                d["hp"] = 0
                with get_connection() as conn:
                    conn.execute("UPDATE rpg_players SET losses=losses+1 WHERE user_id=?", (str(interaction.user.id),))
            if not any(x["hp"] > 0 for x in self.members.values()):
                self.finished = True
                self.stop()
                for item in self.children: item.disabled = True
                await interaction.edit_original_response(content=self.status_text("💀 **Party tumbang. Boss menang.** Tidak ada hadiah drop kali ini."), view=self)
                return
            for item in self.children: item.disabled = False
            await interaction.edit_original_response(content=self.status_text(f"Aksi {interaction.user.display_name}: **{action}**, damage **{damage}**. Boss membalas **{incoming}** damage."), view=self)
        except Exception as exc:
            print(f"[Fumi RPG] Secret boss error: {exc!r}")
            await interaction.followup.send("Terjadi error saat memproses boss. Admin bisa memeriksa Console FadeHost.", ephemeral=True)
        finally:
            self.locked = False

    @discord.ui.button(label="Serang", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def attack_button(self, interaction, button): await self.act(interaction, "attack")

    @discord.ui.button(label="Skill (15 MP)", style=discord.ButtonStyle.danger, emoji="✨")
    async def skill_button(self, interaction, button): await self.act(interaction, "skill")

    @discord.ui.button(label="Bertahan/Pulih", style=discord.ButtonStyle.success, emoji="🛡️")
    async def guard_button(self, interaction, button): await self.act(interaction, "guard")

class PartyInviteView(discord.ui.View):
    def __init__(self, leader, invited):
        super().__init__(timeout=60)
        self.leader_id = leader.id
        self.invited_id = invited.id
        self.accepted = False

    @discord.ui.button(label="Terima Party", style=discord.ButtonStyle.success)
    async def accept(self, interaction, button):
        if interaction.user.id != self.invited_id:
            await interaction.response.send_message("Undangan ini bukan untukmu.", ephemeral=True)
            return
        self.accepted = True
        self.stop()
        await interaction.response.edit_message(content=f"🤝 {interaction.user.mention} menerima undangan party. (Pencatatan party belum disimpan permanen.)", view=None)

    @discord.ui.button(label="Tolak", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction, button):
        if interaction.user.id != self.invited_id:
            await interaction.response.send_message("Undangan ini bukan untukmu.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(content="Undangan party ditolak.", view=None)

def setup_rpg(bot):
    setup_rpg_database()

    @bot.group(name="rpg", invoke_without_command=True)
    async def rpg(ctx):
        ensure_player(ctx.author.id, str(ctx.author))
        await rpg_send(ctx, "menu", embed=discord.Embed(
            title="🌑 Fumi RPG",
            description="`!profile` · `!inventory` · `!daily` · `!gacha coin|mana|orb|void`\n"
                        "`!collection` · `!class` · `!adventure basic|hard|nightmare`\n"
                        "`!difficulty` · `!bosses` · `!bossfight` · `!fieldbosses` · `!shop` · `!equipgacha`\n"
                        "`!party @anggota` · `!pvp @anggota` · `!rpg help` untuk bantuan.",
            color=discord.Color.dark_purple()))

    @rpg.command(name="help")
    async def rpg_help(ctx):
        await rpg_send(ctx, "menu", content=(
            "**Fumi RPG commands**\n`!profile [@anggota]`, `!inventory`, `!daily`\n"
            "`!gacha coin|mana|orb|void`, `!collection [@anggota]`\n"
            "`!class`, `!class choose Warrior|Mage|Archer|Healer|Assassin`\n"
            "`!adventure basic|hard|nightmare`, `!difficulty`, `!bosses`, `!bossfight`\n"
            "`!party @anggota`, `!pvp @anggota`, `!rpgstatus`\n"
            "`!shop`, `!buy <nama item>`, `!sell <id>`, `!equipgacha`, `!equipments`, `!equipment`\n"
            "`!equip <id>`, `!unequip weapon|armor`, `!trade @anggota <id_item> [gold]`, `!tradeaccept <id>`"))

    @bot.command(name="profile", aliases=["profil"])
    async def profile(ctx, member: discord.Member = None):
        member = member or ctx.author
        p = ensure_player(member.id, str(member))
        chars = get_characters(member.id)
        embed = discord.Embed(title=f"🧭 Profil RPG — {member.display_name}", color=discord.Color.blurple())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Level / EXP", value=f"{p[2]} · {p[3]}/{p[2]*100}", inline=True)
        embed.add_field(name="Class", value=p[8], inline=True)
        embed.add_field(name="Karakter Gacha", value=str(len(chars)), inline=True)
        embed.add_field(name="Statistik", value=f"❤️ HP {p[9]}\n💧 MP {p[10]}\n⚔️ ATK {p[11]}\n🛡️ DEF {p[12]}", inline=True)
        embed.add_field(name="Mata Uang", value=f"🪙 {p[4]} Gold\n💎 {p[5]} Mana\n🔮 {p[6]} Orb\n🌑 {p[7]} Void Seal", inline=True)
        embed.add_field(name="Rekor", value=f"Menang: {p[13]} · Kalah: {p[14]}", inline=True)
        await rpg_send(ctx, "menu", embed=embed)

    @bot.command(name="inventory", aliases=["inv", "inventori"])
    async def inventory(ctx):
        p = ensure_player(ctx.author.id, str(ctx.author))
        await rpg_send(ctx, "menu", embed=discord.Embed(
            title=f"🎒 Inventory — {ctx.author.display_name}",
            description=f"🪙 Gold Coin: **{p[4]}**\n💎 Mana Crystal: **{p[5]}**\n"
                        f"🔮 Summoning Orb: **{p[6]}**\n🌑 Void Seal: **{p[7]}**",
            color=discord.Color.gold()))

    @bot.command(name="daily")
    async def daily(ctx):
        ensure_player(ctx.author.id, str(ctx.author))
        today = date.today().isoformat()
        with get_connection() as conn:
            row = conn.execute("SELECT last_daily FROM rpg_players WHERE user_id=?", (str(ctx.author.id),)).fetchone()
            if row and row[0] == today:
                await rpg_send(ctx, "menu", content="⏳ Hadiah harian sudah diklaim. Coba lagi besok.")
                return
            conn.execute("UPDATE rpg_players SET gold_coin=gold_coin+250, mana_crystal=mana_crystal+1, last_daily=? WHERE user_id=?",
                         (today, str(ctx.author.id)))
        await rpg_send(ctx, "menu", content=f"🎁 {ctx.author.mention} mendapat 250 Gold Coin dan 1 Mana Crystal!")

    @bot.command(name="gacha")
    async def gacha(ctx, banner_key: str = None):
        ensure_player(ctx.author.id, str(ctx.author))
        if not banner_key or banner_key.lower() not in BANNERS:
            await rpg_send(ctx, "gacha", content="Banner: `!gacha coin`, `!gacha mana`, `!gacha orb`, `!gacha void`.")
            return
        key = banner_key.lower()
        b = BANNERS[key]
        with get_connection() as conn:
            row = conn.execute(f"SELECT {b['currency']} FROM rpg_players WHERE user_id=?", (str(ctx.author.id),)).fetchone()
            if not row or row[0] < b["cost"]:
                await rpg_send(ctx, "gacha", content=f"❌ Butuh {b['cost']} {b['display_currency']}.")
                return
            name, role = random.choice(b["characters"])
            conn.execute(f"UPDATE rpg_players SET {b['currency']}={b['currency']}-? WHERE user_id=?",
                         (b["cost"], str(ctx.author.id)))
            old = conn.execute("SELECT quantity FROM rpg_characters WHERE user_id=? AND name=?",
                               (str(ctx.author.id), name)).fetchone()
            duplicate = old is not None
            if duplicate:
                conn.execute("UPDATE rpg_characters SET quantity=quantity+1, shards=shards+10 WHERE user_id=? AND name=?",
                             (str(ctx.author.id), name))
            else:
                conn.execute("INSERT INTO rpg_characters(user_id,name,role,rarity) VALUES(?,?,?,?)",
                             (str(ctx.author.id), name, role, b["rarity"]))
            conn.execute("INSERT INTO rpg_gacha_history(user_id,banner,character_name,rarity) VALUES(?,?,?,?)",
                         (str(ctx.author.id), key, name, b["rarity"]))
        emoji = {"Common":"⚪", "Rare":"🔵", "Epic":"🟣", "Secret":"🌑"}[b["rarity"]]
        await rpg_send(ctx, "gacha", embed=discord.Embed(
            title=f"{emoji} Gacha Result",
            description=f"**{name}** · {role} · {b['rarity']}\n" +
                        ("Duplikat: +10 shards." if duplicate else "Karakter baru ditambahkan."),
            color=discord.Color.dark_purple()))


    @bot.command(name="equipgacha", aliases=["gachaequip", "equipmentgacha"])
    async def equipgacha(ctx):
        p = ensure_player(ctx.author.id, str(ctx.author))
        pool = CLASS_EQUIPMENT.get(p[8], [])
        if not pool:
            await rpg_send(ctx, "gacha", content="Class kamu belum punya pool equipment.")
            return
        if p[4] < EQUIPMENT_GACHA_COST:
            await rpg_send(ctx, "gacha", content=f"❌ Butuh {EQUIPMENT_GACHA_COST} Gold Coin.")
            return
        rarity = random.choices([x[0] for x in EQUIPMENT_GACHA_ODDS], weights=[x[1] for x in EQUIPMENT_GACHA_ODDS], k=1)[0]
        item = random.choice([x for x in pool if x[2] == rarity])
        with get_connection() as conn:
            conn.execute("UPDATE rpg_players SET gold_coin=gold_coin-? WHERE user_id=?", (EQUIPMENT_GACHA_COST,str(ctx.author.id)))
        item_id = add_equipment(ctx.author.id,item,p[8],0,"gacha")
        name,slot,rarity,atk,hp,defense = item
        await rpg_send(ctx,"gacha",embed=discord.Embed(title=f"🎲 Equipment Gacha — {rarity}",description=f"**{name}** · {slot.title()} · Class {p[8]}\nATK +{atk} · HP +{hp} · DEF +{defense}\nID `{item_id}` · Biaya {EQUIPMENT_GACHA_COST} Gold",color=discord.Color.gold() if rarity=="Mythic" else discord.Color.dark_purple()))

    @bot.command(name="equipments", aliases=["equiplist","equipmentinventory"])
    async def equipments(ctx):
        ensure_player(ctx.author.id,str(ctx.author))
        rows=owned_equipment(ctx.author.id)
        if not rows:
            await rpg_send(ctx,"menu",content="🎒 Inventory equipment kosong. Gunakan `!equipgacha` atau `!shop`.")
            return
        with get_connection() as conn:
            equipped={r[0] for r in conn.execute("SELECT item_id FROM rpg_equipment_loadout WHERE user_id=? AND item_id IS NOT NULL",(str(ctx.author.id),))}
        lines=[f"`ID {r[0]}` **{r[1]}** [{r[3]} {r[2]}] — ATK +{r[4]} HP +{r[5]} DEF +{r[6]}"+(" · **TERPASANG**" if r[0] in equipped else "")+(" · 🔒 Bound" if r[8] else "") for r in rows]
        await rpg_send(ctx,"menu",content="**🎒 Equipment Inventory**\n"+"\n".join(lines[:35]))

    @bot.command(name="equipment", aliases=["gear","loadout"])
    async def equipment(ctx):
        ensure_player(ctx.author.id,str(ctx.author))
        with get_connection() as conn:
            rows=conn.execute("SELECT l.slot,e.id,e.item_name,e.rarity,e.atk_bonus,e.hp_bonus,e.def_bonus FROM rpg_equipment_loadout l LEFT JOIN rpg_equipment_inventory e ON e.id=l.item_id WHERE l.user_id=?",(str(ctx.author.id),)).fetchall()
        by_slot={r[0]:r for r in rows}
        lines=[]
        for slot in ("weapon","armor"):
            r=by_slot.get(slot)
            lines.append(f"**{slot.title()}:** "+(f"`ID {r[1]}` {r[2]} [{r[3]}] · ATK +{r[4]} HP +{r[5]} DEF +{r[6]}" if r and r[1] else "— Kosong —"))
        atk,hp,defense=equipment_stats(ctx.author.id)
        await rpg_send(ctx,"menu",content="**⚔️ Equipment Terpasang**\n"+"\n".join(lines)+f"\nBonus total: ATK +{atk} · HP +{hp} · DEF +{defense}")

    @bot.command(name="equip")
    async def equip(ctx,item_id:int):
        ensure_player(ctx.author.id,str(ctx.author))
        with get_connection() as conn:
            item=conn.execute("SELECT id,item_name,slot,class_name FROM rpg_equipment_inventory WHERE id=? AND user_id=?",(item_id,str(ctx.author.id))).fetchone()
            player=conn.execute("SELECT class_name FROM rpg_players WHERE user_id=?",(str(ctx.author.id),)).fetchone()
            if not item:
                await rpg_send(ctx,"menu",content="❌ ID equipment tidak ditemukan.")
                return
            if item[3] not in ("Any",player[0]):
                await rpg_send(ctx,"menu",content=f"❌ Equipment ini khusus class {item[3]}.")
                return
            conn.execute("INSERT INTO rpg_equipment_loadout(user_id,slot,item_id) VALUES(?,?,?) ON CONFLICT(user_id,slot) DO UPDATE SET item_id=excluded.item_id",(str(ctx.author.id),item[2],item[0]))
        await rpg_send(ctx,"menu",content=f"✅ **{item[1]}** dipasang sebagai {item[2]}.")

    @bot.command(name="unequip")
    async def unequip(ctx,slot:str):
        slot=slot.lower()
        if slot not in ("weapon","armor"):
            await rpg_send(ctx,"menu",content="Gunakan `!unequip weapon` atau `!unequip armor`.")
            return
        with get_connection() as conn:
            cur=conn.execute("DELETE FROM rpg_equipment_loadout WHERE user_id=? AND slot=?",(str(ctx.author.id),slot))
        await rpg_send(ctx,"menu",content="✅ Equipment dilepas." if cur.rowcount else "Slot itu sudah kosong.")

    @bot.command(name="shop", aliases=["toko"])
    async def shop(ctx):
        lines=[]
        for name,price in EQUIPMENT_SHOP.items():
            item=equipment_item_by_name(name)
            if item:
                lines.append(f"**{name}** — {price} Gold · {item[1].title()} · ATK +{item[3]} HP +{item[4]} DEF +{item[5]}")
        await rpg_send(ctx,"menu",content="**🏪 Fumi Equipment Shop**\n"+"\n".join(lines)+"\n\nBeli dengan `!buy nama item`. Limited drop-only tidak dijual.")

    @bot.command(name="buy")
    async def buy(ctx,*,item_name:str):
        p=ensure_player(ctx.author.id,str(ctx.author))
        matched=next(((name,price) for name,price in EQUIPMENT_SHOP.items() if name.casefold()==item_name.strip().casefold()),None)
        if not matched:
            await rpg_send(ctx,"menu",content="❌ Item tidak ada di toko. Cek `!shop`.")
            return
        name,price=matched
        item=equipment_item_by_name(name)
        if not item or item[2]!="Basic":
            await rpg_send(ctx,"menu",content="❌ Toko hanya menjual equipment Basic pilihan.")
            return
        if p[4]<price:
            await rpg_send(ctx,"menu",content=f"❌ Gold tidak cukup. Harga {price} Gold.")
            return
        with get_connection() as conn:
            conn.execute("UPDATE rpg_players SET gold_coin=gold_coin-? WHERE user_id=?",(price,str(ctx.author.id)))
        item_id=add_equipment(ctx.author.id,item,"Any",0,"shop")
        await rpg_send(ctx,"menu",content=f"🛒 Berhasil membeli **{name}** seharga {price} Gold. ID `{item_id}`.")

    @bot.command(name="sell")
    async def sell(ctx,item_id:int):
        ensure_player(ctx.author.id,str(ctx.author))
        with get_connection() as conn:
            item=conn.execute("SELECT item_name,rarity,bound FROM rpg_equipment_inventory WHERE id=? AND user_id=?",(item_id,str(ctx.author.id))).fetchone()
            equipped=conn.execute("SELECT 1 FROM rpg_equipment_loadout WHERE user_id=? AND item_id=?",(str(ctx.author.id),item_id)).fetchone()
            if not item:
                await rpg_send(ctx,"menu",content="❌ Item tidak ditemukan.")
                return
            if item[2] or item[1]=="Limited":
                await rpg_send(ctx,"menu",content="🔒 Equipment Limited terikat ke pemilik dan tidak bisa dijual.")
                return
            if equipped:
                await rpg_send(ctx,"menu",content="Lepas equipment dahulu dengan `!unequip weapon` atau `!unequip armor`.")
                return
            price=max(25,int(EQUIPMENT_SHOP.get(item[0],100)*0.45))
            conn.execute("DELETE FROM rpg_equipment_inventory WHERE id=? AND user_id=?",(item_id,str(ctx.author.id)))
            conn.execute("UPDATE rpg_players SET gold_coin=gold_coin+? WHERE user_id=?",(price,str(ctx.author.id)))
        await rpg_send(ctx,"menu",content=f"💰 **{item[0]}** terjual seharga {price} Gold.")

    @bot.command(name="trade")
    async def trade(ctx,member:discord.Member,item_id:int,gold_amount:int=0):
        ensure_player(ctx.author.id,str(ctx.author)); ensure_player(member.id,str(member))
        if member.bot or member.id==ctx.author.id or gold_amount<0:
            await rpg_send(ctx,"menu",content="❌ Target trade tidak valid.")
            return
        with get_connection() as conn:
            item=conn.execute("SELECT id,item_name,bound FROM rpg_equipment_inventory WHERE id=? AND user_id=?",(item_id,str(ctx.author.id))).fetchone()
            equipped=conn.execute("SELECT 1 FROM rpg_equipment_loadout WHERE user_id=? AND item_id=?",(str(ctx.author.id),item_id)).fetchone()
            gold=conn.execute("SELECT gold_coin FROM rpg_players WHERE user_id=?",(str(ctx.author.id),)).fetchone()[0]
            if not item or equipped:
                await rpg_send(ctx,"menu",content="❌ Item tidak ditemukan atau masih terpasang.")
                return
            if item[2]:
                await rpg_send(ctx,"menu",content="🔒 Limited terikat pada pemilik dan tidak bisa ditrade.")
                return
            if gold_amount>gold:
                await rpg_send(ctx,"menu",content="❌ Gold kamu tidak cukup.")
                return
            offer_id=conn.execute("INSERT INTO rpg_trade_offers(from_user,to_user,item_id,gold_amount) VALUES(?,?,?,?)",(str(ctx.author.id),str(member.id),item_id,gold_amount)).lastrowid
        await rpg_send(ctx,"menu",content=f"🤝 {member.mention}, **{ctx.author.display_name}** menawarkan **{item[1]}** + {gold_amount:,} Gold. Terima dengan `!tradeaccept {offer_id}`.")

    @bot.command(name="tradeaccept")
    async def tradeaccept(ctx,offer_id:int):
        ensure_player(ctx.author.id,str(ctx.author))
        with get_connection() as conn:
            offer=conn.execute("SELECT from_user,to_user,item_id,gold_amount,status FROM rpg_trade_offers WHERE id=?",(offer_id,)).fetchone()
            if not offer or offer[4]!="pending" or offer[1]!=str(ctx.author.id):
                await rpg_send(ctx,"menu",content="❌ Trade tidak ditemukan, sudah selesai, atau bukan untuk kamu.")
                return
            sender,receiver,item_id,gold_amount,_=offer
            gold=conn.execute("SELECT gold_coin FROM rpg_players WHERE user_id=?",(sender,)).fetchone()
            item=conn.execute("SELECT item_name,bound FROM rpg_equipment_inventory WHERE id=? AND user_id=?",(item_id,sender)).fetchone()
            equipped=conn.execute("SELECT 1 FROM rpg_equipment_loadout WHERE user_id=? AND item_id=?",(sender,item_id)).fetchone()
            if not item or item[1] or equipped or not gold or gold[0]<gold_amount:
                conn.execute("UPDATE rpg_trade_offers SET status='cancelled' WHERE id=?",(offer_id,))
                await rpg_send(ctx,"menu",content="❌ Trade dibatalkan karena item/saldo pengirim berubah.")
                return
            conn.execute("UPDATE rpg_players SET gold_coin=gold_coin-? WHERE user_id=?",(gold_amount,sender))
            conn.execute("UPDATE rpg_players SET gold_coin=gold_coin+? WHERE user_id=?",(gold_amount,receiver))
            conn.execute("UPDATE rpg_equipment_inventory SET user_id=? WHERE id=?",(receiver,item_id))
            conn.execute("UPDATE rpg_trade_offers SET status='accepted' WHERE id=?",(offer_id,))
        await rpg_send(ctx,"menu",content=f"✅ Trade #{offer_id} selesai: **{item[0]}** dan {gold_amount:,} Gold dikirim ke {ctx.author.mention}.")


    @bot.command(name="collection", aliases=["koleksi", "characters"])
    async def collection(ctx, member: discord.Member = None):
        member = member or ctx.author
        ensure_player(member.id, str(member))
        chars = get_characters(member.id)
        if not chars:
            await rpg_send(ctx, "menu", content=f"{member.mention} belum punya karakter. Coba `!gacha coin`.")
            return
        lines = [f"{name} — {rarity} · {role} · x{qty} · {shards} shards"
                 for name, role, rarity, qty, shards in chars[:25]]
        await rpg_send(ctx, "menu", embed=discord.Embed(
            title=f"📘 Koleksi — {member.display_name}", description="\n".join(lines),
            color=discord.Color.blurple()))

    @bot.group(name="class", invoke_without_command=True)
    async def class_group(ctx):
        p = ensure_player(ctx.author.id, str(ctx.author))
        desc = "\n".join(f"**{name}** — HP {s['hp']}, MP {s['mp']}, ATK {s['atk']}, DEF {s['def']}; skill {s['skill']}"
                         for name, s in CLASSES.items())
        await rpg_send(ctx, "menu", content=f"Class saat ini: **{p[8]}**\n{desc}\nGanti class: `!class choose Mage` (pilihan gratis, statistik dasar berubah).")

    @class_group.command(name="choose")
    async def class_choose(ctx, *, class_name: str):
        class_name = class_name.strip().title()
        if class_name not in CLASSES:
            await rpg_send(ctx, "menu", content="Pilih: Warrior, Mage, Archer, Healer, atau Assassin.")
            return
        s = CLASSES[class_name]
        ensure_player(ctx.author.id, str(ctx.author))
        with get_connection() as conn:
            level = conn.execute("SELECT level FROM rpg_players WHERE user_id=?", (str(ctx.author.id),)).fetchone()[0]
            stats = stats_for_level(class_name, level)
            conn.execute("UPDATE rpg_players SET class_name=?, hp=?, mp=?, atk=?, defense=? WHERE user_id=?",
                         (class_name, stats["hp"], stats["mp"], stats["atk"], stats["def"], str(ctx.author.id)))
        await rpg_send(ctx, "menu", content=(f"✨ Class berubah menjadi **{class_name}**. Skill utama: **{s['skill']}**.\n"
            f"Stat level {level}: HP {stats['hp']:,} · MP {stats['mp']:,} · ATK {stats['atk']:,} · DEF {stats['def']:,}."))

    @bot.command(name="syncstats", aliases=["statupgrade", "naikstat"])
    async def syncstats(ctx):
        ensure_player(ctx.author.id, str(ctx.author))
        stats = sync_player_stats(ctx.author.id, refill=True)
        p = ensure_player(ctx.author.id, str(ctx.author))
        await rpg_send(ctx, "menu", content=(
            f"📈 Statistik **{ctx.author.display_name}** disesuaikan dengan level **{p[2]:,}**!\n"
            f"❤️ HP: **{stats['hp']:,}**\n💧 MP: **{stats['mp']:,}**\n"
            f"⚔️ ATK: **{stats['atk']:,}**\n🛡️ DEF: **{stats['def']:,}**\n"
            "Statistik bertambah otomatis setiap naik level."))

    @bot.command(name="difficulty", aliases=["kesulitan"])
    async def difficulty(ctx):
        text = "\n".join(f"**{v['label']}** — HP ×{v['hp']:g}, ATK ×{v['atk']:g}, reward ×{v['reward']:g}"
                         for v in DIFFICULTIES.values())
        await rpg_send(ctx, "adventure", content=text + "\nSecret Boss berada di atas Nightmare.")

    @bot.command(name="adventure", aliases=["dungeon", "hunt"])
    async def adventure(ctx, difficulty_name: str = "basic"):
        ensure_player(ctx.author.id, str(ctx.author))
        difficulty_name = difficulty_name.lower()
        if difficulty_name not in DIFFICULTIES:
            await rpg_send(ctx, "adventure", content="Pilih kesulitan: `!adventure basic`, `!adventure hard`, `!adventure nightmare`.")
            return
        choices = MONSTER_BY_DIFFICULTY[difficulty_name]
        key = random.choice(choices)
        monster = scaled_monster(key, difficulty_name)
        view = AdventureView(ctx.author, monster, difficulty_name)
        await view.start()
        await rpg_send(ctx, "adventure",
                       content=f"⚔️ **{monster['name']}** muncul!\nKesulitan: **{difficulty_name.title()}**\n"
                               f"Monster HP: **{monster['hp']}** · ATK: **{monster['atk']}**\n"
                               f"HP kamu: **{view.hp}/{view.max_hp}** · MP: **{view.mp}/{view.max_mp}**",
                       view=view)


    @bot.command(name="fieldbosses", aliases=["fieldboss"])
    async def fieldbosses(ctx):
        lines=[f"`{k}` **{b['name']}** · {b['difficulty']} · HP {b['hp']:,} · ATK {b['atk']:,}\nDrop: **{b['drop']}** ({int(b['chance']*100)}%, Limited/Bound)" for k,b in FIELD_BOSSES.items()]
        await rpg_send(ctx,"boss",content="**👹 Field Bosses**\n"+"\n\n".join(lines)+"\n\nLawan dengan `!fieldbossfight <key>`.")

    @bot.command(name="fieldbossfight", aliases=["fboss"])
    async def fieldbossfight(ctx,boss_key:str=None):
        ensure_player(ctx.author.id,str(ctx.author))
        if not boss_key or boss_key.lower() not in FIELD_BOSSES:
            await rpg_send(ctx,"boss",content="Gunakan `!fieldbosses`, lalu `!fieldbossfight basic1` (basic2, hard1, hard2, nightmare1).")
            return
        key=boss_key.lower(); boss=FIELD_BOSSES[key]; p=ensure_player(ctx.author.id,str(ctx.author))
        gear_atk,gear_hp,gear_def=equipment_stats(ctx.author.id)
        max_hp=p[9]+gear_hp; hp=max_hp; boss_hp=boss["hp"]; atk=p[11]+gear_atk; defense=p[12]+gear_def; turns=0
        while hp>0 and boss_hp>0 and turns<100:
            turns+=1; boss_hp-=max(1,int(atk+p[2]*2-boss["def"]*0.25))
            if boss_hp>0: hp-=max(1,int(boss["atk"]-defense*0.4))
        if boss_hp<=0:
            gain_exp(ctx.author.id,boss["exp"])
            with get_connection() as conn:
                conn.execute("UPDATE rpg_players SET gold_coin=gold_coin+?,wins=wins+1 WHERE user_id=?",(boss["gold"],str(ctx.author.id)))
            drop=None
            if random.random()<boss["chance"]:
                slot,rarity,da,dh,dd=LIMITED_EQUIPMENT[boss["drop"]]
                add_equipment(ctx.author.id,(boss["drop"],slot,rarity,da,dh,dd),"Any",1,"field_boss")
                drop=boss["drop"]
            result=f"🏆 **{boss['name']} dikalahkan!**\nHadiah: {boss['exp']:,} EXP · {boss['gold']:,} Gold.\nHP tersisa: {max(0,hp):,}/{max_hp:,} · Giliran: {turns}"
            result+=f"\n🎁 Limited drop: **{drop}** — terikat ke akunmu." if drop else f"\nDrop tidak jatuh kali ini ({int(boss['chance']*100)}% peluang)."
        else:
            with get_connection() as conn: conn.execute("UPDATE rpg_players SET losses=losses+1 WHERE user_id=?",(str(ctx.author.id),))
            result=f"💀 Kalah melawan **{boss['name']}**. Boss tersisa sekitar {max(0,boss_hp):,} HP. Tingkatkan level/equipment lalu coba lagi."
        await rpg_send(ctx,"boss",content=result)


    @bot.command(name="bosses", aliases=["secretboss"])
    async def bosses(ctx):
        lines = [f"**{b['name']}**\nHP {b['hp']:,} · ATK {b['atk']:,}\nMekanik: {b['mechanic']}\nDrop: *{b['drop']}*"
                 for b in SECRET_BOSSES.values()]
        await rpg_send(ctx, "boss", content="\n\n".join(lines) +
                       "\n\nKalahkan ketiganya dan selesaikan trial **Throne of the Forgotten Night** untuk membuka **The Night Ruler**.")

    @bot.command(name="bossfight", aliases=["boss"])
    async def bossfight(ctx, boss_key: str = None, mode: str = "solo", member1: discord.Member = None, member2: discord.Member = None, member3: discord.Member = None):
        if not boss_key or boss_key.lower() not in SECRET_BOSSES:
            await rpg_send(ctx, "boss", content="Pilih boss: `!bossfight varkhaz solo` atau `!bossfight varkhaz party @anggota [@anggota2] [@anggota3]`. Boss: varkhaz, noxvyr, eclipsara.")
            return
        key = boss_key.lower()
        mode = mode.lower()
        if mode not in ("solo", "party", "coop", "co-op"):
            await rpg_send(ctx, "boss", content="Mode: `solo` atau `party`. Contoh `!bossfight noxvyr party @anggota`.")
            return
        members = [ctx.author]
        if mode != "solo":
            members += [m for m in (member1, member2, member3) if m and not m.bot and m.id != ctx.author.id]
            # Deduplicate participants
            members = list({m.id: m for m in members}.values())
            if len(members) < 2:
                await rpg_send(ctx, "boss", content="Mode party perlu minimal satu teman. Contoh: `!bossfight varkhaz party @anggota`.")
                return
        for m in members: ensure_player(m.id, str(m))
        view = SecretBossView(key, SECRET_BOSSES[key], members)
        await rpg_send(ctx, "boss", content=view.status_text("Tekan tombol untuk bertindak. Semua peserta boleh bergiliran; boss membalas setiap aksi."), view=view)

    @bot.command(name="bossinventory", aliases=["bossinv", "bossitems"])
    async def bossinventory(ctx, member: discord.Member = None):
        member = member or ctx.author
        ensure_player(member.id, str(member))
        with get_connection() as conn:
            rows = conn.execute("SELECT item_key, quantity FROM rpg_boss_inventory WHERE user_id=? AND quantity>0", (str(member.id),)).fetchall()
        labels = {k: v["drop"] for k,v in SECRET_BOSSES.items()}
        lines = [f"• **{labels.get(k,k)}** ×{q}" for k,q in rows]
        await rpg_send(ctx, "boss", content=f"🎒 **Boss inventory — {member.display_name}**\n" + ("\n".join(lines) if lines else "Belum punya drop boss.") + "\nKumpulkan ketiga drop unik untuk menukar menjadi role **The Night Ruler** lewat `!nighttrial`.")

    @bot.command(name="nighttrial", aliases=["bossredeem", "redeemnight"])
    async def nighttrial(ctx):
        if not ctx.guild:
            await ctx.send("Command ini hanya bisa digunakan di server.")
            return
        uid = str(ctx.author.id)
        ensure_player(ctx.author.id, str(ctx.author))
        with get_connection() as conn:
            progress = conn.execute("SELECT varkhaz,noxvyr,eclipsara,trial_complete FROM rpg_boss_progress WHERE user_id=?", (uid,)).fetchone()
            items = dict(conn.execute("SELECT item_key,quantity FROM rpg_boss_inventory WHERE user_id=?", (uid,)).fetchall())
            if progress and progress[3]:
                await rpg_send(ctx, "boss", content="Kamu sudah menyelesaikan Throne of the Forgotten Night.")
                return
            if not progress or not all(progress[i] for i in range(3)) or not all(items.get(k,0)>0 for k in SECRET_BOSSES):
                await rpg_send(ctx, "boss", content="🔒 Trial terkunci. Kalahkan ketiga Secret Boss dan miliki masing-masing satu drop unik. Cek `!bossinventory`.")
                return
            role = discord.utils.get(ctx.guild.roles, name=SECRET_CLASS)
            if role is None:
                await rpg_send(ctx, "boss", content=f"Role **{SECRET_CLASS}** belum ada di server. Admin perlu membuat role itu dan memastikan role bot berada di atasnya.")
                return
            if not ctx.guild.me.guild_permissions.manage_roles or role >= ctx.guild.me.top_role:
                await rpg_send(ctx, "boss", content="Bot tidak punya izin/posisi role yang cukup untuk memberikan role itu. Aktifkan Manage Roles dan pindahkan role bot di atas role hadiah.")
                return
            try:
                await ctx.author.add_roles(role, reason="Completed Fumi RPG Secret Boss trial")
            except discord.Forbidden:
                await rpg_send(ctx, "boss", content="Discord menolak pemberian role. Periksa izin Manage Roles dan hierarki role bot.")
                return
            for k in SECRET_BOSSES:
                conn.execute("UPDATE rpg_boss_inventory SET quantity=quantity-1 WHERE user_id=? AND item_key=?", (uid,k))
            conn.execute("UPDATE rpg_boss_progress SET trial_complete=1 WHERE user_id=?", (uid,))
        await rpg_send(ctx, "boss", content=f"👑 **Throne of the Forgotten Night selesai!** {ctx.author.mention} menukar tiga drop unik dan menerima role **{SECRET_CLASS}**.")

    @bot.command(name="party")
    async def party(ctx, member: discord.Member = None):
        if member is None or member.bot or member.id == ctx.author.id:
            await rpg_send(ctx, "coop", content="Gunakan `!party @anggota` untuk mengundang pemain lain.")
            return
        view = PartyInviteView(ctx.author, member)
        await rpg_send(ctx, "coop", content=f"🤝 {member.mention}, kamu diundang ke party oleh {ctx.author.mention}.",
                       view=view)

    @bot.command(name="pvp")
    async def pvp(ctx, member: discord.Member = None):
        if member is None or member.bot or member.id == ctx.author.id:
            await rpg_send(ctx, "pvp", content="Gunakan `!pvp @anggota` untuk menantang pemain lain.")
            return
        await rpg_send(ctx, "pvp", content=(
            f"⚔️ {ctx.author.mention} menantang {member.mention}.\n"
            "Arena dan matchmaking ini belum mengubah statistik atau rating; sistem duel belum aktif."))

    @bot.command(name="rpgstatus")
    async def rpgstatus(ctx):
        await rpg_send(ctx, "menu", content=(
            "Fumi RPG module aktif: profil, statistik dasar, class pilihan, daily, gacha, koleksi, "
            "petualangan monster berbasis tombol, kesulitan dan info Secret Boss.\n"
            "Secret Boss solo/co-op, drop inventory, dan trial penukaran role aktif. Duel PvP belum aktif."))


    # Secret admin commands: deliberately omitted from public RPG help/menu.
    # Configure SECRET_ADMIN_IDS with Discord user IDs, separated by commas.
    # Server administrators are also allowed to use these commands.
    import os

    def is_secret_admin(ctx):
        configured = {
            item.strip()
            for item in os.getenv("SECRET_ADMIN_IDS", "").split(",")
            if item.strip().isdigit()
        }
        return (
            ctx.author.id in {int(item) for item in configured}
            or (ctx.guild is not None and ctx.author.guild_permissions.administrator)
        )

    async def secret_denied(ctx):
        # Keep command discovery and unauthorized attempts quiet.
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass

    @bot.command(name="addgold", hidden=True)
    async def secret_addgold(ctx, member: discord.Member, amount: int):
        if not is_secret_admin(ctx):
            await secret_denied(ctx)
            return
        if amount <= 0:
            await ctx.send("Jumlah harus lebih besar dari 0.", delete_after=8)
            return
        ensure_player(member.id, str(member))
        with get_connection() as conn:
            before = conn.execute(
                "SELECT gold_coin FROM rpg_players WHERE user_id=?",
                (str(member.id),)
            ).fetchone()[0]
            conn.execute(
                "UPDATE rpg_players SET gold_coin=gold_coin+? WHERE user_id=?",
                (amount, str(member.id))
            )
            after = before + amount
        await ctx.send(
            f"🔐 Gold {member.mention}: **{before:,} → {after:,}** (+{amount:,}).",
            delete_after=15
        )

    @bot.command(name="removegold", hidden=True)
    async def secret_removegold(ctx, member: discord.Member, amount: int):
        if not is_secret_admin(ctx):
            await secret_denied(ctx)
            return
        if amount <= 0:
            await ctx.send("Jumlah harus lebih besar dari 0.", delete_after=8)
            return
        ensure_player(member.id, str(member))
        with get_connection() as conn:
            row = conn.execute(
                "SELECT gold_coin FROM rpg_players WHERE user_id=?",
                (str(member.id),)
            ).fetchone()
            before = row[0]
            after = max(0, before - amount)
            conn.execute(
                "UPDATE rpg_players SET gold_coin=? WHERE user_id=?",
                (after, str(member.id))
            )
        await ctx.send(
            f"🔐 Gold {member.mention}: **{before:,} → {after:,}** (-{before-after:,}; saldo tidak bisa negatif).",
            delete_after=15
        )

    @bot.command(name="setgold", hidden=True)
    async def secret_setgold(ctx, member: discord.Member, amount: int):
        if not is_secret_admin(ctx):
            await secret_denied(ctx)
            return
        if amount < 0:
            await ctx.send("Gold tidak boleh negatif.", delete_after=8)
            return
        ensure_player(member.id, str(member))
        with get_connection() as conn:
            row = conn.execute(
                "SELECT gold_coin FROM rpg_players WHERE user_id=?",
                (str(member.id),)
            ).fetchone()
            before = row[0]
            conn.execute(
                "UPDATE rpg_players SET gold_coin=? WHERE user_id=?",
                (amount, str(member.id))
            )
        await ctx.send(
            f"🔐 Gold {member.mention}: **{before:,} → {amount:,}**.",
            delete_after=15
        )


    # Additional hidden admin commands: level and RPG currencies.
    @bot.command(name="setlevel", hidden=True)
    async def secret_setlevel(ctx, member: discord.Member, level: int):
        if not is_secret_admin(ctx):
            await secret_denied(ctx)
            return
        if level < 1 or level > 10000:
            await ctx.send("Level harus antara 1 dan 10000.", delete_after=8)
            return
        ensure_player(member.id, str(member))
        with get_connection() as conn:
            row = conn.execute(
                "SELECT level FROM rpg_players WHERE user_id=?",
                (str(member.id),)
            ).fetchone()
            before = row[0]
            class_name = conn.execute("SELECT class_name FROM rpg_players WHERE user_id=?", (str(member.id),)).fetchone()[0]
            stats = stats_for_level(class_name, level)
            conn.execute(
                "UPDATE rpg_players SET level=?, exp=0, hp=?, mp=?, atk=?, defense=? WHERE user_id=?",
                (level, stats["hp"], stats["mp"], stats["atk"], stats["def"], str(member.id))
            )
        await ctx.send(
            f"🔐 Level {member.mention}: **{before} → {level}** (EXP diatur ke 0).\n"
            f"Stat baru: HP {stats['hp']:,} · MP {stats['mp']:,} · ATK {stats['atk']:,} · DEF {stats['def']:,}.",
            delete_after=15
        )

    @bot.command(name="addmana", hidden=True)
    async def secret_addmana(ctx, member: discord.Member, amount: int):
        if not is_secret_admin(ctx):
            await secret_denied(ctx)
            return
        if amount <= 0:
            await ctx.send("Jumlah harus lebih besar dari 0.", delete_after=8)
            return
        ensure_player(member.id, str(member))
        with get_connection() as conn:
            before = conn.execute(
                "SELECT mana_crystal FROM rpg_players WHERE user_id=?",
                (str(member.id),)
            ).fetchone()[0]
            conn.execute(
                "UPDATE rpg_players SET mana_crystal=mana_crystal+? WHERE user_id=?",
                (amount, str(member.id))
            )
        await ctx.send(
            f"🔐 Mana Crystal {member.mention}: **{before:,} → {before + amount:,}** (+{amount:,}).",
            delete_after=15
        )

    @bot.command(name="addorb", hidden=True)
    async def secret_addorb(ctx, member: discord.Member, amount: int):
        if not is_secret_admin(ctx):
            await secret_denied(ctx)
            return
        if amount <= 0:
            await ctx.send("Jumlah harus lebih besar dari 0.", delete_after=8)
            return
        ensure_player(member.id, str(member))
        with get_connection() as conn:
            before = conn.execute(
                "SELECT summoning_orb FROM rpg_players WHERE user_id=?",
                (str(member.id),)
            ).fetchone()[0]
            conn.execute(
                "UPDATE rpg_players SET summoning_orb=summoning_orb+? WHERE user_id=?",
                (amount, str(member.id))
            )
        await ctx.send(
            f"🔐 Summoning Orb {member.mention}: **{before:,} → {before + amount:,}** (+{amount:,}).",
            delete_after=15
        )

    @bot.command(name="addvoid", hidden=True)
    async def secret_addvoid(ctx, member: discord.Member, amount: int):
        if not is_secret_admin(ctx):
            await secret_denied(ctx)
            return
        if amount <= 0:
            await ctx.send("Jumlah harus lebih besar dari 0.", delete_after=8)
            return
        ensure_player(member.id, str(member))
        with get_connection() as conn:
            before = conn.execute(
                "SELECT void_seal FROM rpg_players WHERE user_id=?",
                (str(member.id),)
            ).fetchone()[0]
            conn.execute(
                "UPDATE rpg_players SET void_seal=void_seal+? WHERE user_id=?",
                (amount, str(member.id))
            )
        await ctx.send(
            f"🔐 Void Seal {member.mention}: **{before:,} → {before + amount:,}** (+{amount:,}).",
            delete_after=15
        )

    @bot.command(name="secretcheck", hidden=True)
    async def secret_check(ctx, member: discord.Member):
        if not is_secret_admin(ctx):
            await secret_denied(ctx)
            return
        p = ensure_player(member.id, str(member))
        await ctx.send(
            f"🔐 RPG check — {member.mention}\\n"
            f"Level: **{p[2]}** · EXP: **{p[3]}**\\n"
            f"Gold: **{p[4]:,}** · Mana: **{p[5]}** · Orb: **{p[6]}** · Void Seal: **{p[7]}**",
            delete_after=20
        )


    print("RPG system terdaftar.")
