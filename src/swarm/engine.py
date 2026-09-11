"""The work engine: admitted work driven to quiescence, with no opinion about the run.

``WorkEngine`` is the controller as it stood before Stage 7 — scheduling, the execution
seam, review, knowledge, cross-pollination, bounded exploration waves and branch stopping —
plus the loop that drives them until nothing more can be admitted.

It deliberately does *not* decide whether the run is finished. That is the run workflow, and
it lives in ``WorkController`` above this layer, which is what a host actually runs. The
split is the one Stage 7 asked for: the state machine is a run-level coordinator over these
services, not a replacement for them, and keeping the engine independently runnable is what
makes that claim checkable rather than a comment.
"""
import asyncio
from .circulation import Circulation
from .controller import ControllerCore
from .domain import Task, TaskStatus
from .persistence import StorageError
from .policies import remaining_seconds, stopped


class WorkEngine(Circulation, ControllerCore):
    """One run's work on one event-loop thread. Subclasses supply the run workflow."""

    # --- workflow hooks -----------------------------------------------------------

    def _prologue(self):
        """Prepare the run before its first wave. True continues; False ends the loop."""
        return True

    def _terminated(self, run):
        """Whether the run has already reached a terminal outcome."""
        return False

    def _halt(self, run):
        """React to a cancelled, stopped or expired run. Returns True to end the loop."""
        self._stop(run.work_stop_reason or 'DEADLINE')
        return True

    def _settled(self):
        """A wave has settled. True means the loop has more to do."""
        return self._advance_cycle()

    def _abandon(self):
        """Nothing more can be admitted; close out what is still waiting."""
        for task in [t for t in self.snapshot().values() if isinstance(t, Task)
                     and t.status in (TaskStatus.PENDING, TaskStatus.READY)]:
            self._fail_pending(task, 'DEPENDENCY_BLOCKED', cancel=True)

    def _cancelled_externally(self):
        self.cancel('CANCELLED')

    # --- the loop -----------------------------------------------------------------

    async def run_until_idle(self):
        if self._running:
            raise RuntimeError('controller is already running')
        self._running = True
        try:
            self._open_run()
            while True:
                run = self.snapshot()[self.run_id]
                if self._terminated(run):
                    break
                if self._cancelled or stopped(run) or remaining_seconds(run) <= 0:
                    if self._halt(run):
                        break
                    continue
                if not self._prologue():
                    break
                self.deliver_messages()
                self._plan_reviews()
                self._sync_state()
                self.retract()
                self.propagate()
                self._dispatch(run)
                if not self.active:
                    if self._settled():
                        continue
                    self._abandon()
                    break
                self._collect(await self._await_progress())
            self._final_settle()
            return self.snapshot()
        except asyncio.CancelledError:
            self._cancelled_externally()
            raise
        except StorageError:
            # Storage is the one failure that makes trustworthy continuation impossible.
            self._storage_failed = True
            raise
        finally:
            await self._drain()
