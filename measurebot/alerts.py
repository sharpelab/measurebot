import os
import re
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load environment variables from .env file if it exists
env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
if os.path.exists(env_file):
    with open(env_file) as f:
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

# SMTP configuration
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.resend.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "resend")
SMTP_PASS = os.getenv("SMTP_PASS")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_TO = os.getenv("EMAIL_TO")  # Keep for backward compatibility


# Configuration class for IPython usage
class Config:
    """Simple configuration for default channels and users."""
    discord_channel = None
    discord_user = None
    email_user = None
    
    @classmethod
    def set_defaults(cls, discord_channel=None, discord_user=None, email_user=None):
        """Set default values for notifications.
        
        Args:
            discord_channel: Default Discord channel name
            discord_user: Default Discord user(s) - can be string or list of strings
            email_user: Default email user(s) - can be string or list of strings
        """
        cls.discord_channel = discord_channel
        cls.discord_user = discord_user
        cls.email_user = email_user
        
        print(f"✅ Defaults set:")
        if discord_channel:
            print(f"   Discord channel: #{discord_channel}")
        if discord_user:
            if isinstance(discord_user, list):
                print(f"   Discord users: {', '.join([f'@{u}' for u in discord_user])}")
            else:
                print(f"   Discord user: @{discord_user}")
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
        user: Discord user(s) to send DM to - can be string or list of strings
    """
    
    # Use config default if not specified
    user = user or config.discord_user
    
    if not BOT_TOKEN:
        print("❌ Discord: BOT_TOKEN not configured")
        return False
        
    if not user:
        print("❌ Discord: No user specified for DM")
        return False

    # Convert single user to list for uniform processing
    users_to_process = user if isinstance(user, list) else [user]
    
    success_count = 0
    total_users = len(users_to_process)
    
    for u in users_to_process:
        u_lower = u.lower()
        if u_lower not in USERS:
            available = ", ".join(USERS.keys()) if USERS else "None"
            print(f"❌ Discord: user '{u}' not found. Available: {available}")
            continue
            
        user_id = USERS[u_lower]
        
        # Step 1: Create DM channel with the user
        dm_url = "https://discord.com/api/v10/users/@me/channels"
        dm_headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
        dm_payload = {"recipient_id": user_id}
        
        try:
            # Create DM channel
            dm_response = requests.post(dm_url, headers=dm_headers, json=dm_payload)
            dm_response.raise_for_status()
            dm_data = dm_response.json()
            dm_channel_id = dm_data["id"]
            
            # Step 2: Send message to DM channel
            message_url = f"https://discord.com/api/v10/channels/{dm_channel_id}/messages"
            message_payload = {"content": message}
            
            message_response = requests.post(message_url, headers=dm_headers, json=message_payload)
            message_response.raise_for_status()
            
            print(f"✅ Discord DM: sent to @{u}")
            success_count += 1
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Discord DM: failed to send to @{u} - {e}")
            continue
    
    return success_count == total_users


# Keep the old function for backward compatibility but rename it
def send_discord_channel_message(message: str, channel: str | None = None, user: str | list[str] | None = None):
    """Send a Discord message to a named channel, optionally mentioning user(s).
    
    Args:
        message: Message to send
        channel: Discord channel name
        user: Discord user(s) to mention - can be string or list of strings
    """
    
    # Use config defaults if not specified
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
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}

    # Handle multiple users
    user_mentions = []
    user_ids = []
    mentioned_users = []
    
    if user:
        # Convert single user to list for uniform processing
        users_to_process = user if isinstance(user, list) else [user]
        
        for u in users_to_process:
            u_lower = u.lower()
            if u_lower in USERS:
                user_id = USERS[u_lower]
                user_mentions.append(f"<@{user_id}>")
                user_ids.append(user_id)
                mentioned_users.append(u)
            else:
                available_users = ", ".join(USERS.keys()) if USERS else "None"
                print(f"⚠️  Discord: user '{u}' not found. Available: {available_users}")
    
    # Prepare message with mentions
    if user_mentions:
        full_message = f"{' '.join(user_mentions)} {message}"
        payload = {
            "content": full_message,
            "allowed_mentions": {"users": user_ids}
        }
    else:
        payload = {"content": message}

    try:
        r = requests.post(url, headers=headers, json=payload)
        r.raise_for_status()
        
        if mentioned_users:
            users_str = ", ".join([f"@{u}" for u in mentioned_users])
            print(f"✅ Discord: sent to #{channel} (mentioning {users_str})")
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
        to_user: Username(s) to send to - can be string or list of strings
        to_email: Direct email address(es) - can be string or list of strings (overrides to_user)
        from_email: Sender email (defaults to EMAIL_FROM)
    """
    
    from_addr = from_email or EMAIL_FROM
    
    # Use config default if not specified
    to_user = to_user or config.email_user
    
    # Determine recipient email(s)
    to_addresses = []
    
    if to_email:
        # Direct email(s) provided
        if isinstance(to_email, list):
            to_addresses = to_email
        else:
            to_addresses = [to_email]
    elif to_user:
        # Look up user(s) by name
        users_to_process = to_user if isinstance(to_user, list) else [to_user]
        
        for user in users_to_process:
            user_lower = user.lower()
            if user_lower in EMAIL_RECIPIENTS:
                to_addresses.append(EMAIL_RECIPIENTS[user_lower])
            else:
                available = ", ".join(EMAIL_RECIPIENTS.keys()) if EMAIL_RECIPIENTS else "None"
                print(f"❌ Email: unknown user '{user}'. Available: {available}")
    else:
        # Fall back to default EMAIL_TO
        if EMAIL_TO:
            to_addresses = [EMAIL_TO]
    
    if not SMTP_PASS:
        print("❌ Email: SMTP_PASS not configured")
        return False
    if not from_addr:
        print("❌ Email: EMAIL_FROM not configured")
        return False
    if not to_addresses:
        print("❌ Email: no recipients specified and no default EMAIL_TO")
        return False

    # Send email to each recipient
    success_count = 0
    total_count = len(to_addresses)
    
    for to_addr in to_addresses:
        # Create message
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
        if total_count == 1:
            print(f"✅ Email: sent to {to_addresses[0]}")
        else:
            print(f"✅ Email: sent to {success_count}/{total_count} recipients ({', '.join(to_addresses[:3])}{'...' if len(to_addresses) > 3 else ''})")
        return success_count == total_count
    else:
        return False


# Main Discord function - now defaults to DMs
def send_discord_message(message: str, user: str | list[str] | None = None):
    """Send a Discord direct message to user(s). This is now the default behavior.
    
    Args:
        message: Message to send
        user: Discord user(s) to send DM to - can be string or list of strings
    """
    return send_discord_dm(message, user)


# Convenience functions
def set_defaults(discord_user=None, email_user=None):
    """Set default values for notifications. Use this in IPython for convenience.
    Note: discord_channel is no longer needed since we use DMs by default.
    """
    config.set_defaults(discord_channel=None, discord_user=discord_user, email_user=email_user)


def discord(message: str, user: str | list[str] | None = None):
    """Short alias for send_discord_message (DMs)."""
    return send_discord_message(message, user)


def discord_channel(message: str, channel: str | None = None, user: str | list[str] | None = None):
    """Send to a Discord channel (old behavior) - use this if you need channel messages."""
    return send_discord_channel_message(message, channel, user)


def email(message: str, subject: str = "MeasureBot Notification", to_user: str | list[str] | None = None, to_email: str | list[str] | None = None):
    """Short alias for send_email."""
    return send_email(message, subject, to_user, to_email)


def alert(message: str, subject: str = "MeasureBot Alert"):
    """Send both Discord DM and email notifications using defaults."""
    discord_ok = send_discord_message(message)
    email_ok = send_email(message, subject)
    return discord_ok and email_ok
def set_defaults(discord_channel=None, discord_user=None, email_user=None):
    """Set default values for notifications. Use this in IPython for convenience.
    
    Args:
        discord_channel: Default Discord channel name
        discord_user: Default Discord user(s) - can be string or list of strings
        email_user: Default email user(s) - can be string or list of strings
    
    Examples:
        # Single users
        set_defaults(discord_channel="alerts", discord_user="john", email_user="john")
        
        # Multiple users
        set_defaults(
            discord_channel="team-alerts", 
            discord_user=["john", "jane", "bob"],
            email_user=["john", "jane"]
        )
    """
    config.set_defaults(discord_channel, discord_user, email_user)


def show_config():
    """Display current configuration and available options."""
    print("=== MeasureBot Configuration ===")
    
    # Show defaults
    if config.discord_channel:
        print(f"Default Discord channel: #{config.discord_channel}")
    else:
        print("Default Discord channel: None")
        
    if config.discord_user:
        if isinstance(config.discord_user, list):
            print(f"Default Discord users: {', '.join([f'@{u}' for u in config.discord_user])}")
        else:
            print(f"Default Discord user: @{config.discord_user}")
    else:
        print("Default Discord user: None")
        
    if config.email_user:
        if isinstance(config.email_user, list):
            print(f"Default email users: {', '.join(config.email_user)}")
        else:
            print(f"Default email user: {config.email_user}")
    else:
        print("Default email user: None")
    
    print()
    print("Available Discord channels:", ", ".join(CHANNELS.keys()) if CHANNELS else "None")
    print("Available Discord users:", ", ".join(USERS.keys()) if USERS else "None")
    print("Available email users:", ", ".join(EMAIL_RECIPIENTS.keys()) if EMAIL_RECIPIENTS else "None")
    print()
    print("Configuration status:")
    print(f"  Discord BOT_TOKEN: {'✅ Set' if BOT_TOKEN else '❌ Missing'}")
    print(f"  Email SMTP_PASS: {'✅ Set' if SMTP_PASS else '❌ Missing'}")
    print(f"  Email FROM address: {'✅ Set' if EMAIL_FROM else '❌ Missing'}")


def email(message: str, subject: str = "MeasureBot Notification", to_user: str | list[str] | None = None, to_email: str | list[str] | None = None):
    """Short alias for send_email.
    
    Args:
        message: Email message content
        subject: Email subject line
        to_user: Username(s) to send to - can be string or list of strings (optional)
        to_email: Direct email address(es) - can be string or list of strings (optional)
    """
    return send_email(message, subject, to_user, to_email)


def alert(message: str, subject: str = "MeasureBot Alert"):
    """Send both Discord and email notifications using defaults."""
    discord_ok = send_discord_message(message)
    email_ok = send_email(message, subject)
    return discord_ok and email_ok


def main():
    """Test the notification functions."""
    print("Testing MeasureBot...")
    print(f"Available Discord users: {', '.join(USERS.keys()) if USERS else 'None'}")
    print(f"Available email recipients: {', '.join(EMAIL_RECIPIENTS.keys()) if EMAIL_RECIPIENTS else 'None'}")
    print("Note: Discord now uses DMs by default instead of channels")
    
    # Test Discord if configured
    if BOT_TOKEN and USERS:
        try:        
            user = list(USERS.keys())[0]
            send_discord_message("Test DM from MeasureBot", user=user)
        except Exception as e:
            print(f"Discord DM failed: {e}")
    else:
        print("Discord not configured")
    
    # Test email if configured  
    if SMTP_PASS and EMAIL_FROM:
        try:
            if EMAIL_RECIPIENTS:
                # Test with first available user
                user = list(EMAIL_RECIPIENTS.keys())[0]
                send_email("Test from MeasureBot", "Test Email", to_user=user)
            elif EMAIL_TO:
                # Fall back to default EMAIL_TO
                send_email("Test from MeasureBot", "Test Email")
            else:
                print("Email: no recipients configured")
        except Exception as e:
            print(f"Email failed: {e}")
    else:
        print("Email not configured")
    
    print("Done!")


if __name__ == "__main__":
    main()
