# MaiBot Phone Controller 📱✨

> **Empower MaiBot with her very own physical Android smartphone!**  
> Pioneering digital life idle slacking & social browsing, natural device alias switching, semantic UI text-tapping, real-time screen stream sharing, and untethered Tailscale mesh networking.

---

## 🌟 Key Features & Highlights

### 1. ☕ True Digital Life: Autonomous Idle Slacking (`auto_slacking`)
> *"She is no longer a rigid program waiting for commands, but a genuine soulmate who sneaks onto her phone to browse feeds during idle moments."*

* 🕒 **Natural Human Circadian Rhythm**:  
  Runs strictly on scheduled hours. Within the daytime active window (default `09:00-23:00`), she autonomously wakes up her phone every **2 to 4 hours** (randomized interval) to browse for 60 seconds if nobody is chatting with her. During late night (`23:00-08:00`), she goes into quiet sleep mode and never touches the phone.
* 📱 **Supports 4 Major Social Apps**:  
  Browses through **Bilibili, Zhihu, Xiaohongshu (RED), and Douyin (TikTok)**.
* 🛡️ **Auto Splash Ad Dismissal & Anti-Deviation Guard**:  
  - Automatically locates and taps "Skip", "Skip Ad", or "Close" buttons on app cold starts.  
  - Background foreground watchdog monitors active packages: if a transparent ad triggers an unintended jump to another shopping app, she presses the **Back key within 1 second** to return.
* 👆 **Human-like Touch Dynamics**:  
  Swipe trajectories include Gaussian micro-jitters, variable duration (350ms-650ms), human reading pauses (3-7s), and an ~8% chance of reversing the swipe to review past content.
* 🎯 **Golden Visual Center Alignment Algorithm (100% Image-Title Match)**:  
  Ignores the top 18% (status/tab bar) and bottom 15% (navigation/login floats). Computes the vertical geometric distance of candidate cards to the screen center line (`cy - screen_h / 2`). The top-ranked card is **guaranteed to be the most prominent, captivating center image/video**, completely eliminating mismatched titles.
* 🧠 **Live LLM Personality Commentary (No Mechanical Report Tone)**:  
  Eliminates rigid robotic phrases like "Reporting Master". Powered by real LLM with a friendly, casual, gamer-girl persona to produce natural, organic Chinese social commentary with crystal-clear screenshots:
  > * RED (Soup Recipe): *"Saw this traditional herbal soup post, master you should drink more warm soup recently too~"*  
  > * Zhihu (Beta Notice): *"Saw Zhihu pushing a beta invite, did you get this update prompt?"*  
  > * Bilibili (Oden Video): *"Look at this master, does 50x price difference oden contain real gold haha"*  
  > * Douyin (Dance Video): *"Master look at this video, the likes count is insanely high lol"*
* 🔄 **Dynamic Multi-Channel Fallback Routing**:  
  Zero manual stream ID hassle. Leaving `notify_stream_id` blank automatically routes notifications to the owner's most active private chat, with automated failover between official bot and alternate adapters.
* 🔒 **Automatic Screen Lock**:  
  Automatically presses the Power key to lock and turn off the screen after slacking, saving battery.

---

### 2. 🔀 Natural Device Alias Switching
* Assign friendly names to multiple devices:  
  `aliases = "BackupPhone=100.64.0.1:5555,Xiaomi=192.168.1.100:5555"`
* Switch devices seamlessly in conversation:  
  *"MaiBot, connect to BackupPhone"* / *"MaiBot, switch to Xiaomi"*

---

### 3. 🎯 Semantic UI Text-Tapping (`phone_tap_text`)
* No brittle pixel coordinates needed. Taps buttons by their visible label:  
  `phone_tap_text("Skip")`, `phone_tap_text("Confirm")`, `phone_tap_text("Send")`

---

### 4. 👁 Real-time Screen Perception & Fast Capture
* 📸 **High-Speed On-Device Capture + ADB Pull**:  
  Captures locally to `/sdcard` and pulls via buffered ADB protocol, slashing cross-ocean VPN transmission latency from 37s to **5-7s**, compressed to JPEG on the fly.
* 🌲 **UI Hierarchy Dump**:  
  `phone_dump` extracts structured UI trees, interactive elements, bounds, and text.

---

### 5. ⌨️ Native Chinese & Unicode Typing (ADBKeyboard)
* Broadcasts Base64 payloads via `am broadcast -a ADB_INPUT_B64 --es msg <base64>` for full Unicode, emoji, and Chinese character typing.

---

### 6. 🎬 Macro Execution Engine (`phone_macro`)
* Bundles serial multi-step sequences (tap, swipe, key, text, delay) in one single dispatch, saving rounds and tokens.

---

### 7. 🛡 Multi-Platform Owner Guard (QQ + Discord)
* Restricts access strictly to configured `owner_qq` IDs across QQ and Discord platforms.

---

### 8. 🌐 Untethered Tailscale Mesh Networking
* Control the phone 24/7 over encrypted Tailscale WireGuard mesh net even when your computer is shut down and your phone is on 5G cellular.

---

## 🛠 Available Tools (14)

| Category | Tool Name | Description |
| :--- | :--- | :--- |
| **Device & Connection** | `phone_devices` | List configured aliases and current device status |
| | `phone_connect` | Connect/switch device by alias or IP:port |
| | `phone_status` | Query battery, charging, power state, and foreground package |
| | `phone_pair` | Pair wireless debugging with 6-digit pairing code |
| **Visuals** | `phone_screenshot` | Fast capture compressed screen and post to chat |
| | `phone_dump` | Dump interactive UI hierarchy tree with bounds |
| **Interaction** | `phone_tap_text` | **Smart tap**: locate and click button by semantic text |
| | `phone_tap` | Tap exact (x, y) coordinates |
| | `phone_swipe` | Swipe direction or between coordinates |
| | `phone_text` | Type text via ADBKeyboard |
| | `phone_key` | Hardware key events (back, home, power, recent, enter) |
| | `phone_open_app` | Launch app by name or package |
| | `phone_macro` | Execute serial action sequence macro |
| **Digital Life** | `phone_slack_off` | Browse feeds (Bilibili/Zhihu/RED/Douyin) & share highlights |

---

## ⚙️ Configuration (`config.toml`)

```toml
[plugin]
name = "phone_controller"
version = "1.1.1"
config_version = "1.1.1"
enabled = true

[device]
adb_path = "adb"
default_host = ""                               # IP address for auto-connection (LAN or Tailscale 100.x.x.x)
default_port = 5555
device_serial = ""                              # Empty defaults to single connected device
owner_qq = ""                                   # Required security item: Owner QQ or Discord User ID
aliases = "BackupPhone=192.168.1.100:5555"
auto_send_screenshot = true
screenshot_quality = 75

[slack_off]
enabled = true
auto_slacking = false                           # Enable autonomous background slacking
interval_hours_min = 2.0                        # Min hours between slacking sessions
interval_hours_max = 4.0                        # Max hours between slacking sessions
session_duration_seconds = 60                   # Browsing duration in seconds
active_time_range = "09:00-23:00"               # Active schedule (quiet during late night)
lock_screen_after_slack = true                  # Auto lock screen after browsing to save battery
preferred_apps = "b站,知乎,小红书,抖音"           # App pool: Bilibili, Zhihu, Xiaohongshu, Douyin
share_interesting_finds = true                  # Share highlight screenshot with owner
notify_summary = false                          # Text summary toggle (default false for quiet mode)
swipe_interval_min = 3.0
swipe_interval_max = 7.0
notify_stream_id = ""                           # Primary target account (Owner QQ, Bot QQ, or Discord ID; DO NOT use session_id)
fallback_stream_id = ""                         # Optional fallback target account (Owner QQ, Bot QQ, or Discord ID; used ONLY if primary fails)
custom_llm_url = ""                             # Optional 3rd-party LLM endpoint
custom_llm_key = ""                             # Optional 3rd-party LLM key
custom_llm_model = "gpt-3.5-turbo"
```

---

## 📄 License

This project is licensed under the [MIT License](./LICENSE).
