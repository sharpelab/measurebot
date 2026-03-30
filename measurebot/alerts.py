import os
import re
import smtplib
from pathlib import Path

import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load environment variables from .env file if it exists.
# Search order: $MEASUREBOT_ENV, ~/.config/measurebot/.env, cwd/.env, package-adjacent .env
def _find_env_file():
    explicit = os.environ.get("MEASUREBOT_ENV")
    if explicit and os.path.isfile(explicit):
        return explicit
    config_env = Path.home() / ".config" / "measurebot" / ".env"
    if config_env.is_file():
        return str(config_env)
    cwd_env = os.path.join(os.getcwd(), ".env")
    if os.path.isfile(cwd_env):
        return cwd_env
    pkg_env = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.isfile(pkg_env):
        return pkg_env
    return None

_env_file = _find_env_file()
if _env_file:
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                # Remove quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                os.environ[key] = value

# Discord configuration
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Build channel map from env: DISCORD_CHANNEL_<NAME>=<ID>
CHANNELS = {
    m.group(1).lower(): v
    for k, v in os.environ.items()
    if (m := re.match(r"DISCORD_CHANNEL_([A-Z0-9_-]+)", k, re.IGNORECASE))
}

# Build user map from env: DISCORD_USER_<USERNAME>=<ID>
USERS = {
    m.group(1).lower(): v
    for k, v in os.environ.items()
    if (m := re.match(r"DISCORD_USER_([A-Z0-9_-]+)", k, re.IGNORECASE))
}

# Build email recipients map from env: EMAIL_TO_<USERNAME>=<EMAIL>
EMAIL_RECIPIENTS = {
    m.group(1).lower(): v
    for k, v in os.environ.items()
    if (m := re.match(r"EMAIL_TO_([A-Z0-9_-]+)", k, re.IGNORECASE))
}

# Slack configuration
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")

# Build Slack channel map from env: SLACK_CHANNEL_<NAME>=<ID>
SLACK_CHANNELS = {
    m.group(1).lower(): v
    for k, v in os.environ.items()
    if (m := re.match(r"SLACK_CHANNEL_([A-Z0-9_-]+)", k, re.IGNORECASE))
}

# Build Slack user map from env: SLACK_USER_<USERNAME>=<ID>
SLACK_USERS = {
    m.group(1).lower(): v
    for k, v in os.environ.items()
    if (m := re.match(r"SLACK_USER_([A-Z0-9_-]+)", k, re.IGNORECASE))
}

# SMTP configuration
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.resend.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "resend")
SMTP_PASS = os.getenv("SMTP_PASS")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_TO = os.getenv("EMAIL_TO")  # Keep for backward compatibility


# --- Resolvers ---
# Accept registry names OR raw IDs/addresses. Auto-detect based on format.

def _to_list(val):
    """Normalize None, a string, or a list of strings to a list."""
    if val is None:
        return []
    return val if isinstance(val, list) else [val]


def _resolve_discord_users(raw: str | list[str] | None) -> list[tuple[str, str]]:
    """Resolve Discord user references to (label, user_id) pairs.

    Accepts registry names (e.g. "asharpe") or raw numeric user IDs.
    """
    results = []
    for item in _to_list(raw):
        if item.isdigit():
            results.append((item, item))
        elif item.lower() in USERS:
            results.append((item, USERS[item.lower()]))
        else:
            available = ", ".join(USERS.keys()) if USERS else "None"
            print(f"❌ Discord: unknown user '{item}'. Available: {available}")
    return results


def _resolve_slack_users(raw: str | list[str] | None) -> list[tuple[str, str]]:
    """Resolve Slack user references to (label, user_id) pairs.

    Accepts registry names (e.g. "asharpe") or raw Slack user IDs (e.g. "U02HE4J1279").
    """
    results = []
    for item in _to_list(raw):
        if item.startswith("U") and len(item) > 1 and item[1:].isalnum():
            results.append((item, item))
        elif item.lower() in SLACK_USERS:
            results.append((item, SLACK_USERS[item.lower()]))
        else:
            available = ", ".join(SLACK_USERS.keys()) if SLACK_USERS else "None"
            print(f"❌ Slack: unknown user '{item}'. Available: {available}")
    return results


def _resolve_emails(raw: str | list[str] | None) -> list[tuple[str, str]]:
    """Resolve email references to (label, address) pairs.

    Accepts registry names (e.g. "asharpe") or raw email addresses.
    """
    results = []
    for item in _to_list(raw):
        if "@" in item:
            results.append((item, item))
        elif item.lower() in EMAIL_RECIPIENTS:
            results.append((item, EMAIL_RECIPIENTS[item.lower()]))
        else:
            available = ", ".join(EMAIL_RECIPIENTS.keys()) if EMAIL_RECIPIENTS else "None"
            print(f"❌ Email: unknown user '{item}'. Available: {available}")
    return results


# Configuration class for IPython usage
class Config:
    """Simple configuration for default channels and users."""
    discord_channel = None
    discord_user = None
    slack_channel = None
    slack_user = None
    email_user = None

    @classmethod
    def set_defaults(cls, discord_user=None, slack_channel=None, slack_user=None, email_user=None):
        """Set default values for notifications.

        Args:
            discord_user: Default Discord user(s) - registry name(s) or raw ID(s)
            slack_channel: Default Slack channel name
            slack_user: Default Slack user(s) - registry name(s) or raw ID(s)
            email_user: Default email user(s) - registry name(s) or raw address(es)
        """
        cls.discord_user = discord_user
        cls.slack_channel = slack_channel
        cls.slack_user = slack_user
        cls.email_user = email_user

        print(f"✅ Defaults set:")
        if discord_user:
            if isinstance(discord_user, list):
                print(f"   Discord users: {', '.join([f'@{u}' for u in discord_user])}")
            else:
                print(f"   Discord user: @{discord_user}")
        if slack_channel:
            print(f"   Slack channel: #{slack_channel}")
        if slack_user:
            if isinstance(slack_user, list):
                print(f"   Slack users: {', '.join([f'@{u}' for u in slack_user])}")
            else:
                print(f"   Slack user: @{slack_user}")
        if email_user:
            if isinstance(email_user, list):
                print(f"   Email users: {', '.join(email_user)}")
            else:
                print(f"   Email user: {email_user}")


# Global config instance
config = Config()


def send_discord_dm(message: str, user: str | list[str] | None = None):
    """Send a Discord direct message to user(s).

    Args:
        message: Message to send
        user: Registry name(s) or raw Discord user ID(s)
    """
    user = user or config.discord_user

    if not BOT_TOKEN:
        print("❌ Discord: BOT_TOKEN not configured")
        return False

    resolved = _resolve_discord_users(user)
    if not resolved:
        print("❌ Discord: No valid users for DM")
        return False

    success_count = 0
    dm_headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}

    for label, user_id in resolved:
        try:
            dm_response = requests.post(
                "https://discord.com/api/v10/users/@me/channels",
                headers=dm_headers,
                json={"recipient_id": user_id},
            )
            dm_response.raise_for_status()
            dm_channel_id = dm_response.json()["id"]

            msg_response = requests.post(
                f"https://discord.com/api/v10/channels/{dm_channel_id}/messages",
                headers=dm_headers,
                json={"content": message},
            )
            msg_response.raise_for_status()
            print(f"✅ Discord DM: sent to @{label}")
            success_count += 1
        except requests.exceptions.RequestException as e:
            print(f"❌ Discord DM: failed to send to @{label} - {e}")

    return success_count == len(resolved)


def send_discord_channel_message(message: str, channel: str | None = None, user: str | list[str] | None = None):
    """Send a Discord message to a named channel, optionally mentioning user(s).

    Args:
        message: Message to send
        channel: Discord channel name
        user: Registry name(s) or raw Discord user ID(s) to mention
    """
    channel = channel or config.discord_channel or "alerts"
    user = user or config.discord_user

    if not BOT_TOKEN:
        print("❌ Discord: BOT_TOKEN not configured")
        return False
    if channel not in CHANNELS:
        available = ", ".join(CHANNELS.keys()) if CHANNELS else "None"
        print(f"❌ Discord: channel '{channel}' not found. Available: {available}")
        return False

    channel_id = CHANNELS[channel]
    headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}

    resolved = _resolve_discord_users(user)

    if resolved:
        mentions = [f"<@{uid}>" for _, uid in resolved]
        labels = [label for label, _ in resolved]
        full_message = f"{' '.join(mentions)} {message}"
        payload = {
            "content": full_message,
            "allowed_mentions": {"users": [uid for _, uid in resolved]}
        }
    else:
        payload = {"content": message}

    try:
        r = requests.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers=headers, json=payload,
        )
        r.raise_for_status()
        if resolved:
            print(f"✅ Discord: sent to #{channel} (mentioning {', '.join(f'@{l}' for l in labels)})")
        else:
            print(f"✅ Discord: sent to #{channel}")
        return True
    except Exception as e:
        print(f"❌ Discord: failed to send to #{channel} - {e}")
        return False


def send_email(message: str, subject: str = "MeasureBot Notification", to_user: str | list[str] | None = None, to_email: str | list[str] | None = None, from_email: str | None = None):
    """Send an email notification via SMTP.

    Args:
        message: Email message content
        subject: Email subject line
        to_user: Registry name(s) or raw email address(es)
        to_email: Direct email address(es) (merged with to_user)
        from_email: Sender email (defaults to EMAIL_FROM)
    """
    from_addr = from_email or EMAIL_FROM
    to_user = to_user or config.email_user

    # Merge to_email and to_user — resolver handles both raw addresses and names
    all_inputs = _to_list(to_email) + _to_list(to_user)

    if all_inputs:
        resolved = _resolve_emails(all_inputs)
        # Deduplicate by address
        seen = set()
        to_addresses = []
        for _, addr in resolved:
            if addr not in seen:
                seen.add(addr)
                to_addresses.append(addr)
    elif EMAIL_TO:
        to_addresses = [EMAIL_TO]
    else:
        to_addresses = []

    if not SMTP_PASS:
        print("❌ Email: SMTP_PASS not configured")
        return False
    if not from_addr:
        print("❌ Email: EMAIL_FROM not configured")
        return False
    if not to_addresses:
        print("❌ Email: no recipients specified and no default EMAIL_TO")
        return False

    success_count = 0

    for to_addr in to_addresses:
        msg = MIMEMultipart()
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.attach(MIMEText(message, "plain"))

        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
            success_count += 1
        except Exception as e:
            print(f"❌ Email: failed to send to {to_addr} - {e}")

    if success_count > 0:
        total_count = len(to_addresses)
        if total_count == 1:
            print(f"✅ Email: sent to {to_addresses[0]}")
        else:
            print(f"✅ Email: sent to {success_count}/{total_count} recipients ({', '.join(to_addresses[:3])}{'...' if len(to_addresses) > 3 else ''})")
        return success_count == total_count
    else:
        return False


# Slack functions
def send_slack_dm(message: str, user: str | list[str] | None = None):
    """Send a Slack direct message to user(s).

    Args:
        message: Message to send
        user: Registry name(s) or raw Slack user ID(s)
    """
    user = user or config.slack_user

    if not SLACK_TOKEN:
        print("❌ Slack: SLACK_BOT_TOKEN not configured")
        return False

    resolved = _resolve_slack_users(user)
    if not resolved:
        print("❌ Slack: No valid users for DM")
        return False

    success_count = 0
    headers = {
        "Authorization": f"Bearer {SLACK_TOKEN}",
        "Content-Type": "application/json",
    }

    for label, user_id in resolved:
        try:
            open_resp = requests.post(
                "https://slack.com/api/conversations.open",
                headers=headers,
                json={"users": user_id},
            )
            open_data = open_resp.json()

            if not open_data.get("ok"):
                print(f"❌ Slack DM: failed to open channel with @{label} - {open_data.get('error', 'Unknown error')}")
                continue

            dm_channel_id = open_data["channel"]["id"]

            send_resp = requests.post(
                "https://slack.com/api/chat.postMessage",
                headers=headers,
                json={"channel": dm_channel_id, "text": message},
            )
            send_data = send_resp.json()

            if send_data.get("ok"):
                print(f"✅ Slack DM: sent to @{label}")
                success_count += 1
            else:
                print(f"❌ Slack DM: failed to send to @{label} - {send_data.get('error', 'Unknown error')}")

        except requests.exceptions.RequestException as e:
            print(f"❌ Slack DM: failed to send to @{label} - {e}")

    return success_count == len(resolved)


def send_slack_channel_message(message: str, channel: str | None = None, user: str | list[str] | None = None):
    """Send a Slack message to a named channel, optionally mentioning user(s).

    Args:
        message: Message to send
        channel: Slack channel name
        user: Registry name(s) or raw Slack user ID(s) to mention
    """
    channel = channel or config.slack_channel or "general"
    user = user or config.slack_user

    if not SLACK_TOKEN:
        print("❌ Slack: SLACK_BOT_TOKEN not configured")
        return False
    if channel not in SLACK_CHANNELS:
        available = ", ".join(SLACK_CHANNELS.keys()) if SLACK_CHANNELS else "None"
        print(f"❌ Slack: channel '{channel}' not found. Available: {available}")
        return False

    channel_id = SLACK_CHANNELS[channel]
    headers = {"Authorization": f"Bearer {SLACK_TOKEN}", "Content-Type": "application/json"}

    resolved = _resolve_slack_users(user)

    if resolved:
        mentions = [f"<@{uid}>" for _, uid in resolved]
        labels = [label for label, _ in resolved]
        full_message = f"{' '.join(mentions)} {message}"
    else:
        full_message = message

    payload = {
        "channel": channel_id,
        "text": full_message
    }

    try:
        r = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers=headers, json=payload,
        )
        r.raise_for_status()
        response_data = r.json()

        if response_data.get("ok"):
            if resolved:
                print(f"✅ Slack: sent to #{channel} (mentioning {', '.join(f'@{l}' for l in labels)})")
            else:
                print(f"✅ Slack: sent to #{channel}")
            return True
        else:
            print(f"❌ Slack: failed to send to #{channel} - {response_data.get('error', 'Unknown error')}")
            return False
    except Exception as e:
        print(f"❌ Slack: failed to send to #{channel} - {e}")
        return False


# Main Discord function - now defaults to DMs
def send_discord_message(message: str, user: str | list[str] | None = None):
    """Send a Discord direct message to user(s). This is now the default behavior."""
    return send_discord_dm(message, user)


# Main Slack function - uses channel @mentions if available, falls back to DMs
def send_slack_message(message: str, user: str | list[str] | None = None, channel: str | None = None):
    """Send a Slack message with @mentions for reliable phone notifications, or DM if no channel."""
    channel = channel or config.slack_channel
    if channel and channel in SLACK_CHANNELS:
        return send_slack_channel_message(message, channel, user)
    else:
        return send_slack_dm(message, user)


# Convenience functions
def set_defaults(discord_user=None, slack_user=None, slack_channel=None, email_user=None):
    """Set default values for notifications. Use this in IPython for convenience.

    All user parameters accept registry names, raw IDs/addresses, or lists mixing both.
    """
    config.set_defaults(discord_user=discord_user, slack_user=slack_user, slack_channel=slack_channel, email_user=email_user)


def discord(message: str, user: str | list[str] | None = None):
    """Short alias for send_discord_message (DMs)."""
    return send_discord_message(message, user)


def slack(message: str, user: str | list[str] | None = None):
    """Short alias for send_slack_message."""
    return send_slack_message(message, user)


def discord_channel(message: str, channel: str | None = None, user: str | list[str] | None = None):
    """Send to a Discord channel."""
    return send_discord_channel_message(message, channel, user)


def slack_channel(message: str, channel: str | None = None, user: str | list[str] | None = None):
    """Send to a Slack channel."""
    return send_slack_channel_message(message, channel, user)


def email(message: str, subject: str = "MeasureBot Notification", to_user: str | list[str] | None = None, to_email: str | list[str] | None = None):
    """Short alias for send_email."""
    return send_email(message, subject, to_user, to_email)


def alert(message: str, subject: str = "MeasureBot Alert"):
    """Send Discord DM, Slack, and email notifications using defaults."""
    discord_ok = send_discord_message(message)
    slack_ok = send_slack_message(message)
    email_ok = send_email(message, subject)
    return discord_ok and slack_ok and email_ok


def show_config():
    """Display current configuration and available options."""
    print("=== MeasureBot Configuration ===")

    if config.discord_user:
        if isinstance(config.discord_user, list):
            print(f"Default Discord users: {', '.join([f'@{u}' for u in config.discord_user])}")
        else:
            print(f"Default Discord user: @{config.discord_user}")
    else:
        print("Default Discord user: None")

    if config.slack_channel:
        print(f"Default Slack channel: #{config.slack_channel}")
    else:
        print("Default Slack channel: None")

    if config.slack_user:
        if isinstance(config.slack_user, list):
            print(f"Default Slack users: {', '.join([f'@{u}' for u in config.slack_user])}")
        else:
            print(f"Default Slack user: @{config.slack_user}")
    else:
        print("Default Slack user: None")

    if config.email_user:
        if isinstance(config.email_user, list):
            print(f"Default email users: {', '.join(config.email_user)}")
        else:
            print(f"Default email user: {config.email_user}")
    else:
        print("Default email user: None")

    print()
    print("Available Discord users:", ", ".join(USERS.keys()) if USERS else "None")
    print("Available Slack channels:", ", ".join(SLACK_CHANNELS.keys()) if SLACK_CHANNELS else "None")
    print("Available Slack users:", ", ".join(SLACK_USERS.keys()) if SLACK_USERS else "None")
    print("Available email users:", ", ".join(EMAIL_RECIPIENTS.keys()) if EMAIL_RECIPIENTS else "None")
    print()
    print("Configuration status:")
    print(f"  Discord BOT_TOKEN: {'✅ Set' if BOT_TOKEN else '❌ Missing'}")
    print(f"  Slack BOT_TOKEN: {'✅ Set' if SLACK_TOKEN else '❌ Missing'}")
    print(f"  Email SMTP_PASS: {'✅ Set' if SMTP_PASS else '❌ Missing'}")
    print(f"  Email FROM address: {'✅ Set' if EMAIL_FROM else '❌ Missing'}")


def main():
    """Test the notification functions."""
    print("Testing MeasureBot...")
    print(f"Available Discord users: {', '.join(USERS.keys()) if USERS else 'None'}")
    print(f"Available Slack users: {', '.join(SLACK_USERS.keys()) if SLACK_USERS else 'None'}")
    print(f"Available email recipients: {', '.join(EMAIL_RECIPIENTS.keys()) if EMAIL_RECIPIENTS else 'None'}")

    if BOT_TOKEN and USERS:
        try:
            user = list(USERS.keys())[0]
            send_discord_message("Test DM from MeasureBot", user=user)
        except Exception as e:
            print(f"Discord DM failed: {e}")
    else:
        print("Discord not configured")

    if SLACK_TOKEN and SLACK_USERS:
        try:
            user = list(SLACK_USERS.keys())[0]
            send_slack_message("Test DM from MeasureBot", user=user)
        except Exception as e:
            print(f"Slack DM failed: {e}")
    else:
        print("Slack not configured")

    if SMTP_PASS and EMAIL_FROM:
        try:
            if EMAIL_RECIPIENTS:
                user = list(EMAIL_RECIPIENTS.keys())[0]
                send_email("Test from MeasureBot", "Test Email", to_user=user)
            elif EMAIL_TO:
                send_email("Test from MeasureBot", "Test Email")
            else:
                print("Email: no recipients configured")
        except Exception as e:
            print(f"Email test failed: {e}")
    else:
        print("Email not configured")

    print("Done!")


if __name__ == "__main__":
    main()
