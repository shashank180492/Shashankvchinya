import tkinter as tk
from tkinter import filedialog, messagebox
import pandas as pd
import numpy as np
from scipy.interpolate import interp1d # type: ignore
import matplotlib.pyplot as plt
from io import BytesIO

# 📝 Make sure to include this import for ExcelWriter!
from pandas import ExcelWriter

def browse_file():
    file_path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx")])
    file_entry.delete(0, tk.END)
    file_entry.insert(0, file_path)

def calculate():
    try:
        file_path = file_entry.get()
        a = float(entry_a.get())
        b = float(entry_b.get())
        c = float(entry_c.get())
        vehicle_wt = float(entry_vehicle_wt.get())
        rider_wt = float(entry_rider_wt.get())
        battery_capacity = float(entry_battery.get())
        raster = float(entry_raster.get())

        # Load data
        data = pd.read_excel(file_path, sheet_name='Sheet1')
        eff_table = pd.read_excel(file_path, sheet_name='Sheet3')

        # Efficiency curve
        speed_curve = eff_table.iloc[1:, 0].dropna().values.astype(float)
        efficiency_curve = eff_table.iloc[1:, 1].dropna().values.astype(float)
        efficiency_interp = interp1d(speed_curve, efficiency_curve, kind='linear', fill_value="extrapolate")

        df = data.copy()
        df['Speed_dyno_m/s'] = df['Speed_dyno'] / 3.6
        df['dv/dt'] = np.gradient(df['Speed_dyno_m/s'], df['timestamps'])
        df['dv/dt'] = df['dv/dt'].shift(1).fillna(0)

        m = vehicle_wt + rider_wt
        df['F'] = a + b * df['Speed_dyno'] + c * (df['Speed_dyno'] ** 2) + m * df['dv/dt']
        df['P'] = df['F'] * df['Speed_dyno_m/s']
        df['Efficiency'] = df['Speed_dyno'].apply(lambda v: efficiency_interp(v))

        def calculate_p_corrected(row):
            if row['timestamps'] < 700:
                return abs(row['P']) / row['Efficiency']
            else:
                if row['P'] < 0:
                    return row['P'] * row['Efficiency']
                elif row['P'] == 0:
                    return 32
                else:
                    return row['P'] / row['Efficiency']

        df['P_corrected'] = df.apply(calculate_p_corrected, axis=1)

        integral_P_corrected = np.trapz(df['P_corrected'], df['timestamps'])
        Wh = integral_P_corrected / 3600
        distance = np.trapz(df['Speed_dyno_m/s'], df['timestamps'])
        WhperKm = Wh / (distance / 1000)
        range_km = battery_capacity / WhperKm

        # Create Speed vs Force plot
        speeds = np.linspace(df['Speed_dyno'].min(), df['Speed_dyno'].max(), 100)
        forces = a + b * speeds + c * (speeds ** 2)

        plt.figure(figsize=(8, 5))
        plt.plot(speeds, forces, color='blue', linewidth=2)
        plt.xlabel("Speed (km/h)")
        plt.ylabel("Force (N)")
        plt.title("Speed vs Force Curve")
        plt.grid(True)

        imgdata = BytesIO()
        plt.savefig(imgdata, format='png')
        plt.close()
        imgdata.seek(0)

        output_file_path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel files", "*.xlsx")])
        if output_file_path:
            with ExcelWriter(output_file_path, engine='xlsxwriter') as writer:
                df.to_excel(writer, sheet_name='Processed Data', index=False)

                summary_data = pd.DataFrame({
                    'Metric': ['Total Energy Consumption (Wh)',
                               'Total Distance (m)',
                               'Energy Consumption (Wh/km)',
                               'Estimated Range (km)'],
                    'Value': [Wh, distance, WhperKm, range_km]
                })
                summary_data.to_excel(writer, sheet_name='Summary', index=False, startrow=0)

                workbook = writer.book
                worksheet = writer.sheets['Summary']
                worksheet.insert_image('D6', 'speed_force_plot.png', {'image_data': imgdata})

            messagebox.showinfo("Success", f"Calculation complete.\n\nEstimated Range: {range_km:.2f} km\nEnergy Consumption: {WhperKm:.2f} Wh/km\n\nFile saved: {output_file_path}")
        else:
            messagebox.showinfo("Cancelled", "Save cancelled, but calculation complete.")

    except Exception as e:
        messagebox.showerror("Error", str(e))

root = tk.Tk()
root.title("Energy Consumption Calculator")

tk.Label(root, text="Select Excel File:").grid(row=0, column=0, sticky="w")
file_entry = tk.Entry(root, width=50)
file_entry.grid(row=0, column=1)
tk.Button(root, text="Browse", command=browse_file).grid(row=0, column=2)

tk.Label(root, text="a:").grid(row=1, column=0, sticky="w")
entry_a = tk.Entry(root)
entry_a.insert(0, "36.078")
entry_a.grid(row=1, column=1)

tk.Label(root, text="b:").grid(row=2, column=0, sticky="w")
entry_b = tk.Entry(root)
entry_b.insert(0, "0.1727")
entry_b.grid(row=2, column=1)

tk.Label(root, text="c:").grid(row=3, column=0, sticky="w")
entry_c = tk.Entry(root)
entry_c.insert(0, "-0.0028")
entry_c.grid(row=3, column=1)

tk.Label(root, text="Vehicle Weight (kg):").grid(row=4, column=0, sticky="w")
entry_vehicle_wt = tk.Entry(root)
entry_vehicle_wt.insert(0, "138")
entry_vehicle_wt.grid(row=4, column=1)

tk.Label(root, text="Rider Weight (kg):").grid(row=5, column=0, sticky="w")
entry_rider_wt = tk.Entry(root)
entry_rider_wt.insert(0, "75")
entry_rider_wt.grid(row=5, column=1)

tk.Label(root, text="Battery Capacity (Wh):").grid(row=6, column=0, sticky="w")
entry_battery = tk.Entry(root)
entry_battery.insert(0, "3965")
entry_battery.grid(row=6, column=1)

tk.Label(root, text="Raster (s):").grid(row=7, column=0, sticky="w")
entry_raster = tk.Entry(root)
entry_raster.insert(0, "1")
entry_raster.grid(row=7, column=1)

tk.Button(root, text="Calculate & Save", command=calculate, bg="green", fg="white").grid(row=8, column=1, pady=10)

root.mainloop()
