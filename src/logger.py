import numpy as np
import json
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from typing import List, Dict, Any, Tuple

class SDKLogger:
    def __init__(self, map_size: Tuple[float, float], grid_res: int = 50):
        self.map_width, self.map_height = map_size
        self.grid_res = grid_res
        
        # Grid representing visits: X is columns (width), Y is rows (height)
        self.grid = np.zeros((grid_res, grid_res), dtype=np.int32)
        
        # Anomaly / Bug logging
        self.anomalies: List[Dict[str, Any]] = []
        
        # Tracking general stats
        self.total_steps = 0
        self.bug_zone_hits = 0
        self.wall_clips = 0
        self.oob_violations = 0

    def log_position(self, x: float, y: float):
        """Map continuous 2D coordinates to discrete grid cells and increment count."""
        self.total_steps += 1
        
        # Clamp coordinates to map boundary to avoid index errors
        clamped_x = max(0.0, min(x, self.map_width - 1e-5))
        clamped_y = max(0.0, min(y, self.map_height - 1e-5))
        
        # Find grid index
        grid_x = int((clamped_x / self.map_width) * self.grid_res)
        grid_y = int((clamped_y / self.map_height) * self.grid_res)
        
        # Increment coordinate visit (Y maps to rows, X to columns)
        self.grid[grid_y, grid_x] += 1

    def log_anomaly(self, anomaly_type: str, details: Dict[str, Any], step: int):
        """Record an anomaly event with metadata."""
        anomaly_entry = {
            "step": step,
            "type": anomaly_type,
            "details": details
        }
        self.anomalies.append(anomaly_entry)
        
        if anomaly_type == "BUG_ZONE_TRIGGER":
            self.bug_zone_hits += 1
        elif anomaly_type == "WALL_CLIP":
            self.wall_clips += 1
        elif anomaly_type == "OUT_OF_BOUNDS":
            self.oob_violations += 1

    def save_logs(self, filepath: str):
        """Save standard JSON log of detected exploits, bugs, and summary metrics."""
        report = {
            "summary": {
                "total_steps": self.total_steps,
                "total_anomalies": len(self.anomalies),
                "bug_zone_hits": self.bug_zone_hits,
                "wall_clips": self.wall_clips,
                "out_of_bounds_violations": self.oob_violations
            },
            "anomalies": self.anomalies
        }
        with open(filepath, 'w') as f:
            json.dump(report, f, indent=4)

    def save_heatmap_image(self, 
                           filepath: str, 
                           obstacles: List[Dict[str, Any]], 
                           player_pos: List[float], 
                           goal_pos: List[float], 
                           bug_zones: List[Dict[str, Any]],
                           title: str = "Agent Exploration Heatmap"):
        """Generate and save a premium, visual 2D plot showing paths, obstacles, and bugs."""
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 8), dpi=150)
        
        # Plot spatial density matrix
        # Use log scale for density to distinguish heavy trails from light exploration
        grid_log = np.log1p(self.grid)
        
        # Extents: left, right, bottom, top
        im = ax.imshow(grid_log, 
                       cmap='viridis', 
                       origin='lower', 
                       extent=[0, self.map_width, 0, self.map_height],
                       interpolation='gaussian', 
                       alpha=0.85)
        
        # Color bar styling
        cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label('Log Visit Density', color='white', fontsize=12)
        cbar.ax.yaxis.set_tick_params(color='white')
        plt.setp(plt.getp(cbar.ax.yaxis, 'ticklabels'), color='white')

        # Draw obstacles
        for obs in obstacles:
            if obs.get("type") == "rect":
                rect = plt.Rectangle((obs["x"], obs["y"]), obs["w"], obs["h"], 
                                     color='#e74c3c', alpha=0.6, label='Obstacle' if 'Obstacle' not in ax.get_legend_handles_labels()[1] else "")
                ax.add_patch(rect)
            elif obs.get("type") == "circle":
                circle = plt.Circle((obs["x"], obs["y"]), obs["r"], 
                                    color='#e74c3c', alpha=0.6, label='Obstacle' if 'Obstacle' not in ax.get_legend_handles_labels()[1] else "")
                ax.add_patch(circle)

        # Draw bug zones (exploits)
        for bz in bug_zones:
            rect = plt.Rectangle((bz["x"], bz["y"]), bz["w"], bz["h"], 
                                 linewidth=1.5, edgecolor='#f1c40f', facecolor='#f1c40f', alpha=0.4, 
                                 hatch='//', label='Hidden Bug Zone' if 'Hidden Bug Zone' not in ax.get_legend_handles_labels()[1] else "")
            ax.add_patch(rect)
            # Add text label for the bug
            ax.text(bz["x"] + bz["w"]/2, bz["y"] + bz["h"]/2, bz.get("error_code", "BUG"),
                    color='#f1c40f', fontsize=8, fontweight='bold', ha='center', va='center')

        # Draw Player position
        ax.scatter(player_pos[0], player_pos[1], color='#3498db', s=120, edgecolors='white', 
                   zorder=5, label='Player')
        
        # Draw Goal position
        ax.scatter(goal_pos[0], goal_pos[1], color='#2ecc71', marker='*', s=200, edgecolors='white', 
                   zorder=5, label='Goal Objective')

        # Set labels and bounds
        ax.set_xlim(0, self.map_width)
        ax.set_ylim(0, self.map_height)
        ax.set_xlabel('Game X Coordinate', fontsize=11, color='white')
        ax.set_ylabel('Game Y Coordinate', fontsize=11, color='white')
        ax.set_title(title, fontsize=14, fontweight='bold', pad=15, color='white')
        
        # Grid lines
        ax.grid(True, color='#2c3e50', linestyle='--', alpha=0.5)
        
        # Legend with clean background
        legend = ax.legend(loc='upper right', framealpha=0.8, facecolor='#2c3e50', edgecolor='#34495e')
        for text in legend.get_texts():
            text.set_color('white')
            
        plt.tight_layout()
        plt.savefig(filepath, facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close()
