#!/usr/bin/env python
# azeron_mapper.py
import sys
import os
import json
import time
import select  # Import select
from evdev import InputDevice, categorize, ecodes, util

CONFIG_FILE = 'config.json'
config = None
mapping = {}
custom_handlers = {}

# Store D-pad state to only send keyup when released
dpad_state = {'x': 0, 'y': 0}

# --- Global state for analog stick position ---
current_axis_x = 0
current_axis_y = 0
# --- Global state for analog stick position ---

# --- Utility Functions ---
def get_ecode(name_or_code):
    """Get evdev ecode from name or numerical code."""
    if isinstance(name_or_code, int):
        return name_or_code
    if isinstance(name_or_code, str):
        if name_or_code.isdigit():
            return int(name_or_code)
        # Allow lookup by name or code string
        try:
            return getattr(ecodes, name_or_code)
        except AttributeError:
            print(f"Warning: Unknown ecode name '{name_or_code}'", file=sys.stderr)
            return None
    return None

def send_command(command):
    """Sends a command to dotool via stdout."""
    if command and not command.startswith("COMMENT:"):
        print(command, flush=True)

# --- Configuration Loading ---
def load_config():
    global config
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        return True
    except FileNotFoundError:
        print(f"Error: Configuration file '{CONFIG_FILE}' not found.", file=sys.stderr)
    except json.JSONDecodeError as e:
        print(f"Error: Could not parse configuration file '{CONFIG_FILE}': {e}", file=sys.stderr)
    except Exception as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
    return False

# --- Event Handlers ---
def handle_abs_x(value):
    """Handler only updates the current axis state."""
    global current_axis_x
    current_axis_x = value
    # print(f"DEBUG: Stored X = {current_axis_x}", file=sys.stderr)

def handle_abs_y(value):
    """Handler only updates the current axis state."""
    global current_axis_y
    current_axis_y = value
    # print(f"DEBUG: Stored Y = {current_axis_y}", file=sys.stderr)

def handle_dpad_x(value):
    cfg = config.get('dpad')
    if not cfg: return

    current_action = None
    release_action = None

    # Determine new action based on value (-1 left, 1 right, 0 center)
    if value == -1: current_action = cfg.get('left')
    elif value == 1: current_action = cfg.get('right')

    # Determine action to release based on previous state
    if dpad_state['x'] == -1: release_action = cfg.get('left')
    elif dpad_state['x'] == 1: release_action = cfg.get('right')

    # Send keyup for the old direction if it's different from the new one
    if release_action and release_action != current_action and release_action.startswith("key "):
        send_command(f"keyup {release_action.split(' ', 1)[1]}")

    # Send keydown for the new direction if it's different from the old one
    if current_action and current_action != release_action and current_action.startswith("key "):
        send_command(f"keydown {current_action.split(' ', 1)[1]}")

    dpad_state['x'] = value # Update state

def handle_dpad_y(value):
    cfg = config.get('dpad')
    if not cfg: return

    current_action = None
    release_action = None

    # Determine new action based on value (-1 up, 1 down, 0 center)
    if value == -1: current_action = cfg.get('up')
    elif value == 1: current_action = cfg.get('down')

    # Determine action to release based on previous state
    if dpad_state['y'] == -1: release_action = cfg.get('up')
    elif dpad_state['y'] == 1: release_action = cfg.get('down')

    # Send keyup for the old direction if it's different from the new one
    if release_action and release_action != current_action and release_action.startswith("key "):
        send_command(f"keyup {release_action.split(' ', 1)[1]}")

    # Send keydown for the new direction if it's different from the old one
    if current_action and current_action != release_action and current_action.startswith("key "):
        send_command(f"keydown {current_action.split(' ', 1)[1]}")

    dpad_state['y'] = value # Update state

# --- Mapping Population ---
def populate_mappings():
    global mapping, custom_handlers
    mapping = {}
    custom_handlers = {
        # Always include analog stick handlers if configured
        "handle_abs_x": handle_abs_x,
        "handle_abs_y": handle_abs_y,
        "handle_dpad_x": handle_dpad_x,
        "handle_dpad_y": handle_dpad_y,
    }

    # Analog Stick
    stick_cfg = config.get('analog_stick')
    if stick_cfg:
        x_ecode = get_ecode(stick_cfg.get('x_code'))
        y_ecode = get_ecode(stick_cfg.get('y_code'))
        if x_ecode is not None:
             mapping[(ecodes.EV_ABS, x_ecode)] = {None: "handle_abs_x"}
        if y_ecode is not None:
             mapping[(ecodes.EV_ABS, y_ecode)] = {None: "handle_abs_y"}

    # D-Pad
    dpad_cfg = config.get('dpad')
    if dpad_cfg:
        x_ecode = get_ecode(dpad_cfg.get('x_code'))
        y_ecode = get_ecode(dpad_cfg.get('y_code'))
        if x_ecode is not None:
             mapping[(ecodes.EV_ABS, x_ecode)] = {None: "handle_dpad_x"}
        if y_ecode is not None:
             mapping[(ecodes.EV_ABS, y_ecode)] = {None: "handle_dpad_y"}

    # Buttons
    button_cfg = config.get('button_mappings')
    if button_cfg:
        for key_name, actions in button_cfg.items():
            ecode = get_ecode(key_name)
            if ecode is None:
                print(f"Warning: Could not find ecode for '{key_name}' in config.", file=sys.stderr)
                continue

            action_map = {}
            press_action = actions.get('press')
            release_action = actions.get('release')

            if press_action:
                action_map[1] = press_action # Value 1 for press
            if release_action:
                action_map[0] = release_action # Value 0 for release

            if action_map:
                mapping[(ecodes.EV_KEY, ecode)] = action_map

# --- Main Loop ---
def main():
    global current_axis_x, current_axis_y # Allow modification
    if not load_config():
        sys.exit(1)

    populate_mappings()

    device_path = config.get('device_path')
    if not device_path:
        print("Error: 'device_path' not specified in config file.", file=sys.stderr)
        sys.exit(1)

    device = None # Define device outside try block for finally
    try:
        device = InputDevice(device_path)
        device.grab() # Capture input exclusively
        print(f"Listening on {device.name} ({device_path})...", file=sys.stderr)
        print(f"Using config file: {CONFIG_FILE}", file=sys.stderr)

        # --- Initialize analog stick state & get config ---
        stick_cfg = config.get('analog_stick')
        if stick_cfg:
            # Initialize state to the configured center value
            current_axis_x = stick_cfg.get('center', 0)
            current_axis_y = stick_cfg.get('center', 0)
        else:
            # Set defaults if no stick config
            current_axis_x = 0
            current_axis_y = 0
        # x_ecode = get_ecode(stick_cfg.get('x_code')) if stick_cfg else None
        # y_ecode = get_ecode(stick_cfg.get('y_code')) if stick_cfg else None

        # if x_ecode is not None and x_ecode in device.capabilities().get(ecodes.EV_ABS, []):
        #     current_axis_x = device.absinfo[x_ecode].value
        #     print(f"DEBUG: Initial Axis X = {current_axis_x}", file=sys.stderr) # <<< ADD DEBUG
        # if y_ecode is not None and y_ecode in device.capabilities().get(ecodes.EV_ABS, []):
        #     current_axis_y = device.absinfo[y_ecode].value
        #     print(f"DEBUG: Initial Axis Y = {current_axis_y}", file=sys.stderr) # <<< ADD DEBUG
        # --- Initialize analog stick state & get config ---

        poll_interval = 0.01 # Seconds (e.g., 10ms for 100Hz polling)

        while True:
            # Wait for events or timeout
            r, w, x = select.select([device.fd], [], [], poll_interval)

            # 1. Process any available events
            if r:
                try:
                    for event in device.read(): # Read all available events
                        map_key = (event.type, event.code)

                        if map_key in mapping:
                            action_map = mapping[map_key]

                            # Buttons (value 0 or 1)
                            if event.value in action_map:
                                command = action_map[event.value]
                                if command:
                                    send_command(command)
                            # Axes/Dpad (value is position or None -> handler)
                            elif None in action_map:
                                handler_name = action_map[None]
                                if handler_name in custom_handlers:
                                    # Call handler (updates current_axis_x/y or handles dpad)
                                    custom_handlers[handler_name](event.value)
                        # else:
                            # if event.type != ecodes.EV_SYN:
                                # print(f"Unmapped event: {categorize(event)}", file=sys.stderr)
                except BlockingIOError:
                    # No more events to read right now
                    pass
                except OSError as e:
                     # Device disconnected?
                     print(f"\nError reading from device: {e}", file=sys.stderr)
                     break # Exit main loop

            # 2. Poll analog stick state for continuous movement
            if stick_cfg:
                center = stick_cfg['center']
                deadzone = stick_cfg['deadzone']
                sens_x = stick_cfg['sensitivity_x']
                sens_y = stick_cfg['sensitivity_y']
                max_val = stick_cfg['max'] # Use max from config
                invert_y = stick_cfg.get('invert_y', False)
                # Calculate range relative to center (assumes center is midpoint)
                # Use max_val - center for scaling to handle potential non-zero min
                range_size = max_val - center

                # Calculate deltas from the stored current values
                delta_x = current_axis_x - center
                delta_y = current_axis_y - center

                move_x = 0
                move_y = 0

                # Calculate X movement
                if abs(delta_x) > deadzone:
                    if range_size != 0:
                        move_x = int(delta_x * sens_x / range_size)

                # Calculate Y movement
                if abs(delta_y) > deadzone:
                     if range_size != 0:
                         raw_move_y = int(delta_y * sens_y / range_size)
                         move_y = -raw_move_y if invert_y else raw_move_y

                # Send move command if stick is outside deadzone
                if move_x != 0 or move_y != 0:
                    send_command(f"mousemove {move_x} {move_y}")

    except KeyboardInterrupt:
        print("\nExiting.", file=sys.stderr)
    except Exception as e:
         print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
    finally:
        if device:
            try:
                print("Releasing device...", file=sys.stderr)
                # Ensure D-pad keys are released on exit
                if 'dpad' in config:
                    if dpad_state['x'] != 0: handle_dpad_x(0)
                    if dpad_state['y'] != 0: handle_dpad_y(0)
                device.ungrab() # Release the device
                print("Device released.", file=sys.stderr)
            except Exception as e:
                 print(f"Error during cleanup: {e}", file=sys.stderr)


if __name__ == "__main__":
    # Check permissions
    if os.geteuid() != 0:
         pass # Input group check could be added here if needed
         # print("Warning: Script might need root privileges or user in 'input' group to access device.", file=sys.stderr)

    main()