"""
Tromsø Aurora Borealis Telegram Notifier

Entry point for the application.
Monitors webcams from yr.no for aurora borealis activity
and sends Telegram notifications when detected.
"""

from bot.main import main

if __name__ == "__main__":
    main()
