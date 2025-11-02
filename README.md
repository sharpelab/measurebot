# MeasureBot

Simple bot for notifications via Discord and email.

## Setup

1. **Install dependencies:**
   ```bash
   pip install requests
   ```

2. **Configure:**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. **Run:**
   ```bash
   python measurebot/alerts.py
   ```

## Usage

### IPython/Jupyter Setup (Recommended)

```python
# Set up defaults once per session
from measurebot.alerts import set_defaults, discord, email, alert

set_defaults(
    discord_channel="alerts", 
    discord_user="aaron", 
    email_user="aaron"
)

# Now use short, simple calls
discord("Sample is ready!")
email("Sample is ready!", "Lab Alert")
alert("Critical: Temperature high!")  # Sends both Discord + email
```

### Full Function Calls

```python
from measurebot.alerts import send_discord_message, send_email

# Send Discord message
send_discord_message("System alert!", channel="alerts", user="aaron")

# Send email to specific user
send_email("Important notification", subject="Alert", to_user="aaron")

# Send email to direct address
send_email("Important notification", subject="Alert", to_email="someone@example.com")
```

## Configuration

Edit `.env` file:

```bash
# Discord (optional)
DISCORD_BOT_TOKEN=your-bot-token
DISCORD_CHANNEL_ALERTS=channel-id
DISCORD_USER_AARON=user-id

# Email (required for email notifications)
SMTP_PASS=your-resend-api-key
EMAIL_FROM=sender@yourdomain.com

# Email recipients (choose one method)
EMAIL_TO=default@example.com              # Default recipient
# OR use named recipients:
EMAIL_TO_AARON=aaron@example.com          # Send to specific users
EMAIL_TO_ADMIN=admin@example.com
```

That's it!
