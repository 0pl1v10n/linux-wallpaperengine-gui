# 🖼️ Linux Wallpaper Engine GUI

A lightweight GTK-based graphical interface for managing and applying animated Steam Workshop wallpapers on Linux using [`linux-wallpaperengine`](https://github.com/Almamu/linux-wallpaperengine).

This tool removes the need to manually run CLI commands by providing a simple, Steam-like UI for browsing, selecting, and applying wallpapers across multiple screens.

---

## ✨ Features

* 🎨 Browse Steam Workshop wallpaper collection locally
* 🖥️ Multi-monitor support (assign wallpapers per screen)
* ⚡ Fast wallpaper switching using `linux-wallpaperengine`
* 🎛️ Adjustable settings (FPS, engine path, etc.)
* 🧠 Remembers selected wallpapers per screen
* 🧹 Built-in process control (kill running wallpapers)
* 📦 Desktop integration support (.desktop file creation)
* 🧰 CLI + GUI hybrid workflow

---

## 📦 Requirements

Make sure you have the following installed:

* Python 3
* GTK (PyGObject / GTK bindings)
* GdkPixbuf
* `linux-wallpaperengine` binary
* Steam
* Wallpaper Engine (Offical)

---

## 🚀 Installation

### 1. Install dependencies

**Arch-based:**

```bash
sudo pacman -S python python-gobject gtk3 gdk-pixbuf2
```

**Debian/Ubuntu:**

```bash
sudo apt install python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0
```

### 2. Install linux-wallpaperengine

Follow:
[https://github.com/Almamu/linux-wallpaperengine](https://github.com/Almamu/linux-wallpaperengine)

Ensure the binary is available and working:

```bash
linux-wallpaperengine --help
```

---

## ▶️ Usage

Run the GUI:

```bash
python3 main.py
```

---

## ⚙️ CLI Options

This project also supports command-line usage for automation:

### Apply wallpapers and exit

```bash
python3 main.py --apply
```

### Kill running wallpaper engine processes

```bash
python3 main.py --kill
```

### Create / update desktop entry

```bash
python3 main.py --new-desktop
```

---

## 🖥️ How it works

1. The app scans your Steam Workshop wallpaper directory
2. Wallpapers are displayed in a GTK interface
3. You assign wallpapers per monitor
4. On apply, it runs `linux-wallpaperengine` with the correct arguments
5. Process is managed automatically (start/stop/update)

---

## 📁 Configuration

Config files are stored locally (typically under):

```
~/.config/linux-wallpaperengine-gui/
```

This includes:

* Screen assignments
* Engine path
* FPS settings
* Saved preferences

---

## 🔧 Desktop Integration

When running:

```bash
python3 main.py --new-desktop
```

A `.desktop` file is created so you can launch it from your application menu.

---

## 🧠 Tips

* If wallpapers don’t apply, check engine path in settings
* Use `--kill` if wallpapers get stuck running in background
* Best performance is achieved when FPS is tuned (30–60 recommended)

---

## ⚠️ Notes

* Requires `linux-wallpaperengine` to function
* Works best on X11 or Wayland compositors with proper support
* Some wallpapers may behave differently depending on system rendering
---

## ❤️ Credits

* [https://github.com/Almamu/linux-wallpaperengine](https://github.com/Almamu/linux-wallpaperengine)
* Steam Wallpaper Engine community
* GTK / PyGObject ecosystem
