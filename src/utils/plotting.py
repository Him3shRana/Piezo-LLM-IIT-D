import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def plot_temp_vs_time(log_data, target_temp, title, out_path):
    """Save Temperature vs Time plot."""
    if not log_data:
        return None

    t_ps = [d["time_fs"] / 1000.0 for d in log_data]
    temp_arr = [d["temperature_K"] for d in log_data]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(t_ps, temp_arr, color="C3", linewidth=0.9,
            label="Instantaneous T")

    ax.axhline(
        target_temp,
        color="grey",
        linestyle="--",
        linewidth=0.8,
        label=f"Target {target_temp} K",
    )

    ax.set_xlabel("Time (ps)")
    ax.set_ylabel("Temperature (K)")
    ax.set_title(title)
    ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)

    return out_path


def plot_volume_vs_time(log_data, title, out_path):
    """Save Volume vs Time plot."""
    if not log_data:
        return None

    t_ps = [d["time_fs"] / 1000.0 for d in log_data]
    volume = [d["volume_A3"] for d in log_data]

    fig, ax = plt.subplots(figsize=(8, 4.5))

    ax.plot(
        t_ps,
        volume,
        color="C2",
        linewidth=0.9,
    )

    ax.set_xlabel("Time (ps)")
    ax.set_ylabel("Volume (Å³)")
    ax.set_title(title)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)

    return out_path