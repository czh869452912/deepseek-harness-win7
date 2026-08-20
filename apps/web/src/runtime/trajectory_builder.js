/**
 * Trajectory Target Snapshot Builder.
 * 1:1 Faithful implementation of `@deepseek-ai/dsh-client-ui-trajectory/trajectory-snapshot-builder.ts`
 */

export const EMPTY_TRAJECTORY_SNAPSHOT = {
  eventNodes: [],
  eventLocations: new Map(),
  requests: [],
  callSchemas: new Map(),
  partial: null,
  runningCalls: [],
};

export class TrajectorySnapshotBuilder {
  constructor() {
    this.nodes = new Map(); // key -> contribution
    this.contributions = [];
  }

  replace(nodes = []) {
    this.nodes.clear();
    nodes.forEach((n) => {
      const key = n.key || `node-${n.seq || Math.random()}`;
      this.nodes.set(key, n);
    });
    return this.snapshot();
  }

  apply(upserts = []) {
    upserts.forEach((n) => {
      const key = n.key || `node-${n.seq || Math.random()}`;
      this.nodes.set(key, n);
    });
    return this.snapshot();
  }

  snapshot(partial = null, runningCalls = []) {
    const finalized = [];
    const eventLocations = new Map();
    const requests = [];
    const callSchemas = new Map();

    const sortedContributions = Array.from(this.nodes.values()).sort(
      (a, b) => (a.seq || 0) - (b.seq || 0)
    );

    sortedContributions.forEach((contrib) => {
      finalized.push(contrib);
      if (contrib.seq && contrib.location) {
        eventLocations.set(contrib.seq, contrib.location);
      }
      if (contrib.request) {
        requests.push(contrib.request);
      }
    });

    return {
      eventNodes: finalized,
      eventLocations,
      requests,
      callSchemas,
      partial,
      runningCalls,
    };
  }
}
