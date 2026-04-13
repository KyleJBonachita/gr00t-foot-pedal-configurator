# Ubuntu Single Executable Build

This project can be distributed to another Ubuntu machine without running `pip install` on the target machine.

## Build on Ubuntu

Run the build on Ubuntu, not on Windows. PyInstaller bundles are platform-specific.

```bash
chmod +x build_ubuntu_bundle.sh
./build_ubuntu_bundle.sh
```

The output folder will be:

```bash
dist/
```

The single executable file is:

```bash
dist/footpedal-config
```

Copy that one file to the target Ubuntu machine.

## Run on the target Ubuntu machine

```bash
./footpedal-config
```

You can also double-click `footpedal-config` in the file manager.
It prompts for admin password (pkexec) when needed, then starts the GUI.

If `pkexec` is unavailable, run with elevated permissions:

```bash
sudo -E ./footpedal-config
```

The target machine does not need `pip install` for this app.

## Why your old build had folders

Your previous build used PyInstaller `--onedir`, which outputs one executable plus dependency files in folders.
This build uses PyInstaller `--onefile`, so output is a single executable file.

## App workflow

1. Run **Scan Current Keyboards** (baseline).
2. Plug in the pedal and run **Detect Newly Added Device**.
3. Select the pedal event device path.
4. Choose how many pedal keys you want to configure.
5. For each row:
	- Click **Learn** and press that pedal key.
	- Choose output type: `single`, `combo`, or `macro`.
	- Set output value (for example `C`, `Ctrl+C`, or text).
6. Click **Run Footswitch**.

This remaps only the selected pedal device. Built-in keyboard keys are not modified by this app.

## Important constraints

- Build on the same CPU architecture as the target machine.
- For best compatibility, build on the oldest Ubuntu release you need to support.
- The target machine still needs Linux input access. If grabbing `/dev/input/eventX` fails, run with elevated privileges or configure `uinput` and device permissions.
- The executable bundles Python dependencies, but it does not remove kernel or permission requirements for `evdev` and `uinput`.
