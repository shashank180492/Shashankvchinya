import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np
import difflib

df = pd.DataFrame()
speed_col, accel_col = None, None

# -------------------------------------------
def get_best_match(target, available_columns):
    match = difflib.get_close_matches(target.lower(), available_columns, n=1, cutoff=0.6)
    return match[0] if match else None

def load_csv():
    global df, speed_col, accel_col
    file_path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
    if not file_path:
        return
    try:
        df_raw = pd.read_csv(file_path, encoding="utf-8", engine="python")
        df_raw.columns = [col.strip() for col in df_raw.columns]
        columns_lower = [col.lower() for col in df_raw.columns]

        speed_col_match = get_best_match("Speed (km/h)", columns_lower)
        accel_col_match = get_best_match("Longitudinal acceleration (g)", columns_lower)

        if not speed_col_match or not accel_col_match:
            messagebox.showerror("Missing Columns", f"Required columns not found.\nAvailable: {df_raw.columns.tolist()}")
            return

        speed_col = df_raw.columns[columns_lower.index(speed_col_match)]
        accel_col = df_raw.columns[columns_lower.index(accel_col_match)]
        df = df_raw.copy()

        messagebox.showinfo("Success", f"Loaded {len(df)} rows.\nMatched columns:\n- Speed: {speed_col}\n- Accel: {accel_col}")
        update_table()
        update_dropdowns()
    except Exception as e:
        messagebox.showerror("Read Error", str(e))

def update_table():
    if df.empty:
        return
    for widget in table_frame.winfo_children():
        widget.destroy()
    tree = ttk.Treeview(table_frame)
    tree.pack(fill="both", expand=True)
    tree["columns"] = list(df.columns)
    tree["show"] = "headings"
    for col in df.columns:
        tree.heading(col, text=col)
        tree.column(col, width=100)
    for _, row in df.head(100).iterrows():
        tree.insert("", "end", values=list(row))

def update_dropdowns():
    if df.empty:
        return
    cols = df.columns.tolist()
    x_dropdown['values'] = cols
    y_dropdown['values'] = cols

def smooth_and_calculate():
    global df
    if df.empty:
        messagebox.showwarning("No Data", "Please load a CSV file first.")
        return
    try:
        window = int(window_entry.get())
        vehicle_wt = float(vehicle_weight_entry.get())
        rider_wt = float(rider_weight_entry.get())
        total_mass = vehicle_wt + rider_wt

        df["Smoothed Acceleration (g)"] = df[accel_col].rolling(window=window, min_periods=1, center=True).mean()
        df["Force (N)"] = total_mass * 9.81 * df["Smoothed Acceleration (g)"]

        update_table()
        update_dropdowns()
        messagebox.showinfo("Done", "Smoothing and force calculation completed.")
    except Exception as e:
        messagebox.showerror("Error", str(e))

def plot_graph():
    global df
    if df.empty:
        messagebox.showwarning("No Data", "Please load a CSV file first.")
        return
    x_col = x_dropdown.get()
    y_col = y_dropdown.get()
    if not x_col or not y_col:
        messagebox.showwarning("Select Columns", "Please select both X and Y axis columns.")
        return
    try:
        plt.figure(figsize=(10, 5))
        plt.plot(df[x_col], df[y_col], label=f"{y_col} vs {x_col}")
        plt.xlabel(x_col)
        plt.ylabel(y_col)
        plt.title(f"{y_col} vs {x_col}")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        plt.show()
    except Exception as e:
        messagebox.showerror("Plot Error", str(e))

# ------------------ Span Plot -------------------------
def show_speed_plot_with_selector():
    if df.empty or "Force (N)" not in df.columns:
        messagebox.showerror("Missing Data", "Please smooth and calculate force first.")
        return

    span_window = tk.Toplevel()
    span_window.title("Speed vs Time Plot with Selectable Range")

    fig, ax = plt.subplots(figsize=(10, 4))
    canvas = FigureCanvasTkAgg(fig, master=span_window)
    canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    time = np.arange(len(df))  # x-axis as index
    speed = df[speed_col].values
    ax.plot(time, speed, label="Speed (km/h)")
    ax.set_xlabel("Time index")
    ax.set_ylabel("Speed (km/h)")
    ax.set_title("Speed vs Time")
    ax.grid(True)

    line1 = ax.axvline(x=100, color='red', label="Point 1", linestyle='--')
    line2 = ax.axvline(x=200, color='blue', label="Point 2", linestyle='--')
    speed_text = ax.text(0.01, 0.95, '', transform=ax.transAxes, fontsize=10, verticalalignment='top')

    def update_text():
        i1, i2 = int(line1.get_xdata()[0]), int(line2.get_xdata()[0])
        i1, i2 = sorted([max(0, i1), min(len(df) - 1, i2)])
        s1, s2 = speed[i1], speed[i2]
        speed_text.set_text(f"Speed 1: {s1:.2f} km/h\nSpeed 2: {s2:.2f} km/h")
        fig.canvas.draw_idle()

    def on_click(event):
        if event.inaxes != ax:
            return
        if abs(event.xdata - line1.get_xdata()[0]) < abs(event.xdata - line2.get_xdata()[0]):
            on_click.selected = 1
        else:
            on_click.selected = 2

    def on_motion(event):
        if not hasattr(on_click, "selected") or event.inaxes != ax:
            return
        if on_click.selected == 1:
            line1.set_xdata([event.xdata])
        elif on_click.selected == 2:
            line2.set_xdata([event.xdata])
        update_text()

    def on_release(event):
        on_click.selected = None

    fig.canvas.mpl_connect("button_press_event", on_click)
    fig.canvas.mpl_connect("motion_notify_event", on_motion)
    fig.canvas.mpl_connect("button_release_event", on_release)

    update_text()

    result_label = tk.Label(span_window, text="", font=("Arial", 12), justify="left")
    result_label.pack()

    copy_btn = tk.Button(span_window, text="Copy to Clipboard")
    copy_btn.pack(pady=5)
    copy_btn.config(state="disabled")  # Initially disabled

    def fit_force_curve():
        i1, i2 = int(line1.get_xdata()[0]), int(line2.get_xdata()[0])
        i1, i2 = sorted([max(0, i1), min(len(df) - 1, i2)])
        v = df[speed_col].iloc[i1:i2+1].values
        f = df["Force (N)"].iloc[i1:i2+1].values

        v_squared = v**2
        coeffs = np.polyfit(v_squared, f, 1)
        C, A = coeffs[0], coeffs[1]

        result = f"A = {A:.2f} N\nC = {C:.4f} N/(km/h)^2"
        result_label.config(text=result)

        def copy_to_clipboard():
            span_window.clipboard_clear()
            span_window.clipboard_append(result)
            span_window.update()

        copy_btn.config(command=copy_to_clipboard, state="normal")

    tk.Button(span_window, text="Fit Force Curve", command=fit_force_curve).pack(pady=5)

    canvas.draw()

# ---------------- GUI Layout --------------------------
root = tk.Tk()
root.title("Coastdown Force Calculator")

frame = tk.Frame(root)
frame.pack(padx=10, pady=10)

tk.Button(frame, text="Load CSV", command=load_csv).grid(row=0, column=0, padx=5)

tk.Label(frame, text="Moving Avg Window:").grid(row=0, column=1)
window_entry = tk.Entry(frame, width=5)
window_entry.insert(0, "5")
window_entry.grid(row=0, column=2, padx=5)

tk.Label(frame, text="Vehicle Weight (kg):").grid(row=1, column=0)
vehicle_weight_entry = tk.Entry(frame, width=10)
vehicle_weight_entry.insert(0, "100")
vehicle_weight_entry.grid(row=1, column=1)

tk.Label(frame, text="Rider Weight (kg):").grid(row=1, column=2)
rider_weight_entry = tk.Entry(frame, width=10)
rider_weight_entry.insert(0, "70")
rider_weight_entry.grid(row=1, column=3)

tk.Label(frame, text="X-Axis:").grid(row=2, column=0)
x_dropdown = ttk.Combobox(frame, state="readonly")
x_dropdown.grid(row=2, column=1)

tk.Label(frame, text="Y-Axis:").grid(row=2, column=2)
y_dropdown = ttk.Combobox(frame, state="readonly")
y_dropdown.grid(row=2, column=3)

tk.Button(frame, text="Smooth & Calculate", command=smooth_and_calculate).grid(row=3, column=0, columnspan=2, pady=10)
tk.Button(frame, text="Plot Graph", command=plot_graph).grid(row=3, column=2, columnspan=2)
tk.Button(frame, text="Speed-Time Selector", command=show_speed_plot_with_selector).grid(row=4, column=0, columnspan=4, pady=10)

table_frame = tk.Frame(root)
table_frame.pack(fill="both", expand=True)

root.mainloop()
