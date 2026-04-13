import argparse
import importlib
import json
import string
import sys
import time
from dataclasses import dataclass


def load_evdev():
    try:
        mod = importlib.import_module("evdev")
        return mod, mod.ecodes
    except Exception as exc:
        print("Missing dependency: evdev. Install with: pip install evdev", file=sys.stderr)
        raise SystemExit(1) from exc


def key_name_from_token(token: str) -> str:
    cleaned = token.strip()
    upper = cleaned.upper()

    aliases = {
        "SPACE": "KEY_SPACE",
        "ENTER": "KEY_ENTER",
        "RETURN": "KEY_ENTER",
        "TAB": "KEY_TAB",
        "ESC": "KEY_ESC",
        "ESCAPE": "KEY_ESC",
        "BACKSPACE": "KEY_BACKSPACE",
        "UP": "KEY_UP",
        "DOWN": "KEY_DOWN",
        "LEFT": "KEY_LEFT",
        "RIGHT": "KEY_RIGHT",
        "CTRL": "KEY_LEFTCTRL",
        "ALT": "KEY_LEFTALT",
        "SHIFT": "KEY_LEFTSHIFT",
        "SUPER": "KEY_LEFTMETA",
        "WIN": "KEY_LEFTMETA",
        "CMD": "KEY_LEFTMETA",
    }

    if upper.startswith("KEY_"):
        return upper

    if upper in aliases:
        return aliases[upper]

    if len(cleaned) == 1:
        ch = cleaned
        if ch.isalpha():
            return f"KEY_{ch.upper()}"
        if ch.isdigit():
            return f"KEY_{ch}"
        if ch == " ":
            return "KEY_SPACE"

    return ""


def key_code_from_token(token: str, ecodes) -> int:
    key_name = key_name_from_token(token)
    if not key_name:
        raise ValueError(f"Unsupported key token: {token}")

    code = ecodes.ecodes.get(key_name)
    if code is None:
        raise ValueError(f"Unknown key name: {key_name}")

    if isinstance(code, list):
        code = code[0]

    return int(code)


@dataclass
class Action:
    mode: str
    single_code: int | None = None
    combo_codes: list[int] | None = None
    macro_chars: str | None = None


def parse_mappings_json(raw_json: str) -> list[dict]:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for mappings: {exc}") from exc

    if not isinstance(data, list) or not data:
        raise ValueError("Mappings must be a non-empty JSON array.")

    normalized = []
    for index, entry in enumerate(data, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Mapping {index} must be an object.")

        trigger_code = entry.get("trigger_code")
        mode = str(entry.get("mode") or "").strip().lower()
        output = str(entry.get("output") or "")

        if not isinstance(trigger_code, int) or trigger_code <= 0:
            raise ValueError(f"Mapping {index} has invalid trigger_code.")

        if mode not in {"single", "combo", "macro"}:
            raise ValueError(f"Mapping {index} has invalid mode: {mode}")

        if not output.strip():
            raise ValueError(f"Mapping {index} output cannot be empty.")

        normalized.append({"trigger_code": trigger_code, "mode": mode, "output": output})

    return normalized


def build_action(mode: str, output: str, ecodes) -> Action:
    if mode == "single":
        return Action(mode=mode, single_code=key_code_from_token(output.strip(), ecodes))

    if mode == "combo":
        parts = [part.strip() for part in output.split("+") if part.strip()]
        if len(parts) < 2:
            raise ValueError("Combo output must contain at least 2 keys, example: Ctrl+C")
        codes = [key_code_from_token(part, ecodes) for part in parts]
        return Action(mode=mode, combo_codes=codes)

    return Action(mode="macro", macro_chars=output)


def build_action_map(mappings: list[dict], ecodes) -> dict[int, Action]:
    action_map: dict[int, Action] = {}

    for index, mapping in enumerate(mappings, start=1):
        trigger_code = int(mapping["trigger_code"])
        if trigger_code in action_map:
            raise ValueError(f"Duplicate trigger_code in mapping {index}: {trigger_code}")

        action_map[trigger_code] = build_action(mapping["mode"], mapping["output"], ecodes)

    if not action_map:
        raise ValueError("No mappings configured.")

    return action_map


def char_to_keycode(ch: str, ecodes) -> tuple[int, bool] | None:
    if ch in string.ascii_lowercase:
        return key_code_from_token(ch, ecodes), False
    if ch in string.ascii_uppercase:
        return key_code_from_token(ch, ecodes), True
    if ch in string.digits:
        return key_code_from_token(ch, ecodes), False

    punctuation = {
        " ": ("KEY_SPACE", False),
        "\n": ("KEY_ENTER", False),
        "\t": ("KEY_TAB", False),
        ".": ("KEY_DOT", False),
        ",": ("KEY_COMMA", False),
        "/": ("KEY_SLASH", False),
        "-": ("KEY_MINUS", False),
        "=": ("KEY_EQUAL", False),
        ";": ("KEY_SEMICOLON", False),
        "'": ("KEY_APOSTROPHE", False),
    }

    shifted = {
        "!": "KEY_1",
        "@": "KEY_2",
        "#": "KEY_3",
        "$": "KEY_4",
        "%": "KEY_5",
        "^": "KEY_6",
        "&": "KEY_7",
        "*": "KEY_8",
        "(": "KEY_9",
        ")": "KEY_0",
        "_": "KEY_MINUS",
        "+": "KEY_EQUAL",
        ":": "KEY_SEMICOLON",
        '"': "KEY_APOSTROPHE",
        "?": "KEY_SLASH",
        ">": "KEY_DOT",
        "<": "KEY_COMMA",
    }

    if ch in punctuation:
        name, needs_shift = punctuation[ch]
        code = ecodes.ecodes.get(name)
        return (int(code[0] if isinstance(code, list) else code), needs_shift)

    if ch in shifted:
        name = shifted[ch]
        code = ecodes.ecodes.get(name)
        return (int(code[0] if isinstance(code, list) else code), True)

    return None


def write_key(ui, ecodes, code: int, value: int):
    ui.write(ecodes.EV_KEY, code, value)


def tap_key(ui, ecodes, code: int):
    write_key(ui, ecodes, code, 1)
    write_key(ui, ecodes, code, 0)
    ui.syn()


def emit_single(ui, ecodes, code: int):
    tap_key(ui, ecodes, code)


def emit_combo(ui, ecodes, codes: list[int]):
    for code in codes:
        write_key(ui, ecodes, code, 1)
    ui.syn()
    time.sleep(0.01)
    for code in reversed(codes):
        write_key(ui, ecodes, code, 0)
    ui.syn()


def emit_macro(ui, ecodes, text: str):
    shift_code = key_code_from_token("SHIFT", ecodes)

    for ch in text:
        converted = char_to_keycode(ch, ecodes)
        if not converted:
            continue

        code, needs_shift = converted
        if needs_shift:
            write_key(ui, ecodes, shift_code, 1)
            ui.syn()

        tap_key(ui, ecodes, code)

        if needs_shift:
            write_key(ui, ecodes, shift_code, 0)
            ui.syn()

        time.sleep(0.005)


def resolve_output_codes(action_map: dict[int, Action], ecodes) -> list[int]:
    codes: set[int] = set()
    shift_code = key_code_from_token("SHIFT", ecodes)

    for action in action_map.values():
        if action.mode == "single" and action.single_code is not None:
            codes.add(action.single_code)
        elif action.mode == "combo" and action.combo_codes:
            codes.update(action.combo_codes)
        elif action.mode == "macro" and action.macro_chars:
            for ch in action.macro_chars:
                converted = char_to_keycode(ch, ecodes)
                if converted:
                    code, needs_shift = converted
                    codes.add(code)
                    if needs_shift:
                        codes.add(shift_code)

    if not codes:
        raise ValueError("No output keycodes could be resolved from mappings.")

    return sorted(codes)


def run_loop(evdev, ecodes, device_path: str, action_map: dict[int, Action]):
    device = evdev.InputDevice(device_path)
    output_codes = resolve_output_codes(action_map, ecodes)
    ui = evdev.UInput({ecodes.EV_KEY: output_codes}, name="FootPedalRemapper")

    print(f"Listening on pedal device: {device_path}")
    print("Unmapped pedal keys are blocked. Press Ctrl+C to stop.")

    try:
        device.grab()
    except PermissionError:
        ui.close()
        device.close()
        print("Permission denied while grabbing the pedal device.", file=sys.stderr)
        print("Run with sudo or add user to input/uinput groups.", file=sys.stderr)
        raise SystemExit(1)

    try:
        for event in device.read_loop():
            if event.type != ecodes.EV_KEY:
                continue
            if event.value != 1:
                continue

            action = action_map.get(int(event.code))
            if not action:
                continue

            if action.mode == "single" and action.single_code is not None:
                emit_single(ui, ecodes, action.single_code)
            elif action.mode == "combo" and action.combo_codes:
                emit_combo(ui, ecodes, action.combo_codes)
            elif action.mode == "macro" and action.macro_chars is not None:
                emit_macro(ui, ecodes, action.macro_chars)

    except KeyboardInterrupt:
        pass
    finally:
        try:
            device.ungrab()
        except Exception:
            pass
        ui.close()
        device.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Linux foot pedal remapper using evdev")
    parser.add_argument("--device", required=True, help="Pedal event device path, example /dev/input/event12")
    parser.add_argument("--mappings-json", required=True, help="JSON array with trigger_code/mode/output")
    args = parser.parse_args(argv)

    evdev, ecodes = load_evdev()

    try:
        mappings = parse_mappings_json(args.mappings_json)
        action_map = build_action_map(mappings, ecodes)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)

    run_loop(evdev, ecodes, args.device, action_map)


if __name__ == "__main__":
    main()
