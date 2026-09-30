/** Show only packets received after this page establishes its first snapshot. */
export class Presentation {
  constructor() {
    this.baseline = null;
  }

  /** Capture a page-local starting point without changing the receiver log. */
  start(snapshot) {
    this.baseline = {
      samples: snapshot.samples.length,
      received: snapshot.received,
      invalid: snapshot.invalid,
      malformed: snapshot.malformed,
      source: snapshot.source,
    };
  }

  /**
   * Derive the current presentation from a cumulative receiver snapshot.
   * Processing flow: establish cursor -> select subsequent packets -> rebuild
   * visible track counts and latest telemetry -> preserve service status.
   */
  apply(snapshot) {
    if (this.baseline === null) this.start(snapshot);
    const base = this.baseline;
    // A restarted service or a different capture begins a new local window.
    if (snapshot.source !== base.source || snapshot.received < base.received ||
        snapshot.samples.length < base.samples) {
      this.start(snapshot);
    }
    const samples = snapshot.samples.slice(this.baseline.samples);
    const counts = new Map();
    for (const sample of samples) {
      counts.set(sample.track, (counts.get(sample.track) || 0) + 1);
    }
    const tracks = [];
    for (const track of snapshot.tracks) {
      if (counts.has(track.key)) tracks.push({...track, count: counts.get(track.key)});
    }
    const latest = samples.at(-1) || null;
    let state = snapshot.state;
    if (latest === null && /^(Valid frame|Waiting for valid frames)/.test(state)) {
      state = 'Ready for new transmission';
    }
    return {
      ...snapshot, samples, tracks, state,
      valid: samples.length,
      received: snapshot.received - this.baseline.received,
      invalid: snapshot.invalid - this.baseline.invalid,
      malformed: snapshot.malformed - this.baseline.malformed,
      activeLatest: latest,
      lastReceivedUtcNs: latest?.receivedUtcNs ?? null,
    };
  }
}
