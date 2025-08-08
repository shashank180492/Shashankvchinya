import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from scipy.interpolate import griddata

class SurfacePlotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("3D Surface Plot Viewer")
        self.df = None
        self.animating = False

        self.time_window = tk.DoubleVar(value=1.0)
        self.cmap_choice = tk.StringVar(value='viridis')

        self.x_col = tk.StringVar()
        self.y_col = tk.StringVar()
        self.z_col = tk.StringVar()
        self.time_col = tk.StringVar()

        self.create_widgets()

    def create_widgets(self):
        top_frame = tk.Frame(self.root)
        top_frame.pack(pady=10)

        tk.Button(top_frame, text="📁 Load CSV", command=self.load_csv).grid(row=0, column=0, padx=5)

        ttk.Label(top_frame, text="Time Window (s):").grid(row=0, column=1)
        self.time_entry = tk.Entry(top_frame, textvariable=self.time_window, width=6)
        self.time_entry.grid(row=0, column=2)

        ttk.Label(top_frame, text="Colormap:").grid(row=0, column=3)
        ttk.Combobox(top_frame, textvariable=self.cmap_choice,
                     values=['viridis', 'plasma', 'inferno', 'magma', 'cividis'],
                     width=10).grid(row=0, column=4)

        # Column selectors
        col_sel_frame = tk.Frame(self.root)
        col_sel_frame.pack(pady=5)

        ttk.Label(col_sel_frame, text="Time:").grid(row=0, column=0, padx=3)
        self.time_dropdown = ttk.Combobox(col_sel_frame, textvariable=self.time_col, width=10)
        self.time_dropdown.grid(row=0, column=1, padx=3)

        ttk.Label(col_sel_frame, text="X:").grid(row=0, column=2, padx=3)
        self.x_dropdown = ttk.Combobox(col_sel_frame, textvariable=self.x_col, width=10)
        self.x_dropdown.grid(row=0, column=3, padx=3)

        ttk.Label(col_sel_frame, text="Y:").grid(row=0, column=4, padx=3)
        self.y_dropdown = ttk.Combobox(col_sel_frame, textvariable=self.y_col, width=10)
        self.y_dropdown.grid(row=0, column=5, padx=3)

        ttk.Label(col_sel_frame, text="Z:").grid(row=0, column=6, padx=3)
        self.z_dropdown = ttk.Combobox(col_sel_frame, textvariable=self.z_col, width=10)
        self.z_dropdown.grid(row=0, column=7, padx=3)

        tk.Button(col_sel_frame, text="✅ Apply Columns", command=self.on_column_selection).grid(row=0, column=8, padx=10)

        # Plot area
        plot_frame = tk.Frame(self.root)
        plot_frame.pack()

        self.fig = plt.figure(figsize=(10, 8))
        self.ax = self.fig.add_subplot(111, projection='3d')
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack()

        # Slider
        self.slider = tk.Scale(self.root, from_=0, to=1, resolution=0.1,
                               orient=tk.HORIZONTAL, label="Time", length=600,
                               command=self.update_plot)
        self.slider.pack(pady=10)

        # Controls
        ctrl_frame = tk.Frame(self.root)
        ctrl_frame.pack(pady=10)

        tk.Button(ctrl_frame, text="▶ Play", command=self.start_animation).pack(side=tk.LEFT, padx=10)
        tk.Button(ctrl_frame, text="⏹ Stop", command=self.stop_animation).pack(side=tk.LEFT, padx=10)
        tk.Button(ctrl_frame, text="💾 Export Plot", command=self.export_plot).pack(side=tk.LEFT, padx=10)

    def load_csv(self):
        file_path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if not file_path:
            return

        try:
            self.df = pd.read_csv(file_path)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read CSV: {e}")
            return

        # Update dropdowns
        col_names = list(self.df.columns)
        for dropdown in [self.x_dropdown, self.y_dropdown, self.z_dropdown, self.time_dropdown]:
            dropdown['values'] = col_names

        if 'Time' in col_names:
            self.time_col.set('Time')
        if 'X' in col_names:
            self.x_col.set('X')
        if 'Y' in col_names:
            self.y_col.set('Y')
        if 'Z' in col_names:
            self.z_col.set('Z')

    def on_column_selection(self):
        if self.df is None:
            return
        try:
            time_vals = self.df[self.time_col.get()].dropna()
            self.min_time = float(time_vals.min())
            self.max_time = float(time_vals.max())
        except Exception as e:
            messagebox.showerror("Invalid Column", f"Time column could not be read: {e}")
            return

        self.slider.configure(from_=self.min_time, to=self.max_time - self.time_window.get(), resolution=0.1)
        self.slider.set(self.min_time)
        self.update_plot(self.min_time)

    def update_plot(self, time_val):
        if self.df is None:
            return
        try:
            time_val = float(time_val)
            window = float(self.time_window.get())
            df_window = self.df[
                (self.df[self.time_col.get()] >= time_val) &
                (self.df[self.time_col.get()] <= time_val + window)
            ]
            df_window = df_window.dropna(subset=[self.x_col.get(), self.y_col.get(), self.z_col.get()])
        except Exception as e:
            self.ax.clear()
            self.ax.set_title(f"Column error: {e}")
            self.canvas.draw()
            return

        self.ax.clear()

        if len(df_window) < 3:
            self.ax.set_title("Too few data points")
            self.canvas.draw()
            return

        X = df_window[self.x_col.get()].values
        Y = df_window[self.y_col.get()].values
        Z = df_window[self.z_col.get()].values

        if len(np.unique(X)) < 2 or len(np.unique(Y)) < 2:
            self.ax.set_title("Insufficient variation in X or Y")
            self.ax.scatter(X, Y, Z, c=Z, cmap=self.cmap_choice.get())
        elif len(np.unique(Z)) < 2:
            self.ax.set_title("Z is constant")
            self.ax.scatter(X, Y, Z, c='blue')
        else:
            try:
                xi = np.linspace(X.min(), X.max(), 100)
                yi = np.linspace(Y.min(), Y.max(), 100)
                xi, yi = np.meshgrid(xi, yi)
                zi = griddata((X, Y), Z, (xi, yi), method='linear')

                if zi is None or np.all(np.isnan(zi)):
                    raise ValueError("Interpolation failed")

                self.ax.plot_surface(xi, yi, zi, cmap=self.cmap_choice.get(), edgecolor='none')
            except Exception as e:
                self.ax.set_title(f"Interpolation fallback: {e}")
                self.ax.scatter(X, Y, Z, c=Z, cmap=self.cmap_choice.get())

        self.ax.set_title(f"{time_val:.2f} – {time_val + window:.2f} sec")
        self.ax.set_xlabel(self.x_col.get())
        self.ax.set_ylabel(self.y_col.get())
        self.ax.set_zlabel(self.z_col.get())
        self.canvas.draw()

    def start_animation(self):
        self.animating = True
        self.animate_plot()

    def stop_animation(self):
        self.animating = False

    def animate_plot(self):
        if not self.animating:
            return
        current = self.slider.get()
        step = self.slider['resolution']
        new_time = current + step
        if new_time > float(self.slider['to']):
            new_time = float(self.slider['from'])  # loop
        self.slider.set(new_time)
        self.root.after(300, self.animate_plot)

    def export_plot(self):
        filename = filedialog.asksaveasfilename(defaultextension=".png",
                                                filetypes=[("PNG Image", "*.png")])
        if filename:
            self.fig.savefig(filename)


if __name__ == "__main__":
    root = tk.Tk()
    app = SurfacePlotApp(root)
    root.mainloop()