# APK Manager for Mac

**[English](README.md) · [日本語](README.ja.md) · [中文](README.zh-CN.md)**

A small macOS app for putting a pile of APKs onto Android devices — in the order *you* choose.
Drop the files in, drag them into the right order, hit install. Plug in a different phone and
the same order runs again. It also lists what's already on the device under the **real app
names you see on the phone**, and pulls any of them back out as APK files.

Pure Python standard library + a local web UI wrapped in a `.app` bundle. No `pip install`,
no Node, no Xcode. The only external dependency is `adb`, which the app can download for you.

![queue](docs/screenshot-queue.png)

| Wireless | Device apps / Extract |
| --- | --- |
| ![wireless](docs/screenshot-wireless.png) | ![apps](docs/screenshot-apps.png) |

![console](docs/screenshot-console.png)


---

## What it does

**Install queue**
- Drag APKs (or a whole folder) onto the window. `.apk`, `.xapk`, `.apks` and `.apkm` all work —
  split bundles are installed with `install-multiple` automatically.
- Reorder by dragging, or sort by app name / file name / package / size / version / date added.
- **Install in order**, one after another, with live progress.
- **Pause after current** stops cleanly once the APK in progress finishes; **Continue** picks up
  only what's left. Installing to a device that already got part of the batch asks first —
  *install the remaining* or *reinstall everything* — instead of blindly starting over.
- Each job is **bound to one device** (connection + verified hardware serial). Unplug it and the
  queue pauses; plug in a different phone and nothing resumes on its own. It never falls back to the
  same phone's Wi-Fi entry or to another device.
- Success is **verified on the device**: after `Success`, the app re-checks it's still the same device,
  then reads the package back (`pm path` + `dumpsys`). A version mismatch or missing package is
  *unverified*; if the device can't be queried or its identity can't be confirmed, the item stays
  **awaiting verification** — a failed query is never reported as "not installed".
- Save a named order ("new phone setup") and load it again on the next device.
- Every result is explained: success with version and elapsed time, failures with the actual
  reason *and* what to do about it (signature clash → uninstall first; device has a newer
  build → enable downgrade; phone refused → allow "Install via USB"; and so on).

**Already-installed markers**
- When a device connects, the queue is compared against it: *same version*, *older version →
  upgradable*, *device has newer*, or *not installed*.
- One click to install only what's new or upgradable — handy when setting up several phones.

**Device apps / extraction**
- Lists installed apps with their **real display names** (Chinese/Japanese names show properly)
  plus icons, version and size.
- Click **Extract** on any app to pull its APK into `提取APP/<name>_<package>_<version>/`.
  Split apps come out complete (`base.apk` + every `split_*.apk`) with an `info.txt`.
- Uninstall single apps or a batch, optionally keeping their data (`-k`).

**Wireless (Wi-Fi debugging)**
- Pair with the 6-digit code from Android's Wireless debugging screen, or connect straight to a
  known `IP:port`.
- One button turns a cabled phone into a wireless one (`adb tcpip` + auto-detected IP).
- Devices are labelled **USB** or **Wi-Fi**, and if the same phone is connected both ways the
  app says so — large APKs are much faster over the cable.
- Reconnects to the last wireless device on startup, and retries a dropped one at most three times
  (5 s / 15 s / 45 s) before stopping to wait for you.
- Disconnecting only ever targets the one `IP:port` you picked — there's no "disconnect all".

**ADB console**
- One place to see what the app is doing to your devices: the adb binary, version, server port and
  the adb processes it can see (labelled *this app*, *shared server* or *external / unknown* — a
  running server or a busy port 5037 is never reported as a conflict on its own).
- Device connections grouped by **verified hardware serial**, so the USB and Wi-Fi entries of one
  phone show as one device; authorized, unauthorized and offline are shown separately.
- Every background task — discovery, status queries, wireless auto-connect, reconnect — with its
  state (*running / idle / paused / finishing / failed · waiting*), last success and next run.
- The install job, the last failure, the adb commands running right now, and a raw command log.
- Controls: **Check once**, **Pause background & wait / Resume**, **Pause wireless background**, and
  **USB only** (installs go to that USB device only; no wireless scanning, reconnecting or `tcpip`
  for it; if USB drops the queue pauses).

**Pause background & wait** means this app stops touching devices: the APK being installed is allowed
to finish, but it isn't queried afterwards (it's marked *awaiting verification*, with adb's exit code
and output kept) and the next one doesn't start. **Resume** verifies pending items first and never
continues installing by itself; pending items are never reinstalled just because their result was
unknown. **Cancel current** signals only this app's own `adb install` process (by PID) and then reads
the device; if that read fails, the result is shown as unknown rather than "cancelled, not installed".

All automatic adb activity runs on **one scheduler thread** in the backend, so refreshing the page,
opening a second window or clicking Resume repeatedly never starts a second loop. Pausing is held by
the backend and survives a reload. The app never runs `adb kill-server` and never ends a process it
didn't start.

**Three languages** — English, 日本語, 中文. Switch in the top-right corner; it also changes the
macOS notification text.

---

## Install

1. Download the latest `APK-Manager-mac.zip` from
   [Releases](../../releases) and unzip it.
2. Move **APK Manager.app** wherever you like (Applications is fine).
3. **The first launch needs a right-click → Open → Open.** macOS blocks unsigned apps on a
   plain double-click. To skip the check entirely:
   ```bash
   xattr -dr com.apple.quarantine "/Applications/APK Manager.app"
   ```
4. Closing the window quits the app (~25 s later; it never quits mid-install).

Needs **Python 3.8 or newer**. macOS doesn't ship a usable Python on its own: `/usr/bin/python3` is a
stub until Xcode Command Line Tools are installed (`xcode-select --install`, which currently brings
3.9). Homebrew (`brew install python`) or the python.org installer work too. The launcher looks in
those places by absolute path (Finder-launched apps don't get your terminal's `PATH`) and shows an
alert if none is usable. Not yet verified on a real Mac — see [the acceptance checklist](docs/MAC_ACCEPTANCE.md)
and `tools/mac_diagnose.sh` (read-only diagnostics).

Only one copy runs at a time (a lock file decides; double-clicking again just re-opens the window).
If an older version is still running and idle, it is asked to quit and the new one takes over; if
it's busy installing, it's left alone.

### Phone setup (once)

1. Settings → About phone → tap **Build number** seven times.
2. Settings → Developer options → enable **USB debugging** (Xiaomi and friends also need
   **Install via USB**).
3. Plug in and tap **Allow** on the phone.

No `adb` on your Mac? Open **Settings → Download adb automatically** — it fetches Google's
official platform-tools.

---

## Run from source

```bash
git clone https://github.com/NegiGao/apk-manager-for-mac.git
cd apk-manager-for-mac
python3 app.py            # opens http://127.0.0.1:8777 in your browser
```

Build the `.app` bundle yourself (icon included, no extra tooling needed):

```bash
python3 tools/build_app.py     # → build/APK Manager.app
```

---

## How it works

| Piece | What it does |
| --- | --- |
| `core/binxml.py` | Parser for Android's binary XML and `resources.arsc` — written from scratch, no `aapt` |
| `core/apkinfo.py` | Package name, version, **real localized app label**, icon; bundle (`.xapk`/`.apks`) support |
| `core/adbkit.py` | adb wrapper: devices, install, pair/connect, and partial reads of remote APKs |
| `core/supervisor.py` | The single scheduler for every automatic adb task: pause / resume, USB-only, bounded retries |
| `core/engine.py` | Queue, saved orders, install runner (device binding, pause boundary, verification), markers, uninstall, extraction |
| `core/server.py` | Local HTTP + SSE server, bound to `127.0.0.1` only |
| `web/` | The UI (vanilla JS, no framework) and the i18n table |

A few things worth calling out:

**Real app names without pulling whole APKs.** Reading labels off the device could mean copying
tens of gigabytes. Instead the app reads the remote APK's zip central directory, then fetches
*only* `AndroidManifest.xml` and `resources.arsc` (via `tail`/`head` over `adb exec-out`),
parses them locally, and picks the label matching your UI language. Results are cached per
package.

**Late results can't overwrite a pause.** Every pause bumps a generation counter. A task that was
already running when you paused is shown as *finishing*, and when it returns its result is thrown
away if the generation has moved on — so a slow `adb devices` can't repaint stale data as "live",
and a status query can't land on a device you've since switched away from.

**Startup is kept off the critical path.** The launcher is a single `exec` into Python — no second
interpreter just to pick a port. Python binds the listening socket and spawns the browser *before*
importing the server modules, so the browser's cold start overlaps with Python's imports. Bytecode
is precompiled into the bundle (a `.app` in /Applications can't write `__pycache__`, so otherwise
every launch recompiles), the adb daemon warms up on a background thread, and the chosen browser is
remembered between runs. Relaunching while it's already running reuses the instance instead of
starting a second server.

---

## Tests

No phone needed: `tests/fakeadb/adb` is a stand-in adb that simulates unplugging, unauthorized and
offline devices, a different phone behind the same Wi-Fi address, failing reconnects, an install
interrupted mid-way, and an install that reports `Success` without actually landing.

```bash
sh tests/get_test_apks.sh        # once: fetches 3 real open-source APKs into tests/apks/
python3 tests/acceptance.py      # all 16 scenarios (≈8 min)
python3 tests/acceptance.py 10 13  # just some of them
APKMGR_TEST_SERVER_PY=/path/to/python3.9 python3 tests/acceptance.py   # run the app under 3.9
APKMGR_TEST_EVIDENCE=./evidence python3 tests/acceptance.py            # keep adb command logs
python3 tests/delivery_check.py --zip APK-Manager-mac-v1.5.1.zip --py39 /path/to/python3.9
```

`acceptance.py` covers: pausing the wireless background during a USB install; pausing during failing
reconnects; one scheduler regardless of windows or Resume clicks; USB + Wi-Fi to the same phone;
unplugging mid-install; unauthorized / offline / connection-failed / paused told apart; leaving
other adb users alone; verifying installs on the device; the queue's pause boundary; pausing the
background mid-install (pending verification, no reinstall); late results rejected before they are
written; verification bound to the same device; cancelling only this app's process; a single
instance under concurrent launches and old-version upgrades; no adb traffic while paused; and
"Check once" running exactly once. `delivery_check.py` unpacks the release ZIP into a path with CJK
characters and spaces and launches it with a Finder-like minimal environment, a read-only bundle,
Python 3.9, a forced quit mid-install, and data from v1.4 / v1.5.0.

---

## Privacy

Everything runs locally on your Mac and is bound to `127.0.0.1`. Nothing is uploaded anywhere.
The only outbound connection the app can make is downloading platform-tools from Google, and
only when you press that button.

State lives in `~/Library/Application Support/APK安装管家/` (queue, saved orders, settings, icon
cache) and logs in `~/Library/Logs/`. Delete the app and those folders to remove it completely.

---

## FAQ

**"No device detected."** Use a cable that carries data, try another port, confirm you tapped
Allow on the phone, then press Refresh devices.

**Install hangs.** The phone is probably showing a confirmation dialog — unlock it. Some vendors
require "Install via USB" in Developer options.

**Reading the app list is slow.** The first pass reads metadata for every app; a few hundred
apps take a few minutes, and it's cached afterwards. "User-installed apps" is much faster than
"All apps".

**A wireless connection appears even though I paused the wireless background.** Pausing only
guarantees that *this app* stops connecting. Other programs can connect devices, and the adb server
itself can auto-connect devices that were paired before. The console can tell whether a connection
was made by this app; when it wasn't, it says "not connected by this app (origin unknown)" and does
not guess further. The app won't restart the shared adb server or change its settings for you.

**An app won't uninstall.** Preinstalled system apps can't be removed this way; the app tells
you when that's the reason.

---

## License

MIT — see [LICENSE](LICENSE).
