# ☁️ Delta CLI — Cloud Deployment & 24/7 Server Guide

Complete guide for deploying **`delta-cli`** on cloud servers (**AWS EC2**, **DigitalOcean Droplets**, **Linode**, **Vultr**, or **Ubuntu Linux**).

> **No Nginx or Web Server Needed**: Because `delta-cli` is 100% terminal-based, you do **not** need to open web ports, install Nginx, or configure complex web firewall rules!

---

## 1. Initial Cloud Server Setup

SSH into your cloud server:
```bash
ssh ubuntu@YOUR_SERVER_IP
```

Update system packages and install Python build tools:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git tmux curl
```

---

## 2. Upload or Clone `delta-cli` to Server

### Option A: Upload from your local machine via SCP
Run this command on your **local computer** (PowerShell or Terminal):

```bash
# Upload delta-cli directory to cloud server
scp -r "./delta-cli" ubuntu@YOUR_SERVER_IP:/home/ubuntu/delta-cli
```

### Option B: Clone via Git on your Server
```bash
cd /home/ubuntu
git clone <your_repository_url> delta-cli
```

---

## 3. Initialize Environment on Server

SSH into your server and enter the `delta-cli` folder:

```bash
cd /home/ubuntu/delta-cli
chmod +x run.sh main.py
```

Create your `.env` credentials file on the server:
```bash
cp .env.example .env
nano .env
```

Add your Delta Exchange API keys to `.env`:
```env
DELTA_TESTNET_API_KEY=your_testnet_key
DELTA_TESTNET_API_SECRET=your_testnet_secret

DELTA_LIVE_API_KEY=your_live_key
DELTA_LIVE_API_SECRET=your_live_secret
```

---

## 4. Running 24/7 Automated Trading Bots & Tasks

Choose one of the two methods below to run your bot scheduler 24/7 in the background:

---

### Method 1: `tmux` Terminal Session (Recommended — Quick & Easy)

`tmux` keeps your CLI running continuously even when you close your SSH connection!

#### 1. Start a new `tmux` session:
```bash
tmux new -s delta-cli
```

#### 2. Run the interactive menu or background scheduler:
```bash
cd /home/ubuntu/delta-cli
./run.sh
```
or start the background watcher directly:
```bash
source .venv/bin/activate
python -m delta_bt watch --interval 15
```

#### 3. Detach from `tmux` (Leaves it running in background):
Press **`Ctrl + B`**, release both keys, then press **`D`**.

#### 4. Re-attach to check on your bots anytime:
```bash
tmux attach -t delta-cli
```

---

### Method 2: Systemd Background Service (Production — Auto-Restart on Server Reboot)

Systemd automatically launches `delta-cli` whenever your cloud server boots up or restarts.

#### 1. Create the systemd unit file:
```bash
sudo cat <<EOF | sudo tee /etc/systemd/system/delta-cli.service
[Unit]
Description=Delta CLI Bot Scheduler & Task Engine
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/delta-cli
Environment="PATH=/home/ubuntu/delta-cli/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/home/ubuntu/delta-cli/.venv/bin/python -m delta_bt watch --interval 15
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
```

#### 2. Reload systemd daemon & start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now delta-cli.service
```

#### 3. Check service status:
```bash
sudo systemctl status delta-cli.service
```

---

## 5. Monitoring Your Cloud Bots Remotely

Whenever you SSH into your server, run any of these commands:

### Open Live Auto-Refreshing Terminal Dashboard:
```bash
cd /home/ubuntu/delta-cli
source .venv/bin/activate
python -m delta_bt monitor
```

### View Portfolio PnL & Trade Summary:
```bash
python -m delta_bt pnl
```

### View Systemd Service Logs:
```bash
sudo journalctl -u delta-cli.service -f
```

### Emergency Kill-Switch (Close All Positions):
```bash
python -m delta_bt bot-close-all
```

---

## 6. Updating Code on Cloud Server

To update your code on the server without stopping your active bots:

```bash
cd /home/ubuntu/delta-cli
git pull
sudo systemctl restart delta-cli.service
```
