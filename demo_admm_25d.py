"""2.5D ADMM demo: 7 altitude layers (z = -3..+3), x-y negotiation inside each layer.

Idea
  * Agents on different layers (|dz| >= 1) cannot collide -> no constraint.
  * Agents on the SAME layer (or mid-transition between layers) negotiate in x-y
    with the ADMM solver.
  * An agent that keeps getting pushed off its path (ADMM keeps making it yield)
    climbs/descends to a less crowded neighbouring layer.

Run:  uv run python demo_admm_25d.py
Out:  outputs/admm_25d/<timestamp>/ (PNG, GIF, CSV, SQLite DB)
"""
from datetime import datetime
from pathlib import Path
import sqlite3
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
from mpl_toolkits.mplot3d.art3d import Line3DCollection

from conflict_resolution.solver import ADMMSolver
from conflict_resolution.convergence import ConvergenceLogger

# ---------------- Dynamic Output Folder (subfolder with date/time) ----------------
timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_DIR = Path(__file__).resolve().parent / "outputs" / "admm_25d" / timestamp_str
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------- parameters ----------------
N_AGENTS, TICKS = 16, 90
LAYERS = np.arange(-3, 4)            # 7 layers
D_SAFE, V_MAX, DT = 1.0, 0.5, 1.0
VZ = 0.5                             # layers per tick during a climb
YIELD_THRESH, COOLDOWN = 0.30, 8
ARENA = 10.0
rng = np.random.default_rng(7)

# ---------------- scenario: everyone crosses the centre ----------------
ang = np.linspace(0, 2 * np.pi, N_AGENTS, endpoint=False)
starts = 9.5 * np.c_[np.cos(ang), np.sin(ang)]
goals = -starts + rng.normal(0, 0.25, starts.shape)          # antipodal, slightly jittered
z = rng.choice([-1, 0, 1], size=N_AGENTS).astype(float)       # crowd the middle layers
z_goal = z.copy()                                              # target layer
yield_ema = np.zeros(N_AGENTS)
cooldown = np.zeros(N_AGENTS)

log = ConvergenceLogger()
# layer_gap has a safety margin: agents climb up to VZ per tick, so two agents
# exactly one layer apart could end the tick closer than one layer.
solver = ADMMSolver(d_safe=D_SAFE, v_max=V_MAX, dt=DT, logger=log,
                    layer_gap=1.0 + 2 * VZ)

pos = starts.copy()
P, Z = [pos.copy()], [z.copy()]
min_sep, occupancy, n_cons, climbs = [], [], [], 0

def nearest_layer(zv): return np.clip(np.round(zv), -3, 3)

for t in range(TICKS):
    to_goal = goals - pos
    dist = np.linalg.norm(to_goal, axis=1, keepdims=True)
    step = to_goal / np.maximum(dist, 1e-9) * np.minimum(dist, V_MAX * DT)
    target = pos + step

    res = solver.solve(pos, target, scenario=f"tick {t}", z=z)
    n_cons.append(res.n_constraints)

    # how much did ADMM make each agent deviate from what it wanted?
    shortfall = np.linalg.norm(res.positions - target, axis=1) / (V_MAX * DT)
    yield_ema = 0.7 * yield_ema + 0.3 * shortfall
    pos = res.positions

    # --- layer-change decision: climb to a less crowded neighbour layer ---
    cooldown = np.maximum(cooldown - 1, 0)
    for i in range(N_AGENTS):
        if yield_ema[i] > YIELD_THRESH and cooldown[i] == 0 and abs(z[i] - z_goal[i]) < 1e-6:
            def crowd(layer):
                m = np.abs(z_goal - layer) < 0.5
                m[i] = False
                return int(np.sum(m & (np.linalg.norm(pos - pos[i], axis=1) < 4 * D_SAFE)))
            here = crowd(z_goal[i])
            options = [l for l in (z_goal[i] - 1, z_goal[i] + 1) if -3 <= l <= 3]
            best = min(options, key=crowd)
            if crowd(best) < here:
                z_goal[i] = best; cooldown[i] = COOLDOWN; climbs += 1
    # vertical motion
    dz = np.clip(z_goal - z, -VZ, VZ)
    z = z + dz

    # safety: pairs closer than one layer vertically must keep d_safe in x-y
    worst = np.inf
    for i in range(N_AGENTS):
        for j in range(i + 1, N_AGENTS):
            if abs(z[i] - z[j]) < 1.0:
                worst = min(worst, np.linalg.norm(pos[i] - pos[j]))
    min_sep.append(worst)
    occupancy.append([int(np.sum(nearest_layer(z) == l)) for l in LAYERS])
    P.append(pos.copy()); Z.append(z.copy())

P, Z = np.array(P), np.array(Z)
occupancy = np.array(occupancy).T

# Save CSV log
log_csv_path = OUTPUT_DIR / "admm_25d_log.csv"
log.to_csv(str(log_csv_path))

# Save to SQLite Database
db_path = OUTPUT_DIR / "admm_25d_records.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("""
    CREATE TABLE IF NOT EXISTS tick_records (
        tick INTEGER PRIMARY KEY,
        scenario TEXT,
        n_agents INTEGER,
        n_constraints INTEGER,
        iterations INTEGER,
        converged BOOLEAN,
        solve_time_ms REAL,
        final_primal_residual REAL,
        final_dual_residual REAL,
        min_separation REAL
    )
""")
for idx, r in enumerate(log.records):
    cur.execute("""
        INSERT INTO tick_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        idx, r.scenario, r.n_agents, r.n_constraints, r.iterations,
        r.converged, r.solve_time_ms, r.final_primal_residual,
        r.final_dual_residual, r.min_separation
    ))
conn.commit()
conn.close()

s = log.summary()
finite = [m for m in min_sep if np.isfinite(m)]
print(f"Agents: {N_AGENTS} | layers: 7 | ticks: {TICKS}")
print(f"ADMM solves converged: {s['converged_pct']:.0f}% | mean iters {s['mean_iters']:.1f} | "
      f"mean {s['mean_ms']:.2f} ms | max {s['max_ms']:.2f} ms")
print(f"Layer changes triggered: {climbs}")
print(f"Min same-layer x-y separation: {min(finite):.3f} (safe = {D_SAFE})  "
      f"collision-free: {min(finite) >= D_SAFE - 5e-3}")

# ---------------- drawing ----------------
cmap = plt.cm.viridis
norm = plt.Normalize(-3.5, 3.5)

def draw_layers(ax):
    g = np.linspace(-ARENA, ARENA, 6)
    X, Y = np.meshgrid([-ARENA, ARENA], [-ARENA, ARENA])
    for l in LAYERS:
        ax.plot_surface(X, Y, np.full_like(X, l), color=cmap(norm(l)), alpha=0.07, shade=False)
        for gv in g:
            ax.plot([-ARENA, ARENA], [gv, gv], [l, l], color=cmap(norm(l)), lw=0.3, alpha=0.35)
            ax.plot([gv, gv], [-ARENA, ARENA], [l, l], color=cmap(norm(l)), lw=0.3, alpha=0.35)
    ax.set_xlim(-ARENA, ARENA); ax.set_ylim(-ARENA, ARENA); ax.set_zlim(-3.5, 3.5)
    ax.set_xlabel("x"); ax.set_ylabel("y"); ax.set_zlabel("z (layer)")
    ax.set_zticks(LAYERS)
    ax.set_box_aspect((1, 1, 0.9))

def draw_state(ax, f, azim):
    ax.cla(); draw_layers(ax)
    for k in range(N_AGENTS):
        pts = np.c_[P[:f + 1, k], Z[:f + 1, k]]
        if len(pts) > 1:
            segs = np.stack([pts[:-1], pts[1:]], axis=1)
            lc = Line3DCollection(segs, colors=cmap(norm(Z[1:f + 1, k])), linewidths=1.6)
            ax.add_collection3d(lc)
        ax.plot(*goals[k], -3.5, marker="*", color="k", ms=4, alpha=.4)
    ax.scatter(P[f, :, 0], P[f, :, 1], Z[f], c=Z[f], cmap=cmap, norm=norm,
               s=60, edgecolor="k", depthshade=False)
    ax.view_init(elev=24, azim=azim)

# ---- static figure ----
fig = plt.figure(figsize=(15, 6.2))
ax3 = fig.add_subplot(1, 2, 1, projection="3d")
draw_state(ax3, TICKS, -58)
ax3.set_title("2.5D airspace: 7 layers, ADMM negotiates in x-y per layer")
ax2 = fig.add_subplot(2, 2, 2)
im = ax2.imshow(occupancy, aspect="auto", origin="lower", cmap="magma",
                extent=[0, TICKS, -3.5, 3.5])
ax2.set_yticks(LAYERS); ax2.set_ylabel("layer z"); ax2.set_title("Agents per layer over time")
fig.colorbar(im, ax=ax2, pad=0.01)
ax4 = fig.add_subplot(2, 2, 4)
ax4.plot([m if np.isfinite(m) else np.nan for m in min_sep], color="tab:purple",
         label="min same-layer separation")
ax4.axhline(D_SAFE, color="k", ls="--", label="safe distance")
ax4.set_xlabel("tick"); ax4.set_ylim(0, 20); ax4.legend(fontsize=8); ax4.grid(alpha=.3)
plt.tight_layout()
static_png_path = OUTPUT_DIR / "admm_25d.png"
plt.savefig(static_png_path, dpi=130)
plt.close(fig)

# ---- animation ----
fig2 = plt.figure(figsize=(7, 6))
ax = fig2.add_subplot(111, projection="3d")
frames = list(range(0, TICKS + 1, 2))
def update(f):
    draw_state(ax, f, -58 + 0.5 * f)
    ax.set_title(f"tick {f}   layer changes so far: {int(np.sum(np.abs(np.diff(Z[:f + 1], axis=0)) > 0, axis=0).astype(bool).sum()) if f else 0} agents")

anim = FuncAnimation(fig2, update, frames=frames, interval=120)
gif_path = OUTPUT_DIR / "admm_25d.gif"
anim.save(gif_path, writer=PillowWriter(fps=8), dpi=80)
plt.close(fig2)

print(f"\nSaved all results in: {OUTPUT_DIR}/")
print(f"  - PNG : {static_png_path.name}")
print(f"  - GIF : {gif_path.name}")
print(f"  - CSV : {log_csv_path.name}")
print(f"  - DB  : {db_path.name}")
