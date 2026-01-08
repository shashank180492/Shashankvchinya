import time
import json
import threading
import pandas as pd
import can
import cantools
import os
from itertools import cycle
from datetime import datetime

# =========================================================
# 1. SETUP & CONFIGURATION
# =========================================================
CONFIG_PATH = r"D:\HIL simulation\code\config4.json"

print("[INIT] Loading Config...")
with open(CONFIG_PATH, "r") as f:
    CFG = json.load(f)

# Hardware Setup
BMS_CH = CFG["hardware"]["bms_channel"] # Expecting Real BMS here (USBBUS1)
VCU_CH = CFG["hardware"]["vcu_channel"] # Expecting VCU here (USBBUS2)
BITRATE = CFG["hardware"]["bitrate"]

# Paths
INPUT_EXCEL = CFG["file_paths"]["input_excel"]
DBC_PATH = CFG["file_paths"]["dbc"]
OUTPUT_DIR = os.path.join(CFG["file_paths"]["output_directory"], datetime.now().strftime("%Y%m%d_%H%M%S"))

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# Logic Setup
INJECT_MSG = CFG["gateway"]["injection_message"] # BatteryParameters
INJECT_SIG = CFG["gateway"]["injection_signal"]  # Battery_Current
REPLAY_LIST = CFG["replay"]["messages_to_simulate"]
TARGET_RESPONSES = set(CFG["replay"]["target_response_list"])

# =========================================================
# 2. INITIALIZATION
# =========================================================
print(f"[INIT] Parsing DBC: {os.path.basename(DBC_PATH)}")
dbc = cantools.database.load_file(DBC_PATH, strict=False)

# Identify Message IDs for verification
try:
    bms_frame_id = dbc.get_message_by_name(INJECT_MSG).frame_id
except:
    bms_frame_id = None
    print("[WARN] Could not find injection message ID in DBC for verification.")

print("[INIT] Opening CAN Channels...")
try:
    bus_bms = can.Bus(interface='pcan', channel=BMS_CH, bitrate=BITRATE)
    bus_vcu = can.Bus(interface='pcan', channel=VCU_CH, bitrate=BITRATE)
except Exception as e:
    print(f"[FATAL] Connection Failed: {e}")
    exit(1)

# Shared State
stop_event = threading.Event()
GLOBAL_CURRENT_VAL = 0.0
captured_logs = {name: [] for name in TARGET_RESPONSES}
start_time_ref = 0 

# =========================================================
# 3. WIRING VERIFICATION
# =========================================================
def verify_wiring():
    """Listens to both channels to ensure BMS and VCU are where we expect them."""
    print("\n[CHECK] Verifying Physical Connections (2.0s)...")
    
    bms_side_traffic = 0
    vcu_side_traffic = 0
    bms_msg_found_on_ch1 = False
    bms_msg_found_on_ch2 = False
    
    t_end = time.time() + 2.0
    
    while time.time() < t_end:
        # Check Channel 1 (Should be BMS)
        msg1 = bus_bms.recv(timeout=0.01)
        if msg1:
            bms_side_traffic += 1
            if msg1.arbitration_id == bms_frame_id:
                bms_msg_found_on_ch1 = True
                
        # Check Channel 2 (Should be VCU)
        msg2 = bus_vcu.recv(timeout=0.01)
        if msg2:
            vcu_side_traffic += 1
            if msg2.arbitration_id == bms_frame_id:
                bms_msg_found_on_ch2 = True

    # --- ANALYSIS ---
    print(f"   -> {BMS_CH} seen {bms_side_traffic} frames.")
    print(f"   -> {VCU_CH} seen {vcu_side_traffic} frames.")

    if bms_msg_found_on_ch2:
        print("\n❌ [CRITICAL ERROR] WIRING SWAPPED!")
        print(f"   The BMS Message ({INJECT_MSG}) was detected on the VCU Channel ({VCU_CH}).")
        print("   ACTION: Swap the USB cables or flip the channel names in config.json.")
        return False
        
    if bms_side_traffic == 0:
        print("\n⚠️ [WARNING] No data from Real BMS on Channel 1.")
        print("   Is the BMS powered on? Is the termination resistor installed?")
        
    if bms_msg_found_on_ch1:
        print("\n✅ [PASS] BMS detected correctly on Channel 1.")
        return True
        
    print("\n[INFO] Wiring check inconclusive (BMS silent), proceeding with caution...")
    return True

# =========================================================
# 4. GATEWAY & INJECTION (With SPY Logic)
# =========================================================
def bridge_bms_to_vcu():
    """Reads BMS, Spies on Answer, Overwrites Current, Sends to VCU."""
    inject_def = dbc.get_message_by_name(INJECT_MSG)
    
    while not stop_event.is_set():
        try:
            msg = bus_bms.recv(timeout=0.1)
            if not msg: continue

            # --- SPY LOGIC (ANSWER) ---
            try:
                msg_def = dbc.get_message_by_frame_id(msg.arbitration_id)
                # Detect BMS Auth Response (Modify 'InternalBattAuthOK' to match your DBC)
                if "Auth" in msg_def.name and ("Batt" in msg_def.name or "BMS" in msg_def.name):
                    decoded = dbc.decode_message(msg.arbitration_id, msg.data)
                    print(f"[❗ ANSWER] BMS sent Response:   {decoded}")
            except: pass
            # --------------------------

            # INTERCEPT: Is this the Battery Param message?
            if msg.arbitration_id == inject_def.frame_id:
                try:
                    decoded = dbc.decode_message(msg.arbitration_id, msg.data)
                    # INJECTION: Replace real 0A with Excel value
                    decoded[INJECT_SIG] = GLOBAL_CURRENT_VAL
                    
                    # Re-encode and Send
                    msg.data = inject_def.encode(decoded)
                    bus_vcu.send(msg)
                except:
                    bus_vcu.send(msg) # Forward original if decode fails
            else:
                bus_vcu.send(msg) # Forward everything else blindly
        except can.CanError:
            pass 

def bridge_vcu_to_bms():
    """Reads VCU, Spies on Question, Forwards to BMS."""
    last_auth_state = -1
    
    while not stop_event.is_set():
        try:
            msg = bus_vcu.recv(timeout=0.1)
            if not msg: continue
            
            # --- SPY LOGIC (QUESTION) ---
            try:
                msg_def = dbc.get_message_by_frame_id(msg.arbitration_id)
                # Detect VCU Auth Challenge (Modify 'VcuAuth' to match your DBC)
                if "Auth" in msg_def.name and "VCU" in msg_def.name: 
                    decoded = dbc.decode_message(msg.arbitration_id, msg.data)
                    print(f"\n[❓ QUESTION] VCU sent Challenge: {decoded}")
            except: pass
            # -----------------------------

            # 1. Forward to BMS (Return path)
            bus_bms.send(msg)

            # 2. Monitor Auth Status & Logging
            try:
                msg_def = dbc.get_message_by_frame_id(msg.arbitration_id)
                
                # Check for Auth Success
                if "VCU_Status" in msg_def.name:
                    decoded = dbc.decode_message(msg.arbitration_id, msg.data)
                    status = decoded.get("STA_Authentication_status", -1)
                    if status != last_auth_state:
                        if status == 1: print(f"\n✅ [AUTH] VCU Authenticated! (State: {status})")
                        else: print(f"\n⚠️ [AUTH] VCU Not Authenticated (State: {status})")
                        last_auth_state = status

                # Log Targets
                if msg_def.name in TARGET_RESPONSES:
                    decoded = dbc.decode_message(msg.arbitration_id, msg.data)
                    decoded['Time'] = time.perf_counter()
                    captured_logs[msg_def.name].append(decoded)
            except: pass
        except can.CanError:
            pass

# =========================================================
# 5. DATA FEEDERS (Excel Replay)
# =========================================================
def injection_updater():
    """Updates the Current Injection Value from Excel"""
    global GLOBAL_CURRENT_VAL
    try:
        df = pd.read_excel(INPUT_EXCEL, sheet_name=INJECT_MSG)
        times = df['Time'].values - df['Time'].values[0]
        values = df[INJECT_SIG].values
        playlist = list(zip(times, values))
    except Exception as e:
        print(f"[ERR] Failed to load Injection Data: {e}")
        return

    while start_time_ref == 0: time.sleep(0.01) # Wait for start

    for t_target, val in cycle(playlist):
        if stop_event.is_set(): break
        while (time.perf_counter() - start_time_ref) < t_target:
            time.sleep(0.001)
        GLOBAL_CURRENT_VAL = val

def replay_publisher(message_name):
    """Simulates Motor/Charger messages"""
    try:
        df = pd.read_excel(INPUT_EXCEL, sheet_name=message_name)
        msg_def = dbc.get_message_by_name(message_name)
        times = df['Time'].values - df['Time'].values[0]
        sigs = [s.name for s in msg_def.signals if s.name in df.columns]
        rows = df[sigs].to_dict("records")
        sequence = list(zip(times, rows))
    except: return

    while start_time_ref == 0: time.sleep(0.01)

    for t_target, row in cycle(sequence):
        if stop_event.is_set(): break
        
        target = start_time_ref + t_target
        rem = target - time.perf_counter()
        if rem > 0.002: time.sleep(rem - 0.001)
        while time.perf_counter() < target: pass

        try:
            payload = {k: v for k, v in row.items() if pd.notna(v)}
            bus_vcu.send(can.Message(arbitration_id=msg_def.frame_id, data=msg_def.encode(payload), is_extended_id=msg_def.is_extended_frame))
        except: continue

# =========================================================
# 6. MAIN
# =========================================================
def main():
    global start_time_ref
    
    # 1. Verify Wiring First
    if not verify_wiring():
        print("\n[STOP] Aborting due to wiring error.")
        bus_bms.shutdown()
        bus_vcu.shutdown()
        return

    print("\n--- STARTING HIL ENGINE ---")
    
    # 2. Start Bridges (Immediate Auth)
    t_fwd = threading.Thread(target=bridge_bms_to_vcu, daemon=True)
    t_rev = threading.Thread(target=bridge_vcu_to_bms, daemon=True)
    t_fwd.start()
    t_rev.start()
    
    print("[SYSTEM] Bridge Active. Watching for Handshake...")
    time.sleep(3.0) 

    # 3. Start Simulation
    threads = []
    t_inj = threading.Thread(target=injection_updater, daemon=True)
    threads.append(t_inj)
    
    for msg in REPLAY_LIST:
        t = threading.Thread(target=replay_publisher, args=(msg,), daemon=True)
        threads.append(t)
    
    print(f"[SYSTEM] Starting {len(threads)} Simulators...")
    start_time_ref = time.perf_counter() # SYNC START
    for t in threads: t.start()

    print("[RUNNING] Press Ctrl+C to stop.")
    
    try:
        while True:
            # Overwrite line with status update
            print(f"\r[STATUS] Injecting Current: {GLOBAL_CURRENT_VAL:.1f} A   ", end="")
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n[STOPPING] Saving logs...")
        stop_event.set()
        
        for msg_name, logs in captured_logs.items():
            if logs:
                df = pd.DataFrame(logs)
                cols = ['Time'] + [c for c in df.columns if c != 'Time']
                df[cols].to_csv(os.path.join(OUTPUT_DIR, f"HIL_Output_{msg_name}.csv"), index=False)
                print(f"Saved {msg_name}")

        bus_bms.shutdown()
        bus_vcu.shutdown()
        print("[DONE]")

if __name__ == "__main__":
    main()