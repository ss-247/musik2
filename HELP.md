# MUSIK2 — Help & Reference

> Dark. Tron-inspired. Built for sampling.

---

## Getting Started

1. Place audio files in the `samples/` folder (WAV, FLAC, MP3, OGG, AIFF, OPUS, M4A).
2. Launch: `.\venv\Scripts\python main.py`
3. Double-click a file in the **FILE BROWSER** dock on the left to load it into the active deck.

---

## Waveform View

| Action | Result |
|--------|--------|
| **Scroll wheel** | Zoom in / out (both L and R channels linked) |
| **Click + drag** | Scrub — moves playhead to clicked time position |
| **Shift + drag** | Create / resize a selection region |
| **Drag selection edges** | Adjust selection start or end point |
| **Middle-click drag** *(or right-drag inside PyQtGraph)* | Pan the view when zoomed in |

The **L** (left) channel is rendered in **cyan**; the **R** (right) channel in **magenta**.

---

## Transport Bar

| Button | Action |
|--------|--------|
| `\|◄` | Rewind to start |
| `►` / `‖` | Play / Pause |
| `■` | Stop and return to start |
| `↺` | Toggle loop mode |

The time display shows `current position / total duration`.

---

## Info Panel

Displays metadata read directly from the audio file plus live-computed statistics:

- **Format / subtype** — container format and codec/bit-depth (e.g. `FLAC / PCM_24`)
- **Sample rate** — in Hz
- **Bit depth** — PCM word length if available in file header
- **Duration** — `M:SS.ss`
- **Est. bitrate** — derived from file size ÷ duration (accurate for CBR; approximate for VBR)
- **L / R peak** — per-channel peak in dBFS
- **L / R RMS** — per-channel RMS energy in dBFS

---

## Decks

- The app starts with **Deck A**.
- Click **+ DECK** (top-right corner of the tab bar) to add more decks.
- Each deck is independent: separate file, separate playhead, separate transport.
- Click a deck tab to make it active; the file browser always loads into the **active** deck.

---

## Keyboard Shortcuts *(Increment 2)*

Keyboard bindings will be added in the next increment.

---

## Proprietary / Custom Implementations

The following features were built from scratch for musik2 and are not part of any third-party library:

### Dual-channel linked zoom-scrub
- **What it is:** Scroll-wheel zoom operates on both L and R `PlotWidget`s simultaneously via a shared X-axis link (`setXLink`). The zoom is centre-anchored to the visible view range, not the playhead.
- **File:** `app/waveform.py` — `WaveformView.wheelEvent`

### Min-max envelope downsampling
- **What it is:** Rather than naive stride-downsampling (which misses transients), the waveform renderer uses a min/max envelope: each display pixel represents the minimum *and* maximum sample value in that time window. This preserves peak visibility at any zoom level.
- **File:** `app/waveform.py` — `_downsample()`

### Tron neon palette
- **What it is:** The full colour scheme — `#00f5ff` cyan for left channel and primary UI, `#ff00ff` magenta for right channel, `#39ff14` phosphor green for meters, `#ffb000` amber for warnings — is a bespoke palette. It is not a built-in Qt or PyQtGraph theme.
- **File:** `app/theme.py`

### Per-channel peak / RMS in dBFS
- **What it is:** Peak and RMS dBFS values are computed live from the loaded NumPy array (not read from file tags). This gives accurate per-channel values for any format, including mid-side encoded files.
- **File:** `app/info_panel.py` — `_dbfs()`, `_rms()`

---

## Stack

| Role | Library |
|------|---------|
| GUI | PySide6 6.11+ |
| Waveform rendering | PyQtGraph 0.14+ |
| Audio file I/O | soundfile 0.13+ |
| Audio playback | sounddevice 0.5+ |
| Signal analysis | scipy + numpy |

---

## Roadmap (future increments)

- **Increment 2:** Frequency spectrogram panel, per-channel FFT, pitch detection via librosa
- **Increment 3:** Selection → copy to new deck; reverse selection
- **Increment 4:** Pitch shift, time stretch, BPM detection
- **Increment 5:** Deck blending / mixer, crossfader, per-deck EQ
- **Increment 6:** Export selection, export blend, project save/load
