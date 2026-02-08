# Aurora Borealis Telegram Bot

A Python Telegram bot that monitors public webcams for aurora borealis activity in Tromsø, Norway and sends notifications when detected on multiple cameras simultaneously.

## How It Works

1. Fetches images from public webcams (yr.no, UiT weather station) every 2 minutes during dark hours
2. Analyzes each image using HSV color space detection, looking for green aurora glow (557.7nm oxygen emission)
3. Filters noise using per-camera baselines and blob-size thresholds
4. Sends Telegram alerts when 2+ cameras detect aurora simultaneously
5. Uses smart cooldown logic to avoid notification spam while still reporting changes

## Features

- Multi-camera monitoring with configurable detection regions per camera
- HSV color-based aurora detection (green, red, violet) with weighted scoring
- Automatic darkness detection using astronomical calculations for Tromsø (69.65°N)
- Smart alert cooldown (10 min for increasing activity, 30 min for stable)
- Multi-user subscription system with configurable alert sensitivity levels
- Image archiving with automatic disk space management
- GUI tools for camera calibration, region selection, and parameter tuning

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

Requires Python 3.11+.

### 2. Configure the bot

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
```

You need at minimum:
- `TELEGRAM_BOT_TOKEN` - Create a bot via [@BotFather](https://t.me/botfather)
- `ADMIN_CHAT_ID` - Your Telegram user ID (get it from [@userinfobot](https://t.me/userinfobot))

### 3. Configure cameras

The included `cameras_config.json` has pre-configured Tromsø webcams with calibrated detection regions and noise baselines.

To recalibrate or add your own cameras:

```bash
# Visual region selector - draw sky areas for detection
python tools/region_selector.py

# Debug viewer - see detection results and calibrate noise baselines
python tools/debug_viewer.py

# Parameter tuner - batch test detection parameters on saved photos
python tools/param_tuner.py
```

### 4. Run the bot

```bash
python app.py
```

Or on Windows: double-click `run_bot.cmd`.

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Subscribe to aurora alerts |
| `/stop` | Unsubscribe from alerts |
| `/level` | Set alert sensitivity (Low/Medium/High) |
| `/status` | Show current monitoring status |
| `/cameras` | List monitored cameras |
| `/about` | How the detection works |
| `/help` | Show all commands |

Admin-only (hidden): `/scan`, `/peek`, `/simonsays`

## File Structure

```
tromsoexpertbot/
├── bot/
│   ├── main.py          # Bot setup, commands, scheduler loop
│   ├── config.py        # Configuration (env vars + defaults)
│   ├── detector.py      # HSV color detection + blob filtering
│   ├── fetcher.py       # Async webcam image fetching
│   ├── darkness.py      # Astronomical darkness calculations
│   ├── notifier.py      # Telegram alert sender
│   ├── subscribers.py   # JSON-based subscription management
│   ├── cooldown.py      # Smart alert cooldown logic
│   ├── archiver.py      # Photo archive with auto-cleanup
│   └── status_writer.py # Simple status file for IoT polling
├── tools/
│   ├── region_selector.py  # GUI: mark detection regions on camera images
│   ├── debug_viewer.py     # GUI: live detection results + calibration
│   └── param_tuner.py      # GUI: batch parameter tuning with before/after
├── data/
│   ├── subscribers.example.json  # Example subscriber data
│   └── alert_state.example.json  # Example alert state
├── cameras_config.json  # Camera URLs, regions, noise baselines
├── .env.example         # Environment variable template
├── app.py               # Entry point
├── requirements.txt
└── README.md
```

## Darkness Schedule for Tromsø (69.65°N)

| Period | Behavior |
|--------|----------|
| Nov 21 - Jan 21 | Polar night - always monitoring (24h darkness) |
| Jan 22 - Apr 20 | Monitor after nautical twilight (-12° sun elevation) |
| Apr 21 - Aug 15 | Sleep mode - midnight sun, no aurora visible |
| Aug 16 - Nov 20 | Monitor after nautical twilight (-12° sun elevation) |

## License

MIT License
