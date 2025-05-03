#!/usr/bin/env python3

import subprocess
import sys
import re
import os
import time
import select

# Import evdev
from evdev import InputDevice, categorize, ecodes, util

# --- Configuration ---

# TODO: Replace with your keyboard's event device
# Find using: ls /dev/input/by-id/
# Example: '/dev/input/event5'
EVENT_DEVICE = '/dev/input/event12'

# Map original key names to dotool commands for DEEP PRESS (value 2)
# Example: 'KEY_SPACE': 'key ctrl+shift+s'
DEEP_PRESS_ACTIONS = {
    'KEY_SPACE': 'type "Deep Space!"',
    'KEY_RIGHTALT': 'key super+tab',
    'KEY_DOWN': 'key pagedown',
    # Add more mappings here
}

# Map original key names to dotool commands for NORMAL PRESS (value 1 -> 0)
# If a key isn't listed, its normal press will be simulated directly.
# Example: 'KEY_SPACE': 'key space' (default behavior if not specified)
NORMAL_PRESS_ACTIONS = {
    'KEY_ENTER': 'key enter', # Example of explicitly defining normal behavior
    # Add more mappings if you want to change normal behavior too
}

# Threshold (in seconds) to distinguish deep press from repeat
# If value 2 arrives within this time after value 1, it's deep.
# Adjust this based on testing (0.150 = 150ms)
DEEP_PRESS_THRESHOLD = 0.150

# --- End Configuration ---

# EVTEST_CMD = ['stdbuf', '-oL', 'evtest', EVENT_DEVICE] # Replaced by evdev
# DOTOOLC_CMD = ['dotoolc'] # Using pipe to dotool

# Regex to capture relevant EV_KEY events - No longer needed
# Example line: Event: time 1746280877.082750, type 1 (EV_KEY), code 57 (KEY_SPACE), value 1
# EVENT_REGEX = re.compile(r"Event: .* type 1 \(EV_KEY\), code (\d+) \((KEY_\w+)\), value ([012])")

def run_dotool_command(command_str):
    """Sends a command string to dotool via standard output."""
    # print(f"DEBUG: Sending dotool command: {command_str}", file=sys.stderr) # Uncomment for debugging
    print(command_str, flush=True)
    

def get_default_normal_action(key_name):
    """Generates the default dotool command for a normal key press."""
    # Convert KEY_XYZ to xyz (lowercase) for dotool, handle special cases if needed
    # Handle if key_name already lacks KEY_ prefix from ecodes
    simple_name = key_name
    if simple_name.startswith('KEY_'):
        simple_name = simple_name.replace('KEY_', '').lower()
    else:
        simple_name = simple_name.lower() # Ensure lowercase if no prefix

    # Basic mapping, might need refinement for specific keys like shift, ctrl etc.
    # Example: dotool uses 'leftshift', evdev uses 'KEY_LEFTSHIFT'
    # We might need a small mapping here if defaults don't work
    special_cases = {
        'leftshift': 'shift',
        'rightshift': 'shift',
        'leftctrl': 'ctrl',
        'rightctrl': 'ctrl',
        'leftalt': 'alt',
        'rightalt': 'altgr', # Common mapping, adjust if needed
        'leftmeta': 'super', # Often Super/Win key
        'rightmeta': 'super',
        # Add others as needed, e.g., capslock, numlock
    }
    simple_name = special_cases.get(simple_name, simple_name)

    return f"key {simple_name}"


def main():
    if not EVENT_DEVICE:
        print("Error: EVENT_DEVICE is not set in the script.", file=sys.stderr)
        print("Please find your keyboard's event device (e.g., /dev/input/eventX) and set it.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(EVENT_DEVICE):
         print(f"Error: Event device '{EVENT_DEVICE}' not found.", file=sys.stderr)
         sys.exit(1)

    # Check for dotoold - simple check by trying to run dotoolc help
    # try:
    #     subprocess.run([DOTOOLC_CMD[0], '--help'], check=True, capture_output=True)
    #     print("dotoold seems available.", file=sys.stderr)
    # except (subprocess.CalledProcessError, FileNotFoundError):
    #      print("Error: 'dotoolc --help' failed. Is dotoold running and dotool installed?", file=sys.stderr)
    #      sys.exit(1)


    print(f"Attempting to listen on {EVENT_DEVICE} using evdev...", file=sys.stderr)
    print(f"Deep press mappings: {DEEP_PRESS_ACTIONS}", file=sys.stderr)
    print(f"Normal press mappings: {NORMAL_PRESS_ACTIONS}", file=sys.stderr)

    # Keep track of the state of pressed keys: {code: state (1 or 2)}
    key_states = {}
    # Track modifier states specifically for combinations like Ctrl+C
    # ctrl_pressed = False # Removed
    # Keep track of the timestamp of the initial press (value 1) for deep keys
    key_press_times = {}
    # Keep track of the key name associated with a code: {code: key_name}
    # key_names = {} # No longer needed, get name directly from event.code

    device = None # Define outside try for finally block
    try:
        # Start evtest - Replaced with evdev
        # evtest_proc = subprocess.Popen(EVTEST_CMD, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

        device = InputDevice(EVENT_DEVICE)
        device.grab() # <<< GRAB DEVICE EXCLUSIVELY
        print(f"Successfully grabbed {device.name} ({EVENT_DEVICE}). Listening for events...", file=sys.stderr)

        # Process evtest output line by line - Replaced with evdev loop
        # for line in iter(evtest_proc.stdout.readline, ''):
        for event in device.read_loop():
            # We only care about key events
            if event.type == ecodes.EV_KEY:
                # Use categorize to get more info, including key name
                # categorized_event = categorize(event)

                # Get key name from event code
                try:
                    key_name = ecodes.KEY[event.code]
                except KeyError:
                    # print(f"DEBUG: Unknown key code: {event.code}", file=sys.stderr)
                    continue # Skip unknown key codes

                code = event.code
                value = event.value # 0=release, 1=press, 2=hold/repeat (or deep press here)
                # print(f"DEBUG: code={code}, key_name={key_name}, value={value}", file=sys.stderr) # Uncomment for debugging

                # --- Handle Ctrl State for Ctrl+C --- 
                # if code == ecodes.KEY_LEFTCTRL or code == ecodes.KEY_RIGHTCTRL:
                #     if value == 1: # Ctrl pressed
                #         ctrl_pressed = True
                #     elif value == 0: # Ctrl released
                #         ctrl_pressed = False
                #     # Also update key_states for general logic if needed (e.g., if Ctrl has deep press)
                #     if value in [1, 2]:
                #          if code not in key_states: key_states[code] = 1
                #     elif value == 0:
                #          key_states.pop(code, None)
                #     continue # Handled Ctrl state, move to next event

                # --- Handle C press for Ctrl+C --- 
                # if key_name == 'KEY_C' and value == 1 and ctrl_pressed:
                #     print("DEBUG: Ctrl+C detected. Exiting.", file=sys.stderr)
                #     raise KeyboardInterrupt

                # --- Normal Key/Deep Press Logic --- 
                if value == 1: # Key press initiated
                    if code not in key_states: # Only act on initial press, ignore repeats sending value 1
                        press_time = event.timestamp() # Get precise time
                        # Is this a key configured for deep press?
                        if key_name in DEEP_PRESS_ACTIONS:
                            key_states[code] = 1 # Mark as normally pressed, waiting for deep or release
                            key_press_times[code] = press_time # Store press time
                            print(f"DEBUG: Key {key_name} ({code}) INITIAL press detected (Deep Action Exists). State -> 1 at {press_time:.4f}", file=sys.stderr)
                        else:
                            # Not a deep press key, run normal action immediately
                            # key_states[code] = 1 # No need to track state 1 if action is immediate
                            print(f"DEBUG: Key {key_name} ({code}) NORMAL press detected (no deep action). Running action.", file=sys.stderr)
                            normal_action = NORMAL_PRESS_ACTIONS.get(key_name, get_default_normal_action(key_name))
                            print(f"DEBUG: Running NORMAL action for {key_name}: {normal_action}", file=sys.stderr)
                            run_dotool_command(normal_action)
                            # Set state to prevent release action / repeats causing issues
                            key_states[code] = 99 # Mark as 'normal action done'

                elif value == 2: # Deep press / Repeat
                    # Check if it's a potentially deep key currently in state 1
                    if key_states.get(code) == 1 and key_name in DEEP_PRESS_ACTIONS:
                        current_time = event.timestamp()
                        time_diff = current_time - key_press_times.get(code, current_time) # Calculate diff
                        print(f"DEBUG: Key {key_name} ({code}) Value 2 detected. Time diff: {time_diff:.4f}s", file=sys.stderr)

                        # Check if within threshold for deep press
                        if time_diff < DEEP_PRESS_THRESHOLD:
                            key_states[code] = 2 # Mark as deep pressed
                            print(f"DEBUG: Key {key_name} ({code}) DEEP PRESS DETECTED (time < threshold). State -> 2", file=sys.stderr)
                            action = DEEP_PRESS_ACTIONS[key_name]
                            print(f"DEBUG: Running DEEP action for {key_name}: {action}", file=sys.stderr)
                            run_dotool_command(action)
                        # else: # Time difference too large, assume it's a normal repeat/hold
                            # print(f"DEBUG: Key {key_name} ({code}) Repeat detected (time >= threshold). Ignoring value 2.", file=sys.stderr)
                            # Keep state as 1

                elif value == 0: # Key released
                    previous_state = key_states.pop(code, None)
                    key_press_times.pop(code, None) # Remove timestamp too
                    # Only act if released from state 1 (meaning deep press didn't happen)
                    # AND it was a deep-configurable key (otherwise action was done on press, state is 99)
                    if previous_state == 1 and key_name in DEEP_PRESS_ACTIONS:
                        print(f"DEBUG: Key {key_name} ({code}) NORMAL release detected (State was 1, Deep Action Existed).", file=sys.stderr)
                        normal_action = NORMAL_PRESS_ACTIONS.get(key_name, get_default_normal_action(key_name))
                        print(f"DEBUG: Running NORMAL action for {key_name}: {normal_action}", file=sys.stderr)
                        run_dotool_command(normal_action)
                    # else: # Ignore releases from state 2 (deep) or state 99 (normal action done) or None (no state)
                        # print(f"DEBUG: Key {key_name} ({code}) release ignored. Previous state: {previous_state}", file=sys.stderr)



        # Check if evtest exited unexpectedly - Not applicable anymore
        # evtest_proc.wait()
        # if evtest_proc.returncode != 0:
            # print(f"\nevtest exited with error code: {evtest_proc.returncode}", file=sys.stderr)
            # stderr_output = evtest_proc.stderr.read()
            # if "permission denied" in stderr_output.lower():
                # print(f"Error: Permission denied for {EVENT_DEVICE}. Add user to 'input' group?", file=sys.stderr)
                # print("Try: sudo usermod -a -G input $USER (then log out/in or reboot)", file=sys.stderr)
            # else:
                # print("evtest stderr:", file=sys.stderr)
                # print(stderr_output, file=sys.stderr)

    except PermissionError:
         print(f"Error: Permission denied accessing {EVENT_DEVICE}. Run with sudo?", file=sys.stderr)
         sys.exit(1)
    except FileNotFoundError:
         print(f"Error: Device {EVENT_DEVICE} not found. Is it plugged in? Correct path?", file=sys.stderr)
         sys.exit(1)
    except OSError as e:
        # Handle device disconnection during operation
        print(f"\nError reading from device {EVENT_DEVICE}: {e}. Device disconnected?", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nExiting script.", file=sys.stderr)
    finally:
        if device:
            try:
                device.ungrab() # <<< RELEASE THE GRAB
                print(f"Device {EVENT_DEVICE} ungrabbed.", file=sys.stderr)
            except OSError as e:
                print(f"Error ungrabbing device (was it disconnected?): {e}", file=sys.stderr)
            except Exception as e:
                 print(f"Error during cleanup: {e}", file=sys.stderr)

        # if 'evtest_proc' in locals() and evtest_proc.poll() is None:
        #     evtest_proc.terminate()
        #     evtest_proc.wait()
        #     print("Stopped evtest process.", file=sys.stderr)

if __name__ == "__main__":
    # Check if running as root if needed for evtest, but don't check for dotoold
    if os.geteuid() != 0:
        print("Warning: This script likely needs root privileges (sudo) to access the event device.", file=sys.stderr)
        # Optional: Exit if not root, but allow running for testing if needed.
        # sys.exit("Please run this script using sudo.")

    main() 