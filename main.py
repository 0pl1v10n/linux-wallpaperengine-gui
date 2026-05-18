#!/usr/bin/env python3
"""
Wallpaper Engine GUI
A GNOME-style frontend for linux-wallpaperengine by Almamu.
https://github.com/Almamu/linux-wallpaperengine

Dependencies: python3, python3-gi, gir1.2-gtk-3.0, gir1.2-gdkpixbuf-2.0
"""

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gtk, GLib, GdkPixbuf, Gio, Gdk, Pango, GObject

import os
import re
import sys
import json
import shutil
import signal
import subprocess
import threading
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

APP_ID      = "io.github.linux_wallpaperengine_gui"
APP_NAME    = "Wallpaper Engine"
APP_VERSION = "1.0.0"

CONFIG_DIR   = Path.home() / ".config" / "linux-wallpaperengine-gui"
CONFIG_FILE  = CONFIG_DIR / "config.json"
AUTOSTART_DIR  = Path.home() / ".config" / "autostart"
AUTOSTART_FILE = AUTOSTART_DIR / "linux-wallpaperengine-gui.desktop"

# Default Steam Workshop content paths, tried in order
STEAM_PATHS_DEFAULT = [
    str(Path.home() / ".local/share/Steam/steamapps/workshop/content/431960"),
    str(Path.home() / ".var/app/com.valvesoftware.Steam"
        "/.local/share/Steam/steamapps/workshop/content/431960"),
    str(Path.home() / ".steam/steam/steamapps/workshop/content/431960"),
]

SCALING_MODES  = ["default", "stretch", "fit", "fill"]
CLAMPING_MODES = ["clamp", "border", "repeat"]

THUMB_W = 176
THUMB_H = 99   # 16:9

DEFAULT_CONFIG: dict = {
    "binary_path":        "linux-wallpaperengine",
    "steam_paths":        STEAM_PATHS_DEFAULT,
    "assets_dir":         "",
    "fps":                60,
    "volume":             128,
    "silent":             False,
    "noautomute":         True,   # prevent PulseAudio/PipeWire auto-muting
    "no_audio_processing": False,
    "autostart":          False,
    "monitor_assignments": {},   # {monitor_name: {scaling, clamping, enabled}}
    "wallpaper_properties": {},  # {wallpaper_id: {prop_name: value}}
    "window_width":       1280,
    "window_height":      760,
    "paned_position":     780,
    "thumb_size":         THUMB_W,
}


# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────

APP_CSS = """
/* -- Wallpaper cards -- */
.wp-card {
    border-radius: 8px;
}
.wp-card:hover {
    background-color: alpha(@theme_fg_color, 0.07);
}
.wp-card:selected {
    background-color: alpha(@theme_selected_bg_color, 0.20);
    border-radius: 8px;
}

/* -- Typography helpers -- */
.title-2 {
    font-size: 1.15em;
    font-weight: bold;
}
.heading {
    font-size: 0.82em;
    font-weight: bold;
    opacity: 0.6;
}
.caption {
    font-size: 0.85em;
    opacity: 0.75;
}

/* -- Tag pills -- */
.tag-pill {
    border-radius: 999px;
    background-color: alpha(@theme_fg_color, 0.09);
    padding: 1px 8px;
    font-size: 0.78em;
}

/* -- Boxed list (GNOME Settings style) -- */
.boxed-list {
    border-radius: 12px;
    border-width: 1px;
    border-style: solid;
    border-color: alpha(@theme_fg_color, 0.12);
}
.boxed-list row {
    padding: 0;
    min-height: 44px;
}
.boxed-list row:first-child {
    border-radius: 11px 11px 0 0;
}
.boxed-list row:last-child {
    border-radius: 0 0 11px 11px;
}
.boxed-list row:only-child {
    border-radius: 11px;
}
.boxed-list row:selected {
    background-color: transparent;
    color: @theme_fg_color;
}

/* -- Status label -- */
.status-running {
    color: @theme_selected_bg_color;
    font-style: italic;
}

/* -- Filter bar -- */
.filter-bar {
    background-color: alpha(@theme_fg_color, 0.03);
    border-bottom-width: 1px;
    border-bottom-style: solid;
    border-bottom-color: alpha(@theme_fg_color, 0.10);
}
.filter-chip {
    border-radius: 999px;
    padding: 2px 12px;
    font-size: 0.85em;
    border-width: 1px;
    border-style: solid;
    border-color: alpha(@theme_fg_color, 0.18);
    background-color: transparent;
}
.filter-chip:checked,
.filter-chip:active {
    background-color: @theme_selected_bg_color;
    color: @theme_selected_fg_color;
    border-color: @theme_selected_bg_color;
}

"""


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

class Config:
    """Thin wrapper around a JSON config file."""

    def __init__(self) -> None:
        self._d: dict = dict(DEFAULT_CONFIG)
        self.load()

    def load(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            try:
                with CONFIG_FILE.open() as fh:
                    self._d.update(json.load(fh))
            except Exception:
                pass

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with CONFIG_FILE.open("w") as fh:
            json.dump(self._d, fh, indent=2)

    def __getitem__(self, key):
        return self._d[key]

    def __setitem__(self, key, value):
        self._d[key] = value

    def get(self, key, default=None):
        return self._d.get(key, default)


# ─────────────────────────────────────────────────────────────────────────────
# Wallpaper model
# ─────────────────────────────────────────────────────────────────────────────

class Wallpaper:
    """Represents one wallpaper folder from the Steam Workshop."""

    def __init__(self, path: Path) -> None:
        self.path         = path
        self.workshop_id  = path.name
        self.title        = path.name
        self.description  = ""
        self.wp_type      = "unknown"
        self.tags: list   = []
        self.preview_file: Path | None = None
        self.properties: dict = {}
        self._parse_project()

    def _parse_project(self) -> None:
        pj = self.path / "project.json"
        if not pj.exists():
            return
        try:
            data = json.loads(pj.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return

        self.title       = data.get("title",       self.workshop_id)
        self.description = data.get("description", "")
        self.wp_type     = data.get("type",         "unknown")
        self.tags        = data.get("tags",         [])

        # Preview image: use declared name, then fall back to common names
        declared = data.get("preview", "")
        candidates = (
            [self.path / declared] if declared else []
        ) + [
            self.path / n
            for n in ("preview.gif", "preview.jpg", "preview.jpeg", "preview.png",
                      "preview.webp")
        ]
        for c in candidates:
            if c.exists():
                self.preview_file = c
                break

        # Per-wallpaper properties from project.json general section
        self.properties = (
            data.get("general", {}).get("properties", {})
        )

    _NSFW_TAGS = frozenset({
        "explicit", "adult", "nsfw", "18+", "mature", "adult content",
        "hentai", "nudity", "sexual",
    })

    def is_nsfw(self) -> bool:
        return any(t.casefold() in self._NSFW_TAGS for t in self.tags)

    def matches(self, query: str) -> bool:
        q = query.casefold()
        return (
            q in self.title.casefold()
            or q in self.workshop_id
            or any(q in t.casefold() for t in self.tags)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Monitor detection
# ─────────────────────────────────────────────────────────────────────────────

class Monitor:
    def __init__(self, name: str, width=0, height=0, x=0, y=0, primary=False):
        self.name    = name
        self.width   = width
        self.height  = height
        self.x       = x
        self.y       = y
        self.primary = primary

    @property
    def resolution(self) -> str:
        if self.width and self.height:
            return f"{self.width}×{self.height}"
        return ""

    def __repr__(self) -> str:
        return f"<Monitor {self.name} {self.resolution}>"


def detect_monitors() -> list:
    """Try every available tool to enumerate connected displays."""

    # ── xrandr (X11) ──────────────────────────────────────────────────────
    try:
        raw = subprocess.check_output(["xrandr", "--query"], text=True, timeout=3)
        pat = re.compile(
            r"^(\S+) connected (primary )?(\d+)x(\d+)\+(\d+)\+(\d+)",
            re.MULTILINE,
        )
        monitors = []
        for m in pat.finditer(raw):
            monitors.append(Monitor(
                name    = m.group(1),
                primary = bool(m.group(2)),
                width   = int(m.group(3)),
                height  = int(m.group(4)),
                x       = int(m.group(5)),
                y       = int(m.group(6)),
            ))
        if monitors:
            return monitors
    except Exception:
        pass

    # ── swaymsg (Sway / Wayland) ───────────────────────────────────────────
    try:
        raw  = subprocess.check_output(["swaymsg", "-t", "get_outputs"], text=True, timeout=3)
        outs = json.loads(raw)
        monitors = []
        for o in outs:
            if not o.get("active", True):
                continue
            r = o.get("rect", {})
            monitors.append(Monitor(
                name    = o.get("name", "unknown"),
                width   = r.get("width",  0),
                height  = r.get("height", 0),
                x       = r.get("x", 0),
                y       = r.get("y", 0),
                primary = o.get("primary", False),
            ))
        if monitors:
            return monitors
    except Exception:
        pass

    # ── hyprctl (Hyprland) ────────────────────────────────────────────────
    try:
        raw  = subprocess.check_output(["hyprctl", "monitors", "-j"], text=True, timeout=3)
        outs = json.loads(raw)
        monitors = [
            Monitor(
                name   = o.get("name", "unknown"),
                width  = o.get("width",  0),
                height = o.get("height", 0),
                x      = o.get("x", 0),
                y      = o.get("y", 0),
            )
            for o in outs
        ]
        if monitors:
            return monitors
    except Exception:
        pass

    # ── wlr-randr ─────────────────────────────────────────────────────────
    try:
        raw = subprocess.check_output(["wlr-randr"], text=True, timeout=3)
        monitors = []
        cur_name = None
        for line in raw.splitlines():
            nm = re.match(r"^(\S+)\s+", line)
            if nm and not line.startswith(" "):
                cur_name = nm.group(1)
            if cur_name:
                rm = re.search(r"(\d+)x(\d+) px", line)
                if rm:
                    monitors.append(Monitor(cur_name, int(rm.group(1)), int(rm.group(2))))
                    cur_name = None
        if monitors:
            return monitors
    except Exception:
        pass

    # Fallback: single generic display
    return [Monitor("default")]


# ─────────────────────────────────────────────────────────────────────────────
# Engine process manager
# ─────────────────────────────────────────────────────────────────────────────

class EngineManager:
    """Manages the lifecycle of the linux-wallpaperengine child process."""

    def __init__(self, config: Config) -> None:
        self.config   = config
        self._proc: subprocess.Popen | None = None
        self._poll_source: int | None = None
        self.on_stopped = None   # callable() fired on unexpected exit

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, assignments: list, global_opts: dict) -> tuple[bool, str]:
        """Build and launch the engine. Returns (ok, message)."""
        self.stop()
        cmd = self._build_command(assignments, global_opts)
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid,   # own process group so we can kill cleanly
            )
            # Poll every 800 ms for unexpected exit
            self._poll_source = GLib.timeout_add(800, self._poll_process)
            return True, " ".join(cmd)
        except FileNotFoundError:
            return False, (
                f"Executable not found: \"{self.config['binary_path']}\"\n"
                "Check the path in Preferences."
            )
        except PermissionError:
            return False, (
                f"Permission denied running: {self.config['binary_path']}"
            )
        except Exception as exc:
            return False, str(exc)

    def stop(self) -> None:
        if self._poll_source is not None:
            GLib.source_remove(self._poll_source)
            self._poll_source = None

        # Kill our own managed child first
        if self._proc and self._proc.poll() is None:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
                try:
                    self._proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None

        # Also kill any other instances that may have been started outside
        # the GUI (previous runs, manual launches, autostart, etc.)
        binary = os.path.basename(self.config["binary_path"])
        try:
            subprocess.run(["pkill", "-TERM", "-x", binary],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def list_properties(self, wallpaper_path: str) -> str:
        """Run --list-properties and return stdout (empty string on failure)."""
        binary = self.config["binary_path"]
        try:
            return subprocess.check_output(
                [binary, "--list-properties", wallpaper_path],
                text=True, timeout=10,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return ""

    # ── Internals ─────────────────────────────────────────────────────────

    def _build_command(self, assignments: list, global_opts: dict) -> list:
        binary = self.config["binary_path"]
        cmd = [binary]

        # Audio flags
        # We never pass --volume; let the engine use its own default (full).
        # Only --silent mutes, and --noautomute prevents PulseAudio auto-ducking.
        if global_opts.get("silent"):
            cmd.append("--silent")

        if global_opts.get("noautomute"):
            cmd.append("--noautomute")

        if global_opts.get("no_audio_processing"):
            cmd.append("--no-audio-processing")

        # FPS
        fps = global_opts.get("fps", 60)
        cmd += ["--fps", str(int(fps))]

        # Assets directory override
        assets = global_opts.get("assets_dir", "").strip()
        if assets:
            cmd += ["--assets-dir", assets]

        # Per-wallpaper properties (same for all monitors in this run)
        for k, v in global_opts.get("properties", {}).items():
            cmd += ["--set-property", f"{k}={v}"]

        # Monitor assignments
        # linux-wallpaperengine syntax:
        #   --scaling <mode> [--clamping <mode>] --screen-root <name> --bg <path>
        for ma in assignments:
            wp = ma.get("wallpaper_path", "")
            if not wp:
                continue
            scaling  = ma.get("scaling",  "default")
            clamping = ma.get("clamping", "clamp")
            monitor  = ma.get("monitor_name", "")

            cmd += ["--scaling", scaling]
            if clamping != "clamp":
                cmd += ["--clamping", clamping]

            if monitor and monitor != "default":
                cmd += ["--screen-root", monitor, "--bg", wp]
            else:
                # No multi-monitor flag → last positional argument
                cmd.append(wp)

        return cmd

    def _poll_process(self) -> bool:
        if self._proc is None:
            return False   # stop polling
        if self._proc.poll() is not None:
            # Process exited
            self._proc = None
            self._poll_source = None
            if self.on_stopped:
                self.on_stopped()
            return False   # stop polling
        return True   # keep polling


# ─────────────────────────────────────────────────────────────────────────────
# Wallpaper card (FlowBox child)
# ─────────────────────────────────────────────────────────────────────────────

class WallpaperCard(Gtk.FlowBoxChild):
    """Thumbnail + title card shown in the library grid."""

    def __init__(self, wallpaper: Wallpaper, thumb_w: int = THUMB_W) -> None:
        super().__init__()
        self.wallpaper  = wallpaper
        self._thumb_w   = thumb_w
        self._thumb_h   = int(thumb_w * 9 / 16)

        self.get_style_context().add_class("wp-card")
        self.set_halign(Gtk.Align.CENTER)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        outer.set_margin_top(8)
        outer.set_margin_bottom(8)
        outer.set_margin_start(8)
        outer.set_margin_end(8)

        # Thumbnail
        self._image = Gtk.Image()
        self._image.set_size_request(self._thumb_w, self._thumb_h)
        self._image.get_style_context().add_class("wp-thumbnail")
        outer.pack_start(self._image, False, False, 0)

        # Title
        title = Gtk.Label(label=wallpaper.title)
        title.set_max_width_chars(20)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_xalign(0.5)
        title.get_style_context().add_class("caption")
        outer.pack_start(title, False, False, 0)

        self.add(outer)
        self.show_all()

        if wallpaper.preview_file:
            GLib.idle_add(self._load_thumb)
        else:
            self._set_placeholder()

    def _load_thumb(self) -> bool:
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                str(self.wallpaper.preview_file),
                self._thumb_w, self._thumb_h, True,
            )
            self._image.set_from_pixbuf(pb)
        except Exception:
            self._set_placeholder()
        return False

    def _set_placeholder(self) -> None:
        self._image.set_from_icon_name("image-x-generic-symbolic", Gtk.IconSize.DIALOG)
        self._image.set_pixel_size(48)

    def reload_thumb(self, thumb_w: int) -> None:
        self._thumb_w = thumb_w
        self._thumb_h = int(thumb_w * 9 / 16)
        self._image.set_size_request(self._thumb_w, self._thumb_h)
        if self.wallpaper.preview_file:
            GLib.idle_add(self._load_thumb)


# ─────────────────────────────────────────────────────────────────────────────
# Monitor assignment row
# ─────────────────────────────────────────────────────────────────────────────

class MonitorRow(Gtk.ListBoxRow):
    """One row in the monitor assignment list (enable + scaling combo)."""

    def __init__(self, monitor: Monitor, saved: dict) -> None:
        super().__init__()
        self.monitor = monitor

        box = Gtk.Box(spacing=12)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        box.set_margin_start(14)
        box.set_margin_end(14)

        # Enable checkbox
        self._check = Gtk.CheckButton()
        self._check.set_active(saved.get("enabled", True))
        self._check.set_valign(Gtk.Align.CENTER)
        self._check.connect("toggled", self._on_toggle)
        box.pack_start(self._check, False, False, 0)

        # Monitor info
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        name_lbl = Gtk.Label(label=monitor.name)
        name_lbl.set_xalign(0.0)
        info.pack_start(name_lbl, False, False, 0)
        if monitor.resolution:
            res_lbl = Gtk.Label(label=monitor.resolution)
            res_lbl.set_xalign(0.0)
            res_lbl.get_style_context().add_class("caption")
            info.pack_start(res_lbl, False, False, 0)
        box.pack_start(info, True, True, 0)

        # Scaling combo
        self._scale_combo = Gtk.ComboBoxText()
        for mode in SCALING_MODES:
            self._scale_combo.append_text(mode)
        saved_scaling = saved.get("scaling", "default")
        idx = SCALING_MODES.index(saved_scaling) if saved_scaling in SCALING_MODES else 0
        self._scale_combo.set_active(idx)
        self._scale_combo.set_sensitive(self._check.get_active())
        box.pack_end(self._scale_combo, False, False, 0)

        self.add(box)

    def _on_toggle(self, w: Gtk.CheckButton) -> None:
        self._scale_combo.set_sensitive(w.get_active())

    @property
    def enabled(self) -> bool:
        return self._check.get_active()

    @property
    def scaling(self) -> str:
        return self._scale_combo.get_active_text() or "default"


# ─────────────────────────────────────────────────────────────────────────────
# Detail panel (right-hand side)
# ─────────────────────────────────────────────────────────────────────────────

class DetailPanel(Gtk.Box):
    """Shows wallpaper info and all settings for the selected wallpaper."""

    def __init__(self, config: Config, engine: EngineManager) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.config  = config
        self.engine  = engine
        self._wp: Wallpaper | None     = None
        self._monitors: list           = []
        self._monitor_rows: list       = []
        self._prop_saves: dict         = {}   # {prop_name: callable that returns str value}

        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_hexpand(True)
        self._scroll.set_vexpand(True)
        self.pack_start(self._scroll, True, True, 0)

        self._inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._scroll.add(self._inner)

        self._show_placeholder()

    # ── Public API ────────────────────────────────────────────────────────

    def load(self, wp: Wallpaper, monitors: list) -> None:
        self._wp       = wp
        self._monitors = monitors
        self._monitor_rows.clear()
        self._prop_saves.clear()
        self._rebuild()

    def get_assignments(self) -> list:
        """Return the list of per-monitor assignment dicts for EngineManager."""
        if not self._wp:
            return []
        out = []
        for row in self._monitor_rows:
            if row.enabled:
                out.append({
                    "monitor_name":  row.monitor.name,
                    "wallpaper_path": str(self._wp.path),
                    "scaling":       row.scaling,
                    "clamping":      "clamp",   # could extend later
                })
        return out

    def get_global_opts(self) -> dict:
        wid  = self._wp.workshop_id if self._wp else ""
        props = self.config.get("wallpaper_properties", {}).get(wid, {})
        # Merge in any live prop-widget values
        for key, getter in self._prop_saves.items():
            props[key] = getter()
        return {
            "fps":               self.config["fps"],
            "volume":            self.config["volume"],
            "silent":            self.config["silent"],
            "noautomute":        self.config["noautomute"],
            "no_audio_processing": self.config["no_audio_processing"],
            "assets_dir":        self.config.get("assets_dir", ""),
            "properties":        props,
        }

    def save_state(self) -> None:
        """Persist monitor rows and prop widgets back to config."""
        saved = {}
        for row in self._monitor_rows:
            saved[row.monitor.name] = {
                "scaling": row.scaling,
                "clamping": "clamp",
                "enabled": row.enabled,
            }
        self.config["monitor_assignments"] = saved

        if self._wp:
            wid = self._wp.workshop_id
            all_props = self.config.get("wallpaper_properties", {})
            entry = all_props.get(wid, {})
            for key, getter in self._prop_saves.items():
                entry[key] = getter()
            all_props[wid] = entry
            self.config["wallpaper_properties"] = all_props

    # ── UI construction ───────────────────────────────────────────────────

    def _clear(self) -> None:
        for c in self._inner.get_children():
            self._inner.remove(c)

    def _show_placeholder(self) -> None:
        self._clear()
        ph = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        ph.set_valign(Gtk.Align.CENTER)
        ph.set_halign(Gtk.Align.CENTER)
        ph.set_vexpand(True)
        icon = Gtk.Image.new_from_icon_name("image-x-generic-symbolic", Gtk.IconSize.DIALOG)
        icon.get_style_context().add_class("dim-label")
        lbl = Gtk.Label(label="Select a wallpaper")
        lbl.get_style_context().add_class("dim-label")
        ph.pack_start(icon, False, False, 0)
        ph.pack_start(lbl, False, False, 0)
        self._inner.pack_start(ph, True, True, 0)
        self._inner.show_all()

    def _rebuild(self) -> None:
        self._clear()
        wp = self._wp

        # ── Preview + info ────────────────────────────────────────────────
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        info_box.set_margin_top(16)
        info_box.set_margin_bottom(12)
        info_box.set_margin_start(16)
        info_box.set_margin_end(16)

        # Preview image (320×180)
        if wp.preview_file:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    str(wp.preview_file), 320, 180, True
                )
                prev_img = Gtk.Image.new_from_pixbuf(pb)
            except Exception:
                prev_img = Gtk.Image.new_from_icon_name(
                    "image-x-generic-symbolic", Gtk.IconSize.DIALOG
                )
        else:
            prev_img = Gtk.Image.new_from_icon_name(
                "image-x-generic-symbolic", Gtk.IconSize.DIALOG
            )
        prev_img.set_halign(Gtk.Align.CENTER)
        prev_img.get_style_context().add_class("wp-preview")
        info_box.pack_start(prev_img, False, False, 0)

        # Title
        title_lbl = Gtk.Label(label=wp.title)
        title_lbl.set_xalign(0.0)
        title_lbl.set_line_wrap(True)
        title_lbl.set_max_width_chars(35)
        title_lbl.get_style_context().add_class("title-2")
        info_box.pack_start(title_lbl, False, False, 0)

        # Type + tags
        tags_row = Gtk.Box(spacing=4)
        tags_row.set_halign(Gtk.Align.START)
        for text in [wp.wp_type.capitalize()] + wp.tags[:5]:
            pill = Gtk.Label(label=text)
            pill.get_style_context().add_class("tag-pill")
            tags_row.pack_start(pill, False, False, 0)
        info_box.pack_start(tags_row, False, False, 0)

        # Workshop ID
        id_lbl = Gtk.Label(label=f"Workshop ID: {wp.workshop_id}")
        id_lbl.set_xalign(0.0)
        id_lbl.get_style_context().add_class("caption")
        info_box.pack_start(id_lbl, False, False, 0)

        # Description (capped at 280 chars)
        if wp.description:
            desc = wp.description.strip()[:280]
            desc_lbl = Gtk.Label(label=desc + ("…" if len(wp.description.strip()) > 280 else ""))
            desc_lbl.set_xalign(0.0)
            desc_lbl.set_line_wrap(True)
            desc_lbl.set_max_width_chars(36)
            desc_lbl.get_style_context().add_class("caption")
            info_box.pack_start(desc_lbl, False, False, 0)

        self._inner.pack_start(info_box, False, False, 0)

        # ── Section: Monitor Assignment ────────────────────────────────────
        self._inner.pack_start(self._separator(), False, False, 0)
        self._inner.pack_start(
            self._section_header("display-symbolic", "Monitor Assignment"),
            False, False, 0,
        )
        saved_assignments = self.config.get("monitor_assignments", {})
        lb_monitors = Gtk.ListBox()
        lb_monitors.set_selection_mode(Gtk.SelectionMode.NONE)
        lb_monitors.get_style_context().add_class("boxed-list")
        for mon in self._monitors:
            row = MonitorRow(mon, saved_assignments.get(mon.name, {}))
            lb_monitors.add(row)
            self._monitor_rows.append(row)
        self._inner.pack_start(
            self._padded(lb_monitors), False, False, 0
        )

        # ── Section: Playback ──────────────────────────────────────────────
        self._inner.pack_start(self._separator(), False, False, 0)
        self._inner.pack_start(
            self._section_header("audio-x-generic-symbolic", "Playback"),
            False, False, 0,
        )
        lb_pb = Gtk.ListBox()
        lb_pb.set_selection_mode(Gtk.SelectionMode.NONE)
        lb_pb.get_style_context().add_class("boxed-list")

        lb_pb.add(self._spin_row(
            "FPS Limit", 1, 360, self.config["fps"],
            lambda v: self.config.__setitem__("fps", int(v)),
        ))
        lb_pb.add(self._scale_row(
            "Volume", "audio-volume-high-symbolic",
            0, 128, self.config["volume"],
            lambda v: self.config.__setitem__("volume", int(v)),
        ))
        lb_pb.add(self._switch_row(
            "Mute all audio", "audio-volume-muted-symbolic",
            self.config["silent"],
            lambda s: self.config.__setitem__("silent", s),
        ))
        lb_pb.add(self._switch_row(
            "Keep audio when other apps play (recommended)", "audio-volume-high-symbolic",
            self.config["noautomute"],
            lambda s: self.config.__setitem__("noautomute", s),
        ))
        lb_pb.add(self._switch_row(
            "Disable audio-reactive effects", "audio-input-microphone-symbolic",
            self.config["no_audio_processing"],
            lambda s: self.config.__setitem__("no_audio_processing", s),
        ))
        self._inner.pack_start(self._padded(lb_pb), False, False, 0)

        # ── Section: Wallpaper Properties ─────────────────────────────────
        if wp.properties:
            self._inner.pack_start(self._separator(), False, False, 0)
            self._inner.pack_start(
                self._section_header("preferences-other-symbolic", "Wallpaper Properties"),
                False, False, 0,
            )
            lb_props = Gtk.ListBox()
            lb_props.set_selection_mode(Gtk.SelectionMode.NONE)
            lb_props.get_style_context().add_class("boxed-list")

            saved_props = (
                self.config.get("wallpaper_properties", {})
                    .get(wp.workshop_id, {})
            )

            for pname, pdef in wp.properties.items():
                ptype = pdef.get("type", "")
                plabel = pdef.get("text", pname)
                pval   = saved_props.get(pname, pdef.get("value", ""))
                row = self._property_row(pname, plabel, ptype, pval, pdef)
                if row:
                    lb_props.add(row)

            self._inner.pack_start(self._padded(lb_props), False, False, 0)

        # Bottom padding
        self._inner.pack_start(Gtk.Box(margin_bottom=16), False, False, 0)
        self._inner.show_all()

    # ── Row builder helpers ───────────────────────────────────────────────

    @staticmethod
    def _separator() -> Gtk.Separator:
        sep = Gtk.Separator()
        sep.set_margin_top(4)
        sep.set_margin_bottom(4)
        return sep

    @staticmethod
    def _section_header(icon_name: str, label_text: str) -> Gtk.Box:
        box = Gtk.Box(spacing=6)
        box.set_margin_top(10)
        box.set_margin_bottom(4)
        box.set_margin_start(16)
        box.set_margin_end(16)
        icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.SMALL_TOOLBAR)
        icon.get_style_context().add_class("dim-label")
        lbl = Gtk.Label(label=label_text)
        lbl.set_xalign(0.0)
        lbl.get_style_context().add_class("heading")
        box.pack_start(icon, False, False, 0)
        box.pack_start(lbl, False, False, 0)
        return box

    @staticmethod
    def _padded(widget: Gtk.Widget) -> Gtk.Box:
        box = Gtk.Box()
        box.set_margin_top(2)
        box.set_margin_bottom(8)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.pack_start(widget, True, True, 0)
        return box

    @staticmethod
    def _row_shell() -> tuple:
        """Return (ListBoxRow, inner_hbox)."""
        row = Gtk.ListBoxRow()
        box = Gtk.Box(spacing=12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(14)
        box.set_margin_end(14)
        row.add(box)
        return row, box

    def _spin_row(self, label: str, lo: int, hi: int, value: int,
                  callback) -> Gtk.ListBoxRow:
        row, box = self._row_shell()
        lbl = Gtk.Label(label=label)
        lbl.set_xalign(0.0)
        lbl.set_hexpand(True)
        box.pack_start(lbl, True, True, 0)
        adj  = Gtk.Adjustment(value=value, lower=lo, upper=hi, step_increment=1)
        spin = Gtk.SpinButton(adjustment=adj, digits=0)
        spin.set_numeric(True)
        spin.connect("value-changed", lambda w: callback(w.get_value()))
        box.pack_end(spin, False, False, 0)
        return row

    def _scale_row(self, label: str, icon: str, lo: float, hi: float,
                   value: float, callback) -> Gtk.ListBoxRow:
        row, box = self._row_shell()
        lbl = Gtk.Label(label=label)
        lbl.set_xalign(0.0)
        box.pack_start(lbl, False, False, 0)
        adj   = Gtk.Adjustment(value=value, lower=lo, upper=hi, step_increment=1)
        scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.set_hexpand(True)
        scale.connect("value-changed", lambda w: callback(w.get_value()))
        box.pack_start(scale, True, True, 0)
        return row

    def _switch_row(self, label: str, icon: str, active: bool,
                    callback) -> Gtk.ListBoxRow:
        row, box = self._row_shell()
        lbl = Gtk.Label(label=label)
        lbl.set_xalign(0.0)
        lbl.set_hexpand(True)
        lbl.set_line_wrap(True)
        box.pack_start(lbl, True, True, 0)
        sw = Gtk.Switch()
        sw.set_active(active)
        sw.set_valign(Gtk.Align.CENTER)
        sw.connect("state-set", lambda w, s: (callback(s), False)[1])
        box.pack_end(sw, False, False, 0)
        return row

    def _property_row(self, pname: str, label: str, ptype: str,
                      value: str, pdef: dict) -> Gtk.ListBoxRow | None:
        row, box = self._row_shell()
        lbl = Gtk.Label(label=label)
        lbl.set_xalign(0.0)
        lbl.set_hexpand(True)
        lbl.set_line_wrap(True)
        box.pack_start(lbl, True, True, 0)

        widget = None
        getter = None

        if ptype == "bool":
            sw = Gtk.Switch()
            sw.set_active(str(value).strip() in ("1", "true", "True"))
            sw.set_valign(Gtk.Align.CENTER)
            widget = sw
            getter = lambda w=sw: "1" if w.get_active() else "0"

        elif ptype == "slider":
            lo  = float(pdef.get("min", 0))
            hi  = float(pdef.get("max", 1))
            try:
                cur = float(value)
            except Exception:
                cur = lo
            adj   = Gtk.Adjustment(value=cur, lower=lo, upper=hi,
                                   step_increment=(hi - lo) / 100.0)
            sc    = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
            sc.set_draw_value(True)
            sc.set_value_pos(Gtk.PositionType.RIGHT)
            sc.set_size_request(130, -1)
            widget = sc
            getter = lambda w=sc: str(w.get_value())

        elif ptype == "color":
            cb = Gtk.ColorButton()
            try:
                parts = [float(x) for x in str(value).split()]
                if len(parts) >= 3:
                    rgba = Gdk.RGBA()
                    rgba.red   = parts[0]
                    rgba.green = parts[1]
                    rgba.blue  = parts[2]
                    rgba.alpha = 1.0
                    cb.set_rgba(rgba)
            except Exception:
                pass
            widget = cb
            def _color_getter(w=cb):
                c = w.get_rgba()
                return f"{c.red:.4f} {c.green:.4f} {c.blue:.4f}"
            getter = _color_getter

        elif ptype == "combo":
            options = pdef.get("options", [])
            cb = Gtk.ComboBoxText()
            for opt in options:
                cb.append_text(str(opt))
            try:
                cb.set_active(list(options).index(value))
            except Exception:
                cb.set_active(0)
            widget = cb
            getter = lambda w=cb: w.get_active_text() or ""

        else:
            # textinput / unknown → plain Entry
            ent = Gtk.Entry()
            ent.set_text(str(value))
            ent.set_size_request(130, -1)
            widget = ent
            getter = lambda w=ent: w.get_text()

        if widget and getter:
            box.pack_end(widget, False, False, 0)
            self._prop_saves[pname] = getter
            return row

        return None


# ─────────────────────────────────────────────────────────────────────────────
# Preferences dialog
# ─────────────────────────────────────────────────────────────────────────────

class PreferencesDialog(Gtk.Dialog):

    def __init__(self, parent: Gtk.Window, config: Config) -> None:
        super().__init__(
            title="Preferences",
            transient_for=parent,
            modal=True,
            use_header_bar=True,
        )
        self.config = config
        self.set_default_size(500, -1)
        self.set_resizable(False)

        area = self.get_content_area()

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        outer.set_margin_top(20)
        outer.set_margin_bottom(20)
        outer.set_margin_start(20)
        outer.set_margin_end(20)

        # ── Engine ────────────────────────────────────────────────────────
        outer.pack_start(self._heading("Engine"), False, False, 0)
        eng_lb = self._listbox()

        # Binary path
        self._bin_entry = Gtk.Entry()
        self._bin_entry.set_text(config["binary_path"])
        self._bin_entry.set_placeholder_text("linux-wallpaperengine")
        self._bin_entry.set_hexpand(True)
        eng_lb.add(self._entry_row("Executable", self._bin_entry))

        # Assets dir
        self._assets_entry = Gtk.Entry()
        self._assets_entry.set_text(config.get("assets_dir", ""))
        self._assets_entry.set_placeholder_text("(auto-detect)")
        self._assets_entry.set_hexpand(True)
        eng_lb.add(self._folder_row("Assets Directory", self._assets_entry, parent))

        outer.pack_start(eng_lb, False, False, 0)

        # ── Wallpaper library ─────────────────────────────────────────────
        outer.pack_start(self._heading("Wallpaper Library"), False, False, 0)
        lib_lb = self._listbox()

        steam_paths = config.get("steam_paths", [])
        self._steam_entry = Gtk.Entry()
        self._steam_entry.set_text(steam_paths[0] if steam_paths else "")
        self._steam_entry.set_placeholder_text("~/.local/share/Steam/…/431960")
        self._steam_entry.set_hexpand(True)
        lib_lb.add(self._folder_row("Workshop Content Path", self._steam_entry, parent))

        outer.pack_start(lib_lb, False, False, 0)

        # ── System ────────────────────────────────────────────────────────
        outer.pack_start(self._heading("System"), False, False, 0)
        sys_lb = self._listbox()

        row, box = self._row_shell()
        lbl = Gtk.Label(label="Launch on login (autostart)")
        lbl.set_xalign(0.0)
        lbl.set_hexpand(True)
        box.pack_start(lbl, True, True, 0)
        self._autostart_sw = Gtk.Switch()
        self._autostart_sw.set_active(config.get("autostart", False))
        self._autostart_sw.set_valign(Gtk.Align.CENTER)
        box.pack_end(self._autostart_sw, False, False, 0)
        sys_lb.add(row)

        outer.pack_start(sys_lb, False, False, 0)
        area.add(outer)

        # Buttons
        cancel = self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ok     = self.add_button("Save",   Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")

        self.show_all()

    # ── Row/widget helpers ────────────────────────────────────────────────

    @staticmethod
    def _heading(text: str) -> Gtk.Label:
        lbl = Gtk.Label(label=text)
        lbl.set_xalign(0.0)
        lbl.get_style_context().add_class("heading")
        return lbl

    @staticmethod
    def _listbox() -> Gtk.ListBox:
        lb = Gtk.ListBox()
        lb.set_selection_mode(Gtk.SelectionMode.NONE)
        lb.get_style_context().add_class("boxed-list")
        return lb

    @staticmethod
    def _row_shell() -> tuple:
        row = Gtk.ListBoxRow()
        box = Gtk.Box(spacing=12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(14)
        box.set_margin_end(14)
        row.add(box)
        return row, box

    def _entry_row(self, label: str, entry: Gtk.Entry) -> Gtk.ListBoxRow:
        row, box = self._row_shell()
        lbl = Gtk.Label(label=label)
        lbl.set_xalign(0.0)
        lbl.set_hexpand(True)
        box.pack_start(lbl, True, True, 0)
        entry.set_size_request(220, -1)
        box.pack_end(entry, False, False, 0)
        return row

    def _folder_row(self, label: str, entry: Gtk.Entry,
                    parent: Gtk.Window) -> Gtk.ListBoxRow:
        row, box = self._row_shell()
        lbl = Gtk.Label(label=label)
        lbl.set_xalign(0.0)
        lbl.set_hexpand(True)
        box.pack_start(lbl, True, True, 0)
        entry.set_size_request(170, -1)
        box.pack_start(entry, False, False, 0)

        btn = Gtk.Button()
        btn.set_image(Gtk.Image.new_from_icon_name(
            "folder-open-symbolic", Gtk.IconSize.BUTTON
        ))
        btn.set_tooltip_text("Browse…")

        def on_browse(w, e=entry):
            chooser = Gtk.FileChooserDialog(
                title="Choose Folder",
                transient_for=parent,
                action=Gtk.FileChooserAction.SELECT_FOLDER,
            )
            chooser.add_button("_Cancel", Gtk.ResponseType.CANCEL)
            chooser.add_button("_Select", Gtk.ResponseType.OK)
            if e.get_text():
                try:
                    chooser.set_current_folder(e.get_text())
                except Exception:
                    pass
            if chooser.run() == Gtk.ResponseType.OK:
                e.set_text(chooser.get_filename() or "")
            chooser.destroy()

        btn.connect("clicked", on_browse)
        box.pack_end(btn, False, False, 0)
        return row

    # ── Apply ─────────────────────────────────────────────────────────────

    def apply(self) -> None:
        self.config["binary_path"] = self._bin_entry.get_text().strip()
        self.config["assets_dir"]  = self._assets_entry.get_text().strip()

        steam_path = self._steam_entry.get_text().strip()
        if steam_path:
            paths = list(self.config.get("steam_paths", []))
            if paths:
                paths[0] = steam_path
            else:
                paths = [steam_path]
            self.config["steam_paths"] = paths

        autostart = self._autostart_sw.get_active()
        self.config["autostart"] = autostart
        self._write_autostart(autostart)

    def _write_autostart(self, enable: bool) -> None:
        AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
        if enable:
            script = os.path.abspath(__file__)
            content = "\n".join([
                "[Desktop Entry]",
                f"Name={APP_NAME}",
                "Type=Application",
                f"Exec=python3 {script}",
                "Hidden=false",
                "NoDisplay=false",
                "X-GNOME-Autostart-enabled=true",
                "",
            ])
            AUTOSTART_FILE.write_text(content)
        else:
            if AUTOSTART_FILE.exists():
                AUTOSTART_FILE.unlink()


# ─────────────────────────────────────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(Gtk.ApplicationWindow):

    def __init__(self, app: Gtk.Application, config: Config) -> None:
        super().__init__(application=app, title=APP_NAME)
        self.config   = config
        self.engine   = EngineManager(config)
        self.engine.on_stopped = self._on_engine_stopped

        self._monitors:   list               = []
        self._wallpapers: list               = []
        self._selected:   Wallpaper | None   = None
        self._filter_type: str              = "all"   # all/scene/video/web/application
        self._filter_content: str           = "all"   # all/sfw/nsfw

        # Window geometry
        self.set_default_size(config["window_width"], config["window_height"])
        self.set_icon_name("preferences-desktop-wallpaper-symbolic")
        self.connect("delete-event", self._on_delete)

        # Apply CSS
        provider = Gtk.CssProvider()
        provider.load_from_data(APP_CSS.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        # Build everything
        self._build_header()
        self._build_infobar()
        self._build_searchbar()
        self._build_paned()
        self._build_action_bar()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.pack_start(self._infobar,    False, False, 0)
        root.pack_start(self._searchbar,  False, False, 0)
        root.pack_start(self._paned,      True,  True,  0)
        root.pack_start(self._action_bar, False, False, 0)
        self.add(root)

        self.show_all()
        self._infobar.hide()

        # Kick off async init
        GLib.idle_add(self._async_init)

    # ── Header bar ────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        self._header = Gtk.HeaderBar()
        self._header.set_show_close_button(True)
        self._header.set_title(APP_NAME)
        self._header.set_subtitle("Loading library…")
        self.set_titlebar(self._header)

        # Left side
        left = Gtk.Box(spacing=2)

        self._search_btn = Gtk.ToggleButton()
        self._search_btn.set_image(Gtk.Image.new_from_icon_name(
            "edit-find-symbolic", Gtk.IconSize.BUTTON
        ))
        self._search_btn.set_tooltip_text("Search (Ctrl+F)")
        self._search_btn.connect("toggled", self._on_search_toggled)
        left.pack_start(self._search_btn, False, False, 0)

        refresh_btn = Gtk.Button()
        refresh_btn.set_image(Gtk.Image.new_from_icon_name(
            "view-refresh-symbolic", Gtk.IconSize.BUTTON
        ))
        refresh_btn.set_tooltip_text("Reload wallpaper library")
        refresh_btn.connect("clicked", lambda _: self._scan_wallpapers())
        left.pack_start(refresh_btn, False, False, 0)

        self._header.pack_start(left)

        # Right side
        right = Gtk.Box(spacing=2)

        # Thumbnail size scale
        zoom_box  = Gtk.Box(spacing=4)
        zoom_icon = Gtk.Image.new_from_icon_name("zoom-fit-best-symbolic", Gtk.IconSize.MENU)
        zoom_icon.get_style_context().add_class("dim-label")
        zoom_adj  = Gtk.Adjustment(
            value=config["thumb_size"] if (config := self.config) else THUMB_W,
            lower=96, upper=256, step_increment=16,
        )
        self._zoom_scale = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL, adjustment=zoom_adj
        )
        self._zoom_scale.set_draw_value(False)
        self._zoom_scale.set_size_request(100, -1)
        self._zoom_scale.set_tooltip_text("Thumbnail size")
        self._zoom_scale.connect("value-changed", self._on_zoom_changed)
        zoom_box.pack_start(zoom_icon, False, False, 0)
        zoom_box.pack_start(self._zoom_scale, False, False, 0)
        right.pack_start(zoom_box, False, False, 0)

        prefs_btn = Gtk.Button()
        prefs_btn.set_image(Gtk.Image.new_from_icon_name(
            "preferences-system-symbolic", Gtk.IconSize.BUTTON
        ))
        prefs_btn.set_tooltip_text("Preferences")
        prefs_btn.connect("clicked", self._on_prefs_clicked)
        right.pack_start(prefs_btn, False, False, 0)

        self._header.pack_end(right)

        # Keyboard shortcut for search
        accel = Gtk.AccelGroup()
        self.add_accel_group(accel)
        key, mod = Gtk.accelerator_parse("<Control>f")
        self._search_btn.add_accelerator(
            "clicked", accel, key, mod, Gtk.AccelFlags.VISIBLE
        )

    # ── InfoBar ───────────────────────────────────────────────────────────

    def _build_infobar(self) -> None:
        self._infobar = Gtk.InfoBar()
        self._infobar.set_show_close_button(True)
        self._info_label = Gtk.Label()
        self._info_label.set_xalign(0.0)
        self._info_label.set_line_wrap(True)
        self._infobar.get_content_area().add(self._info_label)
        self._infobar.connect("response", lambda ib, _: ib.hide())

    # ── Search bar ────────────────────────────────────────────────────────

    def _build_searchbar(self) -> None:
        self._searchbar   = Gtk.SearchBar()
        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_hexpand(True)
        self._search_entry.connect("search-changed", self._on_search_changed)
        self._searchbar.add(self._search_entry)
        self._searchbar.connect_entry(self._search_entry)

    # ── Paned: browser + detail ───────────────────────────────────────────

    def _build_paned(self) -> None:
        self._paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._paned.set_position(self.config.get("paned_position", 780))

        # ── Left: library browser ──────────────────────────────────────────
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Spinner / flowbox stack
        self._browser_stack = Gtk.Stack()
        self._browser_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._browser_stack.set_transition_duration(150)

        # Loading state
        loading_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12
        )
        loading_box.set_valign(Gtk.Align.CENTER)
        loading_box.set_halign(Gtk.Align.CENTER)
        loading_box.set_vexpand(True)
        spinner = Gtk.Spinner()
        spinner.set_size_request(48, 48)
        spinner.start()
        loading_box.pack_start(spinner, False, False, 0)
        scan_lbl = Gtk.Label(label="Scanning wallpapers…")
        scan_lbl.get_style_context().add_class("dim-label")
        loading_box.pack_start(scan_lbl, False, False, 0)

        # FlowBox inside a ScrolledWindow
        self._flowbox = Gtk.FlowBox()
        self._flowbox.set_valign(Gtk.Align.START)
        self._flowbox.set_max_children_per_line(50)
        self._flowbox.set_min_children_per_line(2)
        self._flowbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._flowbox.set_column_spacing(2)
        self._flowbox.set_row_spacing(2)
        self._flowbox.set_margin_top(8)
        self._flowbox.set_margin_bottom(8)
        self._flowbox.set_margin_start(8)
        self._flowbox.set_margin_end(8)
        self._flowbox.set_filter_func(self._filter_card)
        self._flowbox.set_sort_func(self._sort_card)
        self._flowbox.connect("child-activated", self._on_card_activated)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)
        scroll.add(self._flowbox)

        # Empty state
        self._empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._empty_box.set_valign(Gtk.Align.CENTER)
        self._empty_box.set_halign(Gtk.Align.CENTER)
        self._empty_box.set_vexpand(True)
        empty_icon = Gtk.Image.new_from_icon_name(
            "action-unavailable-symbolic", Gtk.IconSize.DIALOG
        )
        empty_icon.get_style_context().add_class("dim-label")
        self._empty_box.pack_start(empty_icon, False, False, 0)
        empty_lbl = Gtk.Label(label="No wallpapers found")
        empty_lbl.get_style_context().add_class("dim-label")
        self._empty_box.pack_start(empty_lbl, False, False, 0)
        empty_sub = Gtk.Label(
            label="Check your Steam Workshop path in Preferences."
        )
        empty_sub.get_style_context().add_class("caption")
        self._empty_box.pack_start(empty_sub, False, False, 0)
        open_prefs = Gtk.Button(label="Open Preferences")
        open_prefs.set_halign(Gtk.Align.CENTER)
        open_prefs.connect("clicked", self._on_prefs_clicked)
        self._empty_box.pack_start(open_prefs, False, False, 0)

        self._browser_stack.add_named(loading_box,     "loading")
        self._browser_stack.add_named(scroll,          "browser")
        self._browser_stack.add_named(self._empty_box, "empty")

        left.pack_start(self._build_filter_bar(), False, False, 0)
        left.pack_start(self._browser_stack, True, True, 0)
        left.set_size_request(380, -1)

        # ── Right: detail panel ────────────────────────────────────────────
        self._detail = DetailPanel(self.config, self.engine)
        self._detail.set_size_request(360, -1)

        self._paned.pack1(left,         True,  False)
        self._paned.pack2(self._detail, False, False)

    # ── Filter bar ────────────────────────────────────────────────────────

    def _build_filter_bar(self) -> Gtk.Box:
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        bar.get_style_context().add_class("filter-bar")

        # ── Type row ──────────────────────────────────────────────────────
        type_row = Gtk.Box(spacing=6)
        type_row.set_margin_top(6)
        type_row.set_margin_bottom(4)
        type_row.set_margin_start(10)
        type_row.set_margin_end(10)

        type_lbl = Gtk.Label(label="Type")
        type_lbl.get_style_context().add_class("caption")
        type_row.pack_start(type_lbl, False, False, 0)

        self._type_btns: dict = {}
        type_group = None
        for key, label in [
            ("all", "All"), ("scene", "Scene"), ("video", "Video"),
            ("web", "Web"), ("application", "App"),
        ]:
            btn = Gtk.RadioButton(label=label, group=type_group)
            if type_group is None:
                type_group = btn
            btn.set_mode(False)   # look like a button, not a radio dot
            btn.get_style_context().add_class("filter-chip")
            btn.set_active(self._filter_type == key)
            btn.connect("toggled", self._on_type_filter, key)
            type_row.pack_start(btn, False, False, 0)
            self._type_btns[key] = btn

        bar.pack_start(type_row, False, False, 0)

        # ── Content row ───────────────────────────────────────────────────
        content_row = Gtk.Box(spacing=6)
        content_row.set_margin_top(2)
        content_row.set_margin_bottom(6)
        content_row.set_margin_start(10)
        content_row.set_margin_end(10)

        content_lbl = Gtk.Label(label="Content")
        content_lbl.get_style_context().add_class("caption")
        content_row.pack_start(content_lbl, False, False, 0)

        self._content_btns: dict = {}
        content_group = None
        for key, label in [("all", "All"), ("sfw", "SFW"), ("nsfw", "NSFW")]:
            btn = Gtk.RadioButton(label=label, group=content_group)
            if content_group is None:
                content_group = btn
            btn.set_mode(False)
            btn.get_style_context().add_class("filter-chip")
            btn.set_active(self._filter_content == key)
            btn.connect("toggled", self._on_content_filter, key)
            content_row.pack_start(btn, False, False, 0)
            self._content_btns[key] = btn

        bar.pack_start(content_row, False, False, 0)
        return bar

    def _on_type_filter(self, btn: Gtk.RadioButton, key: str) -> None:
        if btn.get_active():
            self._filter_type = key
            self._flowbox.invalidate_filter()
            self._update_count_subtitle()

    def _on_content_filter(self, btn: Gtk.RadioButton, key: str) -> None:
        if btn.get_active():
            self._filter_content = key
            self._flowbox.invalidate_filter()
            self._update_count_subtitle()

    def _update_count_subtitle(self) -> None:
        visible = sum(
            1 for c in self._flowbox.get_children()
            if isinstance(c, WallpaperCard) and self._filter_card(c)
        )
        total = len(self._wallpapers)
        if visible == total:
            self._header.set_subtitle(f"{total} wallpaper{'s' if total != 1 else ''} in library")
        else:
            self._header.set_subtitle(f"{visible} of {total} wallpapers shown")

    # ── Action bar ────────────────────────────────────────────────────────

    def _build_action_bar(self) -> None:
        self._action_bar = Gtk.ActionBar()

        # Stop
        self._stop_btn = Gtk.Button()
        stop_box = Gtk.Box(spacing=6)
        stop_box.pack_start(
            Gtk.Image.new_from_icon_name("media-playback-stop-symbolic", Gtk.IconSize.BUTTON),
            False, False, 0,
        )
        stop_box.pack_start(Gtk.Label(label="Stop"), False, False, 0)
        self._stop_btn.add(stop_box)
        self._stop_btn.set_sensitive(False)
        self._stop_btn.get_style_context().add_class("destructive-action")
        self._stop_btn.set_tooltip_text("Stop the running wallpaper engine process")
        self._stop_btn.connect("clicked", self._on_stop_clicked)
        self._action_bar.pack_start(self._stop_btn)

        # Centre status
        self._status_lbl = Gtk.Label(label="No wallpaper active")
        self._status_lbl.get_style_context().add_class("caption")
        self._status_lbl.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self._status_lbl.set_max_width_chars(55)
        self._action_bar.set_center_widget(self._status_lbl)

        # Apply
        self._apply_btn = Gtk.Button()
        apply_box = Gtk.Box(spacing=6)
        apply_box.pack_start(
            Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON),
            False, False, 0,
        )
        self._apply_lbl = Gtk.Label(label="Apply Wallpaper")
        apply_box.pack_start(self._apply_lbl, False, False, 0)
        self._apply_btn.add(apply_box)
        self._apply_btn.set_sensitive(False)
        self._apply_btn.get_style_context().add_class("suggested-action")
        self._apply_btn.set_tooltip_text("Launch linux-wallpaperengine with current settings")
        self._apply_btn.connect("clicked", self._on_apply_clicked)
        self._action_bar.pack_end(self._apply_btn)

    # ── Async initialisation ──────────────────────────────────────────────

    def _async_init(self) -> bool:
        self._monitors = detect_monitors()
        self._scan_wallpapers()
        return False   # run once

    def _scan_wallpapers(self) -> None:
        self._browser_stack.set_visible_child_name("loading")
        for child in self._flowbox.get_children():
            self._flowbox.remove(child)
        self._wallpapers = []

        def worker() -> None:
            found = []
            seen_real: set = set()   # resolved real paths to catch symlinked duplicates
            for path_str in self.config.get("steam_paths", []):
                p = Path(path_str)
                if not p.exists():
                    continue
                try:
                    real_p = p.resolve()
                    if real_p in seen_real:
                        continue
                    seen_real.add(real_p)
                    items = sorted(p.iterdir(), key=lambda x: x.name)
                except (PermissionError, OSError):
                    continue
                for item in items:
                    if item.is_dir() and (item / "project.json").exists():
                        real_item = item.resolve()
                        if real_item in seen_real:
                            continue
                        seen_real.add(real_item)
                        found.append(Wallpaper(item))
            GLib.idle_add(self._on_scan_done, found)

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_done(self, wallpapers: list) -> bool:
        self._wallpapers = wallpapers

        # Add all cards (thumbnails load lazily via idle_add inside each card)
        for wp in wallpapers:
            card = WallpaperCard(wp, self.config.get("thumb_size", THUMB_W))
            self._flowbox.add(card)
        self._flowbox.show_all()

        n = len(wallpapers)
        if n == 0:
            self._browser_stack.set_visible_child_name("empty")
            self._header.set_subtitle("No wallpapers found")
        else:
            self._browser_stack.set_visible_child_name("browser")
            self._update_count_subtitle()

        return False   # idle_add: run once

    # ── Search ────────────────────────────────────────────────────────────

    def _on_search_toggled(self, btn: Gtk.ToggleButton) -> None:
        active = btn.get_active()
        self._searchbar.set_search_mode(active)
        if active:
            self._search_entry.grab_focus()

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._flowbox.invalidate_filter()
        self._update_count_subtitle()

    def _filter_card(self, child: Gtk.FlowBoxChild) -> bool:
        if not isinstance(child, WallpaperCard):
            return True
        wp = child.wallpaper

        # Type filter
        if self._filter_type != "all" and wp.wp_type.casefold() != self._filter_type:
            return False

        # Content filter
        if self._filter_content == "sfw" and wp.is_nsfw():
            return False
        if self._filter_content == "nsfw" and not wp.is_nsfw():
            return False

        # Search query
        q = self._search_entry.get_text().strip()
        if q and not wp.matches(q):
            return False

        return True

    @staticmethod
    def _sort_card(a: Gtk.FlowBoxChild, b: Gtk.FlowBoxChild) -> int:
        ta = a.wallpaper.title if isinstance(a, WallpaperCard) else ""
        tb = b.wallpaper.title if isinstance(b, WallpaperCard) else ""
        return (ta.casefold() > tb.casefold()) - (ta.casefold() < tb.casefold())

    # ── Card selection ────────────────────────────────────────────────────

    def _on_card_activated(self, flowbox: Gtk.FlowBox, child: Gtk.FlowBoxChild) -> None:
        if not isinstance(child, WallpaperCard):
            return
        self._selected = child.wallpaper
        self._detail.load(child.wallpaper, self._monitors)
        self._apply_btn.set_sensitive(True)
        self._header.set_subtitle(child.wallpaper.title)

    # ── Thumbnail zoom ────────────────────────────────────────────────────

    def _on_zoom_changed(self, scale: Gtk.Scale) -> None:
        size = int(scale.get_value())
        self.config["thumb_size"] = size
        for child in self._flowbox.get_children():
            if isinstance(child, WallpaperCard):
                child.reload_thumb(size)

    # ── Apply / Stop ──────────────────────────────────────────────────────

    def _on_apply_clicked(self, btn: Gtk.Button) -> None:
        if not self._selected:
            return

        self._detail.save_state()
        self.config.save()

        assignments  = self._detail.get_assignments()
        global_opts  = self._detail.get_global_opts()

        if not assignments:
            self._show_info(
                "No monitors are enabled. Tick at least one monitor in the "
                "Monitor Assignment section.",
                Gtk.MessageType.WARNING,
            )
            return

        ok, msg = self.engine.start(assignments, global_opts)
        if ok:
            self._stop_btn.set_sensitive(True)
            self._apply_lbl.set_label("Restart")
            self._status_lbl.set_label(f"Running — {self._selected.title}")
            self._status_lbl.get_style_context().add_class("status-running")
        else:
            self._show_info(msg, Gtk.MessageType.ERROR)

    def _on_stop_clicked(self, btn: Gtk.Button) -> None:
        self.engine.stop()
        self._reset_status()

    def _on_engine_stopped(self) -> None:
        """Called from GLib main loop when the engine exits unexpectedly."""
        self._reset_status()
        self._show_info(
            "The wallpaper engine process exited unexpectedly.",
            Gtk.MessageType.WARNING,
        )

    def _reset_status(self) -> None:
        self._stop_btn.set_sensitive(False)
        self._apply_lbl.set_label("Apply Wallpaper")
        self._status_lbl.set_label("No wallpaper active")
        self._status_lbl.get_style_context().remove_class("status-running")
        if self._selected:
            self._header.set_subtitle(self._selected.title)
        else:
            self._header.set_subtitle("Select a wallpaper to begin")

    # ── InfoBar helper ────────────────────────────────────────────────────

    def _show_info(self, message: str, msg_type: Gtk.MessageType) -> None:
        self._infobar.set_message_type(msg_type)
        self._info_label.set_text(message)
        self._infobar.show()

    # ── Preferences ───────────────────────────────────────────────────────

    def _on_prefs_clicked(self, *_) -> None:
        dlg = PreferencesDialog(self, self.config)
        if dlg.run() == Gtk.ResponseType.OK:
            dlg.apply()
            self.config.save()
            self._scan_wallpapers()
        dlg.destroy()

    # ── Window close ──────────────────────────────────────────────────────

    def _on_delete(self, *_) -> bool:
        w, h = self.get_size()
        self.config["window_width"]   = w
        self.config["window_height"]  = h
        self.config["paned_position"] = self._paned.get_position()
        self.config["thumb_size"]     = int(self._zoom_scale.get_value())
        self.config.save()
        self.engine.stop()
        return False   # allow destroy


# ─────────────────────────────────────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────────────────────────────────────

class WallpaperEngineApp(Gtk.Application):

    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        GLib.set_application_name(APP_NAME)
        GLib.set_prgname(APP_ID)
        self._config = Config()
        self._window: MainWindow | None = None

    def do_activate(self) -> None:
        if self._window is None:
            self._window = MainWindow(self, self._config)
        self._window.present()

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = WallpaperEngineApp()

    # Allow Ctrl+C in the terminal to stop the engine and exit cleanly.
    # GTK installs its own SIGINT handler that ignores it, so we override
    # it via a GLib Unix signal source which fires on the main loop.
    def _on_sigint(*_):
        if app._window:
            app._window.engine.stop()
        app.quit()
        return GLib.SOURCE_CONTINUE

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, _on_sigint)

    sys.exit(app.run(sys.argv))
