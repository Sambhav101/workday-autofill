# Workday Autofill — Chrome extension

One-click "add this job page to the queue" for the [Workday Autofill](../README.md)
web UI. Click the toolbar icon on any job posting and its URL is POSTed to your
running agent's queue.

## Install (load unpacked)

1. Start the web UI so the queue API is reachable:
   ```bash
   ./venv/bin/python -m src.web          # Windows: .\venv\Scripts\python -m src.web
   ```
2. Open `chrome://extensions` and toggle **Developer mode** (top right).
3. Click **Load unpacked** and select this `extension/` folder.
4. Pin the extension (puzzle-piece menu → pin) so the icon stays visible.

## Use

- Open a job posting, click the toolbar icon, hit **Add to Queue**.
- A green `✓` badge flashes on success; the popup shows how many jobs are queued.
- Supported job pages (Workday today; Greenhouse / Lever / Ashby once
  [#2](https://github.com/Sambhav101/workday-autofill/issues/2) lands) are
  flagged, but any `http(s)` URL can be queued.

## Server settings (⚙︎ in the popup)

By default the extension talks to `http://localhost:8000` (same machine as the
agent). To queue from a **different device on your LAN** — e.g. the agent runs
on a Windows/GPU box and you browse on a Mac — open ⚙︎ **Server settings** and set:

- **Server URL** — the agent's Network URL, e.g. `http://192.168.1.99:8000`
- **Auth token** — the token printed when the agent starts (required when it's
  exposed on the LAN; see [issue #1](https://github.com/Sambhav101/workday-autofill/issues/1))

Settings are saved in `chrome.storage.local` and persist across restarts.

## Permissions

- `activeTab` — read the URL of the tab you're on, only when you click the icon.
- `storage` — remember your server URL + token.
- `host_permissions` (`http/https`) — POST to whatever server URL you configure
  (could be any LAN IP). MV3 grants this without needing CORS changes on the server.
