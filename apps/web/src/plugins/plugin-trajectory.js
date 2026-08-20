/**
 * Trajectory Performance & Event Ledger Plugin (`@deepseek-ai/dsh-client-ui-trajectory`)
 * 1:1 Reference-aligned Cordis Slot Plugin for Trajectory View.
 */

import { TrajectoryView } from "../ui/trajectory.js";

export class PluginTrajectory {
  static id = "ui-trajectory";
  static name = "@deepseek-ai/dsh-client-ui-trajectory";

  apply(ctx) {
    ctx.slots.register(
      {
        name: "trajectory",
      },
      TrajectoryComponent
    );
  }
}

class TrajectoryComponent {
  constructor(props) {
    this.props = props;
    this.view = null;
    this.container = null;
  }

  render(container) {
    this.container = container;
    const { useSession } = this.props;
    const sessionSnapshot = useSession ? useSession() : null;
    const trajectoryLayout = (sessionSnapshot && sessionSnapshot.trajectoryLayout) || [];

    if (!this.view) {
      this.view = new TrajectoryView({ containerId: container });
      this.view.updateLayout(trajectoryLayout);
    } else {
      this.view.container = container;
      this.view.updateLayout(trajectoryLayout);
    }

    return container;
  }
}
