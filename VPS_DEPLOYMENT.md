# Delta CLI: 24/7 VPS Deployment Guide

Since Delta CLI is designed as a lightweight terminal app, running it 24/7 on a Linux VPS (Virtual Private Server) is incredibly easy. You don't need Docker or heavy web servers.

Here are the **three best ways** to keep your bots trading continuously, even after you close your SSH connection.

---

## Method 1: The Built-in Headless Daemon (Easiest)
Delta CLI has a built-in background daemon designed specifically for this.

1. Open the TUI by running: `python main.py`
2. Go to **Option 4 (Scheduled Trading & Tasks)**.
3. Select **Option 4: 🚀 Launch Headless Background Watcher Daemon**.
4. Press Enter to use the default 15-second loop interval.
5. The system will start a background process using `nohup`.
6. **You can now safely close your SSH terminal!** The bot will continue executing your active deployments and background tasks.

**To check on it later:**
- Simply log back into your VPS.
- View the live logs by running: `tail -f watcher.log`

---

## Method 2: Using `tmux` (Highly Recommended)
`tmux` is a terminal multiplexer. It allows you to run the visual TUI (`main.py`) continuously in a virtual window that you can detach from and reattach to later.

1. **Install tmux** (if you don't have it):
   ```bash
   sudo apt update && sudo apt install tmux -y
   ```
2. **Start a new tmux session**:
   ```bash
   tmux new -s delta
   ```
3. **Start your bot in the new session**:
   ```bash
   cd ~/delta-cli
   source venv/bin/activate
   python main.py
   ```
4. **Detach from the session**:
   Press `Ctrl+B`, then press `D`. (You will be dropped back to your normal terminal, but Delta CLI is still running inside the hidden tmux window!).
5. **Close your SSH connection.**

**To check on it later:**
- Log back into your VPS.
- Reattach to the session by running: `tmux attach -t delta`
- You'll see your `main.py` TUI exactly how you left it!

---

## Method 3: Systemd Service (For Maximum Reliability)
If your VPS reboots due to maintenance, your bot will stop. A `systemd` service ensures your bot starts automatically when the server turns on.

1. Create a service file:
   ```bash
   sudo nano /etc/systemd/system/delta-cli.service
   ```
2. Paste the following configuration (Adjust `/home/manoj` if your username is different):
   ```ini
   [Unit]
   Description=Delta CLI Automated Trading Bot
   After=network.target

   [Service]
   Type=simple
   User=manoj
   WorkingDirectory=/home/manoj/delta-cli
   ExecStart=/home/manoj/delta-cli/venv/bin/python3 -m delta_bt watch --interval 15
   Restart=on-failure
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```
3. Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`).
4. Enable and start the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable delta-cli
   sudo systemctl start delta-cli
   ```
5. **Check the live logs:**
   ```bash
   sudo journalctl -u delta-cli -f
   ```

> [!TIP]
> **Which one should I choose?**
> Use **Method 2 (tmux)** if you want to be able to visually see the TUI and manage things easily without restarting processes. Use **Method 3 (systemd)** if you want enterprise-grade reliability in case your server reboots.
