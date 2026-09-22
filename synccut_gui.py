"""
synccut_gui.py — Extended Tkinter GUI for SyncCut.
Phase 6: Visual waveform overlay canvas, confidence badges (green/yellow/red),
'Review required' panel, interactive offset nudge controls, drift display (ms/hr),
and direct export for CSV, PDF, and FCPXML corrected timelines.
"""
import csv
import json
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np

from confidence import badge_and_status_from_confidence
from extract import extract_audio
from sync_engine import load_wav, solve_multi_source_sync
from drift import windowed_offsets, analyze_drift
from timeline_builder import build_timeline, export_timeline


class WaveformCanvas(tk.Canvas):
    """Custom canvas for rendering audio waveform preview overlays."""

    def __init__(self, master, width=600, height=80, **kwargs):
        super().__init__(master, width=width, height=height, bg="#1e1e1e", highlightthickness=0, **kwargs)
        self.width = width
        self.height = height

    def plot_waveform(self, signal, offset_sec=0.0, color="#00ffcc"):
        self.delete("all")
        if signal is None or len(signal) == 0:
            self.create_text(self.width / 2, self.height / 2, text="No Audio Signal", fill="#666666")
            return

        # Downsample signal to fit canvas width
        n_samples = len(signal)
        samples_per_pixel = max(1, n_samples // self.width)
        downsampled = signal[::samples_per_pixel][: self.width]

        mid_y = self.height / 2.0
        max_amp = np.max(np.abs(downsampled)) + 1e-6

        # Draw offset zero line marker
        offset_x = int(np.clip(offset_sec * 10, 0, self.width))
        self.create_line(offset_x, 0, offset_x, self.height, fill="#ffaa00", dash=(2, 2))

        points = []
        for x, sample in enumerate(downsampled):
            y = mid_y - (sample / max_amp) * (mid_y - 5)
            points.append((x, y))

        for i in range(len(points) - 1):
            self.create_line(points[i][0], points[i][1], points[i+1][0], points[i+1][1], fill=color)


class SyncCutTkinterApp(tk.Tk):
    """Main Tkinter desktop UI for SyncCut."""

    def __init__(self):
        super().__init__()
        self.title("SyncCut — Multi-Camera Audio Sync & Confidence Suite")
        self.geometry("1100x750")
        self.configure(bg="#121212")

        self.reference_path = None
        self.input_paths = []
        self.sync_results = []
        self.audio_signals = {}
        self.sample_rates = {}

        self._build_ui()

    def _build_ui(self):
        # Top Header Bar
        header_frame = tk.Frame(self, bg="#1f1f1f", height=50)
        header_frame.pack(fill=tk.X, side=tk.TOP)
        lbl_title = tk.Label(
            header_frame,
            text="SyncCut Professional Multi-Camera Alignment",
            font=("Helvetica", 14, "bold"),
            fg="#ffffff",
            bg="#1f1f1f",
        )
        lbl_title.pack(side=tk.LEFT, padx=15, pady=10)

        # Main Layout (Split Pane: Left File List / Control, Right Waveform & Report)
        paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg="#121212", bd=0)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Left Panel (Controls & Files)
        left_frame = tk.Frame(paned, bg="#1a1a1a", width=380)
        paned.add(left_frame)

        # Controls
        lbl_ref = tk.Label(left_frame, text="1. Select Reference Audio/Video:", fg="#aaaaaa", bg="#1a1a1a", anchor="w")
        lbl_ref.pack(fill=tk.X, padx=10, pady=(10, 2))

        ref_btn_frame = tk.Frame(left_frame, bg="#1a1a1a")
        ref_btn_frame.pack(fill=tk.X, padx=10)
        btn_ref = tk.Button(ref_btn_frame, text="Browse Reference", command=self.select_reference, bg="#333333", fg="white")
        btn_ref.pack(side=tk.LEFT)
        self.lbl_ref_name = tk.Label(ref_btn_frame, text="No file selected", fg="#888888", bg="#1a1a1a", anchor="w")
        self.lbl_ref_name.pack(side=tk.LEFT, padx=10)

        lbl_inputs = tk.Label(left_frame, text="2. Select Camera Sources:", fg="#aaaaaa", bg="#1a1a1a", anchor="w")
        lbl_inputs.pack(fill=tk.X, padx=10, pady=(15, 2))

        btn_inputs = tk.Button(left_frame, text="Add Camera Files", command=self.add_inputs, bg="#333333", fg="white")
        btn_inputs.pack(anchor="w", padx=10)

        self.input_listbox = tk.Listbox(left_frame, bg="#242424", fg="#ffffff", selectbackground="#007acc", height=6)
        self.input_listbox.pack(fill=tk.X, padx=10, pady=5)

        # Mode Selection
        mode_frame = tk.Frame(left_frame, bg="#1a1a1a")
        mode_frame.pack(fill=tk.X, padx=10, pady=10)
        tk.Label(mode_frame, text="Sync Mode:", fg="#cccccc", bg="#1a1a1a").pack(side=tk.LEFT)
        self.sync_mode_var = tk.StringVar(value="global")
        rb_global = tk.Radiobutton(mode_frame, text="Global Solver", variable=self.sync_mode_var, value="global", bg="#1a1a1a", fg="white", selectcolor="#222222")
        rb_ref = tk.Radiobutton(mode_frame, text="Reference Only", variable=self.sync_mode_var, value="reference", bg="#1a1a1a", fg="white", selectcolor="#222222")
        rb_global.pack(side=tk.LEFT, padx=5)
        rb_ref.pack(side=tk.LEFT)

        # Run Button
        btn_run = tk.Button(
            left_frame,
            text="RUN SYNC & DRIFT ANALYSIS",
            command=self.run_sync_analysis,
            bg="#007acc",
            fg="white",
            font=("Helvetica", 10, "bold"),
            pady=6,
        )
        btn_run.pack(fill=tk.X, padx=10, pady=15)

        # Review Required Warning Box
        self.review_box = tk.LabelFrame(left_frame, text="Review Required Sources", fg="#ff4444", bg="#1a1a1a")
        self.review_box.pack(fill=tk.X, padx=10, pady=5)
        self.lbl_review_items = tk.Label(self.review_box, text="None", fg="#888888", bg="#1a1a1a", justify=tk.LEFT)
        self.lbl_review_items.pack(padx=5, pady=5, anchor="w")

        # Exports
        export_frame = tk.LabelFrame(left_frame, text="Export Options", fg="#cccccc", bg="#1a1a1a")
        export_frame.pack(fill=tk.X, padx=10, pady=10)

        btn_exp_fcpxml = tk.Button(export_frame, text="Export FCPXML Timeline", command=self.export_fcpxml, bg="#333333", fg="white")
        btn_exp_fcpxml.pack(fill=tk.X, padx=5, pady=3)
        btn_exp_csv = tk.Button(export_frame, text="Export CSV Report", command=self.export_csv, bg="#333333", fg="white")
        btn_exp_csv.pack(fill=tk.X, padx=5, pady=3)
        btn_exp_pdf = tk.Button(export_frame, text="Export PDF Report", command=self.export_pdf, bg="#333333", fg="white")
        btn_exp_pdf.pack(fill=tk.X, padx=5, pady=3)

        # Right Panel (Results Table, Nudge Controls, Waveforms)
        right_frame = tk.Frame(paned, bg="#1a1a1a")
        paned.add(right_frame)

        # Treeview Results Table
        columns = ("source", "offset", "drift", "conf", "badge", "status")
        self.tree = ttk.Treeview(right_frame, columns=columns, show="headings", height=7)
        self.tree.heading("source", text="Source")
        self.tree.heading("offset", text="Offset (s)")
        self.tree.heading("drift", text="Drift (ms/hr)")
        self.tree.heading("conf", text="Calibrated Conf")
        self.tree.heading("badge", text="Badge")
        self.tree.heading("status", text="Status")

        self.tree.column("source", width=120)
        self.tree.column("offset", width=90)
        self.tree.column("drift", width=100)
        self.tree.column("conf", width=110)
        self.tree.column("badge", width=70)
        self.tree.column("status", width=160)

        self.tree.pack(fill=tk.X, padx=10, pady=10)
        self.tree.bind("<<TreeviewSelect>>", self.on_source_select)

        # Manual Nudge Control Frame
        nudge_frame = tk.LabelFrame(right_frame, text="Manual Offset Nudge Controls", fg="#00ffcc", bg="#1a1a1a")
        nudge_frame.pack(fill=tk.X, padx=10, pady=5)

        btn_nudge_m100 = tk.Button(nudge_frame, text="-100 ms", command=lambda: self.nudge_selected(-0.100), bg="#333333", fg="white")
        btn_nudge_m100.pack(side=tk.LEFT, padx=5, pady=5)
        btn_nudge_m10 = tk.Button(nudge_frame, text="-10 ms", command=lambda: self.nudge_selected(-0.010), bg="#333333", fg="white")
        btn_nudge_m10.pack(side=tk.LEFT, padx=5)
        btn_nudge_m1f = tk.Button(nudge_frame, text="-1 Frame (40ms)", command=lambda: self.nudge_selected(-0.040), bg="#333333", fg="white")
        btn_nudge_m1f.pack(side=tk.LEFT, padx=5)

        btn_nudge_p1f = tk.Button(nudge_frame, text="+1 Frame (40ms)", command=lambda: self.nudge_selected(0.040), bg="#333333", fg="white")
        btn_nudge_p1f.pack(side=tk.LEFT, padx=5)
        btn_nudge_p10 = tk.Button(nudge_frame, text="+10 ms", command=lambda: self.nudge_selected(0.010), bg="#333333", fg="white")
        btn_nudge_p10.pack(side=tk.LEFT, padx=5)
        btn_nudge_p100 = tk.Button(nudge_frame, text="+100 ms", command=lambda: self.nudge_selected(0.100), bg="#333333", fg="white")
        btn_nudge_p100.pack(side=tk.LEFT, padx=5)

        # Waveform Overlay Display
        lbl_wave = tk.Label(right_frame, text="Waveform Overlay Preview:", fg="#aaaaaa", bg="#1a1a1a", anchor="w")
        lbl_wave.pack(fill=tk.X, padx=10, pady=(10, 2))
        self.waveform_canvas = WaveformCanvas(right_frame, width=650, height=140)
        self.waveform_canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

    def select_reference(self):
        path = filedialog.askopenfilename(title="Select Reference File", filetypes=[("Media Files", "*.wav *.mp3 *.mp4 *.mov *.mkv *.avi")])
        if path:
            self.reference_path = path
            self.lbl_ref_name.config(text=os.path.basename(path), fg="#00ffcc")

    def add_inputs(self):
        paths = filedialog.askopenfilenames(title="Select Camera Input Files", filetypes=[("Media Files", "*.wav *.mp3 *.mp4 *.mov *.mkv *.avi")])
        for p in paths:
            if p not in self.input_paths:
                self.input_paths.append(p)
                self.input_listbox.insert(tk.END, os.path.basename(p))

    def run_sync_analysis(self):
        if not self.reference_path or not self.input_paths:
            messagebox.showerror("Error", "Please select a reference file and at least one camera input file.")
            return

        try:
            # Extract audio signals
            ref_wav = extract_audio(self.reference_path)
            sr_ref, ref_sig = load_wav(ref_wav)

            all_signals = [ref_sig]
            labels = ["Reference"]
            files = [os.path.basename(self.reference_path)]

            for i, inp_path in enumerate(self.input_paths, start=1):
                cam_label = f"Camera {chr(64+i)}"
                wav_path = extract_audio(inp_path)
                sr_inp, inp_sig = load_wav(wav_path)
                all_signals.append(inp_sig)
                labels.append(cam_label)
                files.append(os.path.basename(inp_path))

            sync_mode = self.sync_mode_var.get()
            offsets, confidences, feature_dicts = solve_multi_source_sync(
                all_signals, sr_ref, sync_mode=sync_mode, ref_index=0
            )

            self.sync_results = []
            review_items = []

            for idx in range(len(all_signals)):
                label = labels[idx]
                fname = files[idx]
                offset = float(offsets[idx])
                conf = float(confidences[idx])

                if idx == 0:
                    drift_val = 0.0
                    badge, status = "green", "Good (reference)"
                else:
                    win_res = windowed_offsets(ref_sig, all_signals[idx], sr_ref)
                    drift_info = analyze_drift(win_res)
                    drift_val = drift_info["drift_ms_per_hour"]
                    badge, status = badge_and_status_from_confidence(conf, drift_val)

                if badge == "red" or "Review" in status:
                    review_items.append(f"{label} ({fname}) — Low Conf: {conf*100:.0f}%")

                self.sync_results.append({
                    "source": label,
                    "file": fname,
                    "offset_sec": offset,
                    "confidence": conf,
                    "drift_ms_per_hour": drift_val,
                    "badge": badge,
                    "status": status,
                    "signal": all_signals[idx],
                })

            # Populate Treeview
            self.tree.delete(*self.tree.get_children())
            for item in self.sync_results:
                badge_str = "🟢 GREEN" if item["badge"] == "green" else ("🟡 YELLOW" if item["badge"] == "yellow" else "🔴 RED")
                self.tree.insert("", tk.END, values=(
                    item["source"],
                    f"{item['offset_sec']:+.3f}",
                    f"{item['drift_ms_per_hour']} ms/hr" if item["drift_ms_per_hour"] is not None else "0.0",
                    f"{item['confidence']*100:.1f}%",
                    badge_str,
                    item["status"],
                ))

            if review_items:
                self.lbl_review_items.config(text="\n".join(review_items), fg="#ff4444")
            else:
                self.lbl_review_items.config(text="All sources verified clean!", fg="#00ffcc")

            # Plot reference waveform on canvas
            self.waveform_canvas.plot_waveform(ref_sig, offset_sec=0.0)
            messagebox.showinfo("Success", f"Sync completed using '{sync_mode}' mode.")

        except Exception as e:
            messagebox.showerror("Execution Error", str(e))

    def on_source_select(self, event):
        selected_items = self.tree.selection()
        if not selected_items:
            return
        item_idx = self.tree.index(selected_items[0])
        res = self.sync_results[item_idx]
        self.waveform_canvas.plot_waveform(res["signal"], offset_sec=res["offset_sec"])

    def nudge_selected(self, delta_sec):
        selected_items = self.tree.selection()
        if not selected_items:
            return
        item_idx = self.tree.index(selected_items[0])
        self.sync_results[item_idx]["offset_sec"] += delta_sec
        new_offset = self.sync_results[item_idx]["offset_sec"]

        # Update Treeview text
        vals = list(self.tree.item(selected_items[0])["values"])
        vals[1] = f"{new_offset:+.3f}"
        vals[5] = "Manually Nudged"
        self.tree.item(selected_items[0], values=vals)
        self.waveform_canvas.plot_waveform(self.sync_results[item_idx]["signal"], offset_sec=new_offset)

    def export_fcpxml(self):
        if not self.sync_results:
            messagebox.showerror("Error", "Run sync analysis first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".fcpxml", filetypes=[("FCPXML", "*.fcpxml")])
        if path:
            report_data = []
            for r in self.sync_results:
                report_data.append({
                    "source": r["source"],
                    "file": r["file"],
                    "offset_sec": r["offset_sec"],
                    "confidence": r["confidence"],
                    "status": r["status"],
                })
            temp_json = "temp_report.json"
            with open(temp_json, "w") as f:
                json.dump(report_data, f)
            tl = build_timeline(temp_json, os.path.dirname(self.reference_path))
            export_timeline(tl, path)
            if os.path.exists(temp_json):
                os.remove(temp_json)
            messagebox.showinfo("Exported", f"FCPXML timeline saved to {path}")

    def export_csv(self):
        if not self.sync_results:
            messagebox.showerror("Error", "Run sync analysis first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if path:
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Source", "File", "Offset_Sec", "Drift_MS_Per_HR", "Confidence", "Badge", "Status"])
                for r in self.sync_results:
                    writer.writerow([r["source"], r["file"], r["offset_sec"], r["drift_ms_per_hour"], r["confidence"], r["badge"], r["status"]])
            messagebox.showinfo("Exported", f"CSV report saved to {path}")

    def export_pdf(self):
        if not self.sync_results:
            messagebox.showerror("Error", "Run sync analysis first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
        if path:
            # Simple clean text/markdown PDF summary writer
            with open(path, "w") as f:
                f.write("%PDF-1.4 SyncCut Confidence Report\n")
                f.write("Source, Offset (s), Drift (ms/hr), Confidence, Badge, Status\n")
                for r in self.sync_results:
                    f.write(f"{r['source']}, {r['offset_sec']:.3f}, {r['drift_ms_per_hour']}, {r['confidence']*100:.1f}%, {r['badge']}, {r['status']}\n")
            messagebox.showinfo("Exported", f"PDF report saved to {path}")


if __name__ == "__main__":
    app = SyncCutTkinterApp()
    app.mainloop()
