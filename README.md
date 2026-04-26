# Drop Zone Telegram Bot

Bot Telegram ultra-stable pour distribuer des comptes premium avec gestion complète.

## 🚀 Installation Rapide

1. **Clonez et installez :**
   ```bash
   git clone <repository>
   cd drop-zone-bot
   pip install -r requirements.txt
   ```

2. **Configurez le token :**
   - Éditez `bot.py`
   - Changez `BOT_TOKEN` et `ADMIN_IDS`

3. **Lancez :**
   ```bash
   python bot.py
   ```

## 📋 Commandes Admin

### 🎁 Gestion des Prix
- `/add <nom>` - Ajouter un prix simple
- `/bulk <nom> <quantité>` - Ajouter plusieurs comptes d'un coup
- `/del <id>` - Supprimer un prix
- `/list` - Voir le stock par type

### 👥 Gestion des Membres  
- `/members` - Liste des membres
- `/stats` - Statistiques détaillées
- `/reset <@username>` - Reset cooldown
- `/blacklist <@username>` - Bannir/Débannir

### 📡 Communication
- `/broadcast <message>` - Message à tous
- `/help` - Panel admin complet

## 🎯 Commandes Membres

- `/start` - Voir les prix disponibles
- **1 prix par cooldown de 60 minutes**

## 🌐 Hébergement (Railway.app)

1. **Upload sur GitHub**
2. **Railway.app** → "New Project" → "Deploy from GitHub"
3. **Variables d'environnement :**
   ```
   BOT_TOKEN=votre_token_telegram
   PORT=5000
   ```
4. **Déployez automatiquement !**

## 📊 Fonctionnalités

✅ **Base de données SQLite** intégrée  
✅ **Cooldown anti-spam** intelligent  
✅ **Stock par type** (Netflix: 5, Disney+: 3...)  
✅ **Bulk add** - Ajoute 50+ comptes en 1 commande  
✅ **Panel admin** ultra-complet  
✅ **Notifications admin** pour chaque réclamation  

## 🔧 Configuration

Dans `bot.py` :
```python
BOT_TOKEN = "8777662417:AAFA5Nv6bHOQbE8Vd5xJeQ8L9fUze45abcg"
ADMIN_IDS = [8178183186]  # Votre ID Telegram
BOT_NAME = "Drop Zone"
CANAL_LINK = "https://t.me/+pHwsFHqrYP0xYzNl"
```

## 🛡️ Sécurité

- Blacklist automatique
- Cooldown par utilisateur
- Validation des entrées
- Logs admin complets

## 📈 Performance

- **Ultra-léger** : 1 seul fichier Python
- **Ultra-rapide** : Base SQLite optimisée
- **Ultra-stable** : Pas de conflits d'instances
- **24/7** : Hébergement Railway gratuit

---

**Prêt pour l'hébergement en 2 minutes !** 🚀és 🔥
→ Envoie ce message en DM à TOUS les membres

- Chaque membre qui fait `/start` voit les prix dispos avec des boutons
- Il peut en choisir **1 seul** → le prix est immédiatement retiré pour les autres
- Toi tu reçois une notif à chaque claim
- Le bot sauvegarde tous les membres → tu peux les DM via `/broadcast`
- Base de données SQLite locale (`bot.db`) → aucun service externe requis

## Pour héberger 24/7 (optionnel)

- **Gratuit** : Railway.app, Render.com
- **Payant** : VPS OVH (~3€/mois), Hetzner
