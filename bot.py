import os
import sqlite3
import asyncio
from datetime import datetime, timedelta
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ──────────────────────────────────────────────────────────
#  CONFIGURATION
# ──────────────────────────────────────────────────────────

BOT_TOKEN = "8777662417:AAFA5Nv6bHOQbE8Vd5xJeQ8L9fUze45abcg"
ADMIN_IDS = [8178183186]
BOT_NAME = "Drop Zone"
CANAL_LINK = "https://t.me/+pHwsFHqrYP0xYzNl"

# ──────────────────────────────────────────────────────────
#  BASE DE DONNÉES
# ──────────────────────────────────────────────────────────

DEFAULT_COOLDOWN_MINUTES = 60

class Database:
    def __init__(self, path: str = "bot.db"):
        self.path = path
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id    INTEGER PRIMARY KEY,
                    username   TEXT,
                    blacklist  INTEGER DEFAULT 0,
                    joined_at  DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS prizes (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS claims (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL REFERENCES users(user_id),
                    prize_id    INTEGER NOT NULL REFERENCES prizes(id),
                    claimed_at  DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cooldowns (
                    user_id INTEGER PRIMARY KEY,
                    reset_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                INSERT OR IGNORE INTO settings (key, value) VALUES ('cooldown_minutes', '60');
            """)

    # ── UTILISATEURS ───────────────────────────────────────────────
    def add_user(self, user_id: int, username: str = None):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
                (user_id, username)
            )

    def is_blacklisted(self, user_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT blacklist FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return bool(row and row['blacklist'])

    def toggle_blacklist(self, user_id: int) -> bool:
        with self._conn() as conn:
            conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            cur = conn.execute(
                "UPDATE users SET blacklist = NOT blacklist WHERE user_id = ? RETURNING blacklist",
                (user_id,)
            )
            return cur.fetchone()[0] if cur.fetchone() else False

    def get_user_by_username(self, username: str) -> Optional[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM users WHERE username = ? OR username = ?", 
                (username.lstrip('@'), username)
            ).fetchone()

    def get_all_users(self):
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM users ORDER BY joined_at DESC"
            ).fetchall()

    # ── PRIX ───────────────────────────────────────────────────
    def add_prize(self, name: str, content: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO prizes (name, content) VALUES (?, ?)", (name, content)
            )
            return cur.lastrowid

    def add_bulk_prizes(self, name: str, contents: list) -> list:
        added_ids = []
        with self._conn() as conn:
            for content in contents:
                if content.strip():
                    cur = conn.execute(
                        "INSERT INTO prizes (name, content) VALUES (?, ?)", 
                        (name, content.strip())
                    )
                    added_ids.append(cur.lastrowid)
        return added_ids

    def get_prizes_by_type(self):
        with self._conn() as conn:
            available = conn.execute("""
                SELECT name, COUNT(*) as count
                FROM prizes p
                WHERE p.id NOT IN (SELECT prize_id FROM claims)
                GROUP BY name
                ORDER BY count DESC
            """).fetchall()
            
            total = conn.execute("""
                SELECT name, COUNT(*) as count
                FROM prizes p
                GROUP BY name
                ORDER BY count DESC
            """).fetchall()
            
            return {"available": available, "total": total}

    def get_available_prizes(self):
        with self._conn() as conn:
            return conn.execute("""
                SELECT * FROM prizes
                WHERE id NOT IN (
                    SELECT prize_id FROM claims
                )
                ORDER BY created_at
            """).fetchall()

    def get_prize_by_id(self, prize_id: int) -> Optional[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM prizes WHERE id = ?", (prize_id,)).fetchone()

    def delete_prize(self, prize_id: int) -> bool:
        with self._conn() as conn:
            conn.execute("DELETE FROM claims WHERE prize_id = ?", (prize_id,))
            cur = conn.execute("DELETE FROM prizes WHERE id = ?", (prize_id,))
            return cur.rowcount > 0

    def claim_prize(self, prize_id: int, user_id: int) -> Optional[sqlite3.Row]:
        with self._conn() as conn:
            prize = conn.execute("""
                SELECT * FROM prizes
                WHERE id = ?
                AND id NOT IN (
                    SELECT prize_id FROM claims
                )
            """, (prize_id,)).fetchone()
            if not prize:
                return None
            conn.execute(
                "INSERT INTO claims (user_id, prize_id) VALUES (?, ?)",
                (user_id, prize_id)
            )
            return prize

    def give_prize_to_user(self, prize_id: int, user_id: int) -> Optional[sqlite3.Row]:
        return self.claim_prize(prize_id, user_id)

    # ── COOLDOWNS ───────────────────────────────────────────────
    def get_cooldown_minutes(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'cooldown_minutes'"
            ).fetchone()
            return int(row['value']) if row else DEFAULT_COOLDOWN_MINUTES

    def set_cooldown_minutes(self, minutes: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE settings SET value = ? WHERE key = 'cooldown_minutes'",
                (str(minutes),)
            )

    def reset_cooldown(self, user_id: int):
        with self._conn() as conn:
            conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            conn.execute(
                "INSERT OR REPLACE INTO cooldowns (user_id, reset_at) VALUES (?, datetime('now', '-1 day'))",
                (user_id,)
            )

    def get_cooldown_remaining(self, user_id: int):
        cooldown = self.get_cooldown_minutes()
        with self._conn() as conn:
            cooldown_row = conn.execute("SELECT reset_at FROM cooldowns WHERE user_id = ?", (user_id,)).fetchone()
            if cooldown_row:
                reset_at = datetime.strptime(cooldown_row['reset_at'], "%Y-%m-%d %H:%M:%S")
                elapsed = datetime.utcnow() - reset_at
                if elapsed >= timedelta(minutes=cooldown):
                    conn.execute("DELETE FROM cooldowns WHERE user_id = ?", (user_id,))
                    return True, None, None
                else:
                    return False, timedelta(minutes=cooldown) - elapsed, None
        
            last = self.get_last_claim(user_id)
            if not last:
                return True, None, None
            claimed_at = datetime.strptime(last['claimed_at'], "%Y-%m-%d %H:%M:%S")
            elapsed    = datetime.utcnow() - claimed_at
            limit      = timedelta(minutes=cooldown)
            if elapsed >= limit:
                return True, None, last
            return False, limit - elapsed, last

    # ── STATISTIQUES ─────────────────────────────────────────────
    def get_stats(self) -> dict:
        with self._conn() as conn:
            total_users  = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            blacklisted  = conn.execute("SELECT COUNT(*) FROM users WHERE blacklist = 1").fetchone()[0]
            total_prizes = conn.execute("SELECT COUNT(*) FROM prizes").fetchone()[0]
            total_claims  = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
            claimed_prizes = conn.execute("SELECT COUNT(DISTINCT prize_id) FROM claims").fetchone()[0]
            cooldown = self.get_cooldown_minutes()
            available = max(total_prizes - claimed_prizes, 0)
            return {
                "total_users":      total_users,
                "blacklisted":      blacklisted,
                "total_prizes":     total_prizes,
                "total_claims":     total_claims,
                "available_prizes": available,
                "claimed_prizes":   claimed_prizes,
                "cooldown_minutes": cooldown,
            }

    def get_last_claim(self, user_id: int) -> Optional[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute("""
                SELECT p.*, c.claimed_at
                FROM claims c
                JOIN prizes p ON p.id = c.prize_id
                WHERE c.user_id = ?
                ORDER BY c.claimed_at DESC
                LIMIT 1
            """, (user_id,)).fetchone()

    def get_all_prizes(self):
        with self._conn() as conn:
            return conn.execute("""
                SELECT p.*, u.username AS claimed_by, c.claimed_at
                FROM prizes p
                LEFT JOIN claims c ON c.prize_id = p.id
                LEFT JOIN users  u ON u.user_id  = c.user_id
                ORDER BY p.created_at DESC
            """).fetchall()

# ──────────────────────────────────────────────────────────
#  UTILITAIRES
# ──────────────────────────────────────────────────────────

db = Database()

def fmt_remaining(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}min"
    return f"{minutes}min {seconds}s"

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def extract_username(text: str) -> str:
    return text.strip().lstrip('@')

# ──────────────────────────────────────────────────────────
#  COMMANDES MEMBRES
# ──────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username)
    await asyncio.sleep(0.05)
    
    # Messages spéciaux pour les commandes de secours
    if update.message.text.startswith("/start2"):
        await update.message.reply_text(
            f"*🔄 Commande de secours #2 activée!*\n\n"
            f"Si `/start` ne répond pas, utilise `/start2`!\n\n"
            f"🎉 Bienvenue sur {BOT_NAME}!",
            parse_mode="Markdown"
        )
    elif update.message.text.startswith("/start3"):
        await update.message.reply_text(
            f"*🔄 Commande de secours #3 activée!*\n\n"
            f"Si `/start2` ne répond pas, utilise `/start3`!\n\n"
            f"🎉 Bienvenue sur {BOT_NAME}!",
            parse_mode="Markdown"
        )
    elif update.message.text.startswith("/start4"):
        await update.message.reply_text(
            f"*🔄 Commande de secours #4 activée!*\n\n"
            f"Si `/start3` ne répond pas, utilise `/start4`!\n\n"
            f"🎉 Bienvenue sur {BOT_NAME}!",
            parse_mode="Markdown"
        )
    elif update.message.text.startswith("/start5"):
        await update.message.reply_text(
            f"*🔄 Commande de secours #5 activée!*\n\n"
            f"Si `/start4` ne répond pas, utilise `/start5`!\n\n"
            f"🎉 Bienvenue sur {BOT_NAME}!",
            parse_mode="Markdown"
        )

    if db.is_blacklisted(user.id):
        await update.message.reply_text(
            f"🚫 Accès refusé, {user.first_name}.",
            parse_mode="Markdown"
        )
        return

    stats = db.get_stats()
    can_claim, remaining, last_claim = db.get_cooldown_remaining(user.id)

    if not can_claim:
        kb = [[InlineKeyboardButton("Rejoindre le canal", url=CANAL_LINK)]]
        await update.message.reply_text(
            f"*{BOT_NAME}*\n\n"
            f"⏰ Tu as déjà récupéré un prix récemment, {user.first_name}.\n\n"
            f"🎁 *{last_claim['name']}*\n"
            f"📄 `{last_claim['content']}`\n\n"
            f"🕐 Cooldown se termine dans *{fmt_remaining(remaining)}*",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        return

    prizes = db.get_available_prizes()

    if not prizes:
        kb = [[InlineKeyboardButton("Rejoindre le canal", url=CANAL_LINK)]]
        await update.message.reply_text(
            f"*{BOT_NAME}*\n\n"
            f"😔 Aucun prix disponible pour le moment, {user.first_name}.\n\n"
            f"🔄 De nouveaux drops arrivent bientôt.\n\n"
            f"_Reviens vérifier plus tard!_",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        return

    keyboard = [[InlineKeyboardButton(p['name'], callback_data=f"claim_{p['id']}")] for p in prizes]
    keyboard.append([InlineKeyboardButton("Rejoindre le canal", url=CANAL_LINK)])

    stock_info = db.get_prizes_by_type()
    stock_msg = ""
    if stock_info['available']:
        stock_msg = "\n📦 *Stock disponible:*\n"
        for item in stock_info['available'][:5]:
            stock_msg += f"  • {item['name']} (`{item['count']}`)\n"
        if len(stock_info['available']) > 5:
            stock_msg += f"  • ...et {len(stock_info['available']) - 5} autres types\n"

    await update.message.reply_text(
        f"*{BOT_NAME}*\n\n"
        f"🎉 Salut {user.first_name}, voilà les drops disponibles.{stock_msg}\n\n"
        f"🎁 *{stats['available_prizes']} prix au total*\n\n"
        f"_1 prix par fenêtre de {stats['cooldown_minutes']} min. Choisis bien._",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def claim_prize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    prize_id = int(query.data.split("_")[1])
    await asyncio.sleep(0.05)

    if db.is_blacklisted(user.id):
        await query.answer("🚫 Accès refusé.", show_alert=True)
        return

    can_claim, remaining, last_claim = db.get_cooldown_remaining(user.id)
    if not can_claim:
        kb = [[InlineKeyboardButton("Rejoindre le canal", url=CANAL_LINK)]]
        await query.edit_message_text(
            f"*{BOT_NAME}*\n\n"
            f"⏰ Tu as déjà récupéré un prix récemment.\n\n"
            f"🎁 *{last_claim['name']}*\n"
            f"📄 `{last_claim['content']}`\n\n"
            f"🕐 Cooldown se termine dans *{fmt_remaining(remaining)}*",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        return

    prize = db.claim_prize(prize_id, user.id)
    if not prize:
        await query.answer("❌ Ce prix n'est plus disponible.", show_alert=True)
        return

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"🎉 *Nouveau claim!*\n\n"
                f"👤 @{user.username or user.first_name}\n"
                f"🎁 {prize['name']}\n"
                f"📄 `{prize['content']}`",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    kb = [[InlineKeyboardButton("Rejoindre le canal", url=CANAL_LINK)]]
    await query.edit_message_text(
        f"*{BOT_NAME}*\n\n"
        f"✅ Félicitations {user.first_name}!\n\n"
        f"🎁 *{prize['name']}*\n"
        f"📄 `{prize['content']}`\n\n"
        f"🎉 Profite bien!\n\n"
        f"_Prochain drop dans {db.get_cooldown_minutes()} min._",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

# ──────────────────────────────────────────────────────────
#  COMMANDES ADMIN
# ──────────────────────────────────────────────────────────

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    
    s = db.get_stats()
    await update.message.reply_text(
        f"*🎛️ PANEL ADMIN — {BOT_NAME}*\n\n"
        f"*📊 STATISTIQUES ACTUELLES*\n"
        f"👥 Membres : `{s['total_users']}`\n"
        f"🚫 Blacklistés : `{s['blacklisted']}`\n"
        f"🎁 Prix totaux : `{s['total_prizes']}`\n"
        f"✅ Disponibles : `{s['available_prizes']}`\n"
        f"📋 Réclamés : `{s['claimed_prizes']}`\n"
        f"⏰ Cooldown : `{s['cooldown_minutes']}` min\n\n"
        f"*🎁 GESTION DES PRIX*\n"
        f"/add `<nom>` — Ajouter un prix simple\n"
        f"/bulk `<nom>` `<quantité>` — Ajouter plusieurs comptes\n"
        f"/del `<id>` — Supprimer un prix\n"
        f"/list — Voir le stock par type\n"
        f"/give `<@username>` `<id>` — Donner un prix directement\n\n"
        f"*👥 GESTION DES MEMBRES*\n"
        f"/members — Liste des membres\n"
        f"/stats — Statistiques détaillées\n"
        f"/reset `<@username>` — Reset cooldown d'un membre\n"
        f"/blacklist `<@username>` — Bannir/Débannir\n\n"
        f"*📡 COMMUNICATION*\n"
        f"/broadcast `<message>` — Message texte à tous\n"
        f"/broadcastphoto — Message photo+texte à tous\n\n"
        f"*⚙️ CONFIGURATION*\n"
        f"/cooldown `<minutes>` — Changer le cooldown\n\n"
        f"_Version ultra-stable avec toutes les commandes!_ 🚀",
        parse_mode="Markdown"
    )

async def admin_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("📝 Usage : `/add Nom du prix`", parse_mode="Markdown")
        return
    prize_name = " ".join(context.args)
    context.user_data['pending_prize_name'] = prize_name
    await update.message.reply_text(
        f"📝 Nom : *{prize_name}*\n\nEnvoie maintenant le contenu :",
        parse_mode="Markdown"
    )

async def admin_bulk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("📦 Usage : `/bulk Nom du prix quantité`", parse_mode="Markdown")
        return
    
    parts = context.args
    if len(parts) < 2:
        await update.message.reply_text("📦 Usage : `/bulk Nom du prix quantité`", parse_mode="Markdown")
        return
    
    try:
        quantity = int(parts[-1])
        prize_name = " ".join(parts[:-1])
    except ValueError:
        await update.message.reply_text("❌ La quantité doit être un nombre.", parse_mode="Markdown")
        return
    
    context.user_data['pending_bulk_name'] = prize_name
    context.user_data['pending_bulk_quantity'] = quantity
    await update.message.reply_text(
        f"📦 *{prize_name}* × {quantity}\n\n"
        f"Envoie maintenant les {quantity} comptes (un par ligne) :",
        parse_mode="Markdown"
    )

async def admin_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("🗑️ Usage : `/del <id>`", parse_mode="Markdown")
        return
    try:
        prize_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ L'ID doit être un nombre.", parse_mode="Markdown")
        return
    
    prize = db.get_prize_by_id(prize_id)
    if not prize:
        await update.message.reply_text(f"❌ Prix #{prize_id} introuvable.", parse_mode="Markdown")
        return
    
    if db.delete_prize(prize_id):
        await update.message.reply_text(
            f"✅ Prix supprimé !\n\n🗑️ *{prize['name']}* (ID: {prize_id})",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ Erreur lors de la suppression.", parse_mode="Markdown")

async def admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    
    stock = db.get_prizes_by_type()
    
    if not stock['total']:
        await update.message.reply_text("📦 Aucun prix dans la base.")
        return
    
    msg = "📦 *Stock des comptes*\n\n"
    
    if stock['available']:
        msg += "🟢 *Disponibles:*\n"
        for item in stock['available']:
            msg += f"  🎁 {item['name']} (`{item['count']}`)\n"
        msg += "\n"
    
    msg += "📊 *Total en stock:*\n"
    for item in stock['total']:
        available_count = next((a['count'] for a in stock['available'] if a['name'] == item['name']), 0)
        claimed_count = item['count'] - available_count
        msg += f"  📦 {item['name']}: `{available_count}`/{item['count']} "
        if claimed_count > 0:
            msg += f"(`{claimed_count}` réclamés)"
        msg += "\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def admin_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    
    users = db.get_all_users()
    if not users:
        await update.message.reply_text("👥 Aucun membre enregistré.")
        return
    
    msg = f"👥 *Liste des membres ({len(users)})*\n\n"
    for i, user in enumerate(users[:20]):
        status = "🚫" if user['blacklist'] else "✅"
        username = f"@{user['username']}" if user['username'] else f"ID: {user['user_id']}"
        msg += f"{i+1}. {status} {username}\n"
    
    if len(users) > 20:
        msg += f"\n_...et {len(users)-20} autres membres_"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    
    s = db.get_stats()
    await update.message.reply_text(
        f"📊 *Statistiques détaillées*\n\n"
        f"*👥 Utilisateurs*\n"
        f"Total : `{s['total_users']}`\n"
        f"Blacklistés : `{s['blacklisted']}`\n"
        f"Actifs : `{s['total_users'] - s['blacklisted']}`\n\n"
        f"*🎁 Prix*\n"
        f"Total créés : `{s['total_prizes']}`\n"
        f"Disponibles : `{s['available_prizes']}`\n"
        f"Réclamés : `{s['claimed_prizes']}`\n"
        f"Claims totaux : `{s['total_claims']}`\n\n"
        f"*⏰ Configuration*\n"
        f"Cooldown : `{s['cooldown_minutes']}` minutes\n\n"
        f"*📈 Taux de conversion*\n"
        f"{round(s['claimed_prizes']/s['total_prizes']*100, 1) if s['total_prizes'] > 0 else 0}% des prix réclamés",
        parse_mode="Markdown"
    )

async def admin_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("🔄 Usage : `/reset @username`", parse_mode="Markdown")
        return
    
    username = extract_username(context.args[0])
    user = db.get_user_by_username(username)
    
    if not user:
        await update.message.reply_text(f"❌ Utilisateur @{username} introuvable.", parse_mode="Markdown")
        return
    
    db.reset_cooldown(user['user_id'])
    await update.message.reply_text(
        f"✅ Cooldown reset pour @{username} !\n\n"
        f"🔄 Il peut maintenant réclamer un prix immédiatement.",
        parse_mode="Markdown"
    )

async def admin_give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if len(context.args) < 2:
        await update.message.reply_text("🎁 Usage : `/give @username <id_prix>`", parse_mode="Markdown")
        return
    
    username = extract_username(context.args[0])
    try:
        prize_id = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ L'ID du prix doit être un nombre.", parse_mode="Markdown")
        return
    
    user = db.get_user_by_username(username)
    if not user:
        await update.message.reply_text(f"❌ Utilisateur @{username} introuvable.", parse_mode="Markdown")
        return
    
    prize = db.give_prize_to_user(prize_id, user['user_id'])
    if not prize:
        await update.message.reply_text(f"❌ Prix #{prize_id} indisponible.", parse_mode="Markdown")
        return
    
    await update.message.reply_text(
        f"✅ Prix donné !\n\n"
        f"🎁 *{prize['name']}* → @{username}\n"
        f"📄 `{prize['content']}`",
        parse_mode="Markdown"
    )

async def admin_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("🚫 Usage : `/blacklist @username`", parse_mode="Markdown")
        return
    
    username = extract_username(context.args[0])
    user = db.get_user_by_username(username)
    
    if not user:
        await update.message.reply_text(f"❌ Utilisateur @{username} introuvable.", parse_mode="Markdown")
        return
    
    is_blacklisted = db.toggle_blacklist(user['user_id'])
    status = "🚫 **BANNI**" if is_blacklisted else "✅ **AUTORISÉ**"
    
    await update.message.reply_text(
        f"✅ Statut modifié !\n\n"
        f"👤 @{username} : {status}",
        parse_mode="Markdown"
    )

async def admin_cooldown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("⏰ Usage : `/cooldown <minutes>`", parse_mode="Markdown")
        return
    
    try:
        minutes = int(context.args[0])
        if minutes < 1 or minutes > 1440:
            await update.message.reply_text("❌ Le cooldown doit être entre 1 et 1440 minutes.", parse_mode="Markdown")
            return
    except ValueError:
        await update.message.reply_text("❌ Le cooldown doit être un nombre.", parse_mode="Markdown")
        return
    
    db.set_cooldown_minutes(minutes)
    await update.message.reply_text(
        f"✅ Cooldown modifié !\n\n"
        f"⏰ Nouveau cooldown : `{minutes}` minutes",
        parse_mode="Markdown"
    )

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("📡 Usage : `/broadcast <message>`", parse_mode="Markdown")
        return
    
    message = " ".join(context.args)
    users = db.get_all_users()
    
    if not users:
        await update.message.reply_text("👥 Aucun membre à notifier.", parse_mode="Markdown")
        return
    
    sent = 0
    failed = 0
    
    status_msg = await update.message.reply_text(
        f"📡 Envoi du broadcast en cours...\n\n"
        f"👥 Cible : {len(users)} membres",
        parse_mode="Markdown"
    )
    
    for user in users:
        if user['blacklist']:
            continue
        try:
            await context.bot.send_message(
                user['user_id'],
                f"*📡 Annonce {BOT_NAME}*\n\n{message}",
                parse_mode="Markdown"
            )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    
    await status_msg.edit_text(
        f"✅ Broadcast terminé !\n\n"
        f"📤 Envoyés : `{sent}`\n"
        f"❌ Échoués : `{failed}`",
        parse_mode="Markdown"
    )

async def admin_broadcastphoto_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    
    context.user_data['pending_broadcast_photo'] = True
    await update.message.reply_text(
        "📸 Envoie maintenant la photo\n\n"
        "Ajoute une légende si tu veux (optionnel) :",
        parse_mode="Markdown"
    )

async def admin_broadcastphoto_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.user_data.get('pending_broadcast_photo'):
        return
    
    context.user_data.pop('pending_broadcast_photo')
    
    if not update.message.photo:
        await update.message.reply_text("❌ Envoie une photo valide.", parse_mode="Markdown")
        return
    
    photo = update.message.photo[-1]
    caption = update.message.caption or ""
    
    users = db.get_all_users()
    if not users:
        await update.message.reply_text("👥 Aucun membre à notifier.", parse_mode="Markdown")
        return
    
    sent = 0
    failed = 0
    
    status_msg = await update.message.reply_text(
        f"📸 Envoi de la photo en cours...\n\n"
        f"👥 Cible : {len(users)} membres",
        parse_mode="Markdown"
    )
    
    for user in users:
        if user['blacklist']:
            continue
        try:
            full_caption = f"*📸 {BOT_NAME}*\n\n{caption}" if caption else f"*📸 {BOT_NAME}*"
            await context.bot.send_photo(
                user['user_id'],
                photo=photo,
                caption=full_caption,
                parse_mode="Markdown"
            )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    
    await status_msg.edit_text(
        f"✅ Broadcast photo terminé !\n\n"
        f"📤 Envoyés : `{sent}`\n"
        f"❌ Échoués : `{failed}`",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await asyncio.sleep(0.1)

    if 'pending_bulk_name' in context.user_data:
        name = context.user_data.pop('pending_bulk_name')
        quantity = context.user_data.pop('pending_bulk_quantity')
        contents = update.message.text.split('\n')
        
        if len(contents) < quantity:
            await update.message.reply_text(
                f"❌ Tu n'as envoyé que {len(contents)} comptes au lieu des {quantity} demandés.",
                parse_mode="Markdown"
            )
            return
        
        added_ids = db.add_bulk_prizes(name, contents[:quantity])
        await update.message.reply_text(
            f"✅ {len(added_ids)} comptes *{name}* ajoutés !\n\n"
            f"📦 Stock total : {len(added_ids)} comptes",
            parse_mode="Markdown"
        )
        return

    if 'pending_prize_name' not in context.user_data: return
    name     = context.user_data.pop('pending_prize_name')
    content  = update.message.text
    prize_id = db.add_prize(name, content)
    await update.message.reply_text(
        f"✅ Prix ajouté !\n\n🆔 ID : `{prize_id}` · *{name}*\n📄 Contenu : `{content}`",
        parse_mode="Markdown"
    )

# ──────────────────────────────────────────────────────────
#  FONCTION PRINCIPALE
# ──────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("start2", start))
    app.add_handler(CommandHandler("start3", start))
    app.add_handler(CommandHandler("start4", start))
    app.add_handler(CommandHandler("start5", start))

    app.add_handler(CommandHandler("help", admin_help))
    app.add_handler(CommandHandler("add", admin_add))
    app.add_handler(CommandHandler("bulk", admin_bulk))
    app.add_handler(CommandHandler("del", admin_delete))
    app.add_handler(CommandHandler("list", admin_list))
    app.add_handler(CommandHandler("members", admin_members))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("reset", admin_reset))
    app.add_handler(CommandHandler("give", admin_give))
    app.add_handler(CommandHandler("blacklist", admin_blacklist))
    app.add_handler(CommandHandler("cooldown", admin_cooldown))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(CommandHandler("broadcastphoto", admin_broadcastphoto_init))
    
    app.add_handler(CallbackQueryHandler(claim_prize, pattern=r"^claim_\d+$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot hébergement prêt! Ultra-stable!")
    app.run_polling()

if __name__ == '__main__':
    main()
