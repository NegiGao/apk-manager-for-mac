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
- Success is **verified on the device**: after `Success`, the app reads the package's version back
  with `dumpsys` and flags a mismatch or a missing package as *unverified*.
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

Requires macOS 10.13+ and the system `python3`. If macOS says it's missing, run
`xcode-select --install` once.

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
python3 tests/acceptance.py      # all scenarios (≈4 min)
python3 tests/acceptance.py 5 9  # just some of them
```

It covers: pausing the wireless background during a USB install, pausing during failing reconnects,
one scheduler no matter how many windows or Resume clicks, USB + Wi-Fi to the same phone, unplugging
mid-install, telling unauthorized / offline / connection-failed / paused apart, leaving other adb
users alone, verifying installs on the device, and the install-queue pause boundary.

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

**Wireless keeps coming back even though I paused it.** Newer adb servers auto-connect paired
devices over mDNS on their own. That's the adb server, not this app — the console's pause only
guarantees *this app* stops connecting. Turning the server's behaviour off needs the server
restarted with `ADB_MDNS_AUTO_CONNECT=0`, which would also cut other programs' connections, so the
app doesn't do it for you.

**An app won't uninstall.** Preinstalled system apps can't be removed this way; the app tells
you when that's the reason.

---

## License

MIT — see [LICENSE](LICENSE).
