package ph.pbcnx.it9308;

/** Tune/stream status. RF lock and metrics are not decoded yet; fields stay unknown. */
public final class SignalStatus {
    public final boolean known;
    public final boolean locked;
    public final int strength;
    public final int quality;

    private SignalStatus(boolean known, boolean locked, int strength, int quality) {
        this.known = known;
        this.locked = locked;
        this.strength = strength;
        this.quality = quality;
    }

    public static SignalStatus unknown() {
        return new SignalStatus(false, false, -1, -1);
    }

    @Override
    public String toString() {
        return known ? "locked=" + locked + " strength=" + strength + " quality=" + quality
                : "unknown";
    }
}
