import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch
import subprocess
import runtime_guard

from runtime_guard import stale_reason, quarantine


class GuardTests(unittest.TestCase):
    def settings(self, stamp):
        value = datetime.fromtimestamp(stamp, timezone.utc).isoformat()
        return dict(worker_heartbeat_at=value, scheduler_heartbeat_at=value)

    def test_fresh(self):
        self.assertIsNone(stale_reason(self.settings(990), now=1000, started=950))

    def test_scheduler_stuck_even_when_worker_alive(self):
        values = self.settings(990)
        values['scheduler_heartbeat_at'] = self.settings(600)['scheduler_heartbeat_at']
        self.assertEqual(stale_reason(values, now=1000, started=500), 'scheduler_heartbeat_at')

    def test_startup_grace(self):
        self.assertIsNone(stale_reason({}, now=1000, started=990))

    def test_startup_never_became_ready(self):
        self.assertEqual(stale_reason({}, now=1000, started=500), 'worker_heartbeat_at')

    def test_future_and_bad_timestamp(self):
        for value in ['broken', True, '2099-01-01T00:00:00+00:00']:
            self.assertEqual(stale_reason({'worker_heartbeat_at': value}, now=1000, started=500), 'worker_heartbeat_at')

    def test_old_process_heartbeat_not_accepted_as_startup_success(self):
        self.assertEqual(stale_reason(self.settings(999), now=1300, started=1000), 'worker_heartbeat_at')

    def test_quarantine_only_inflight_never_requeues_delivery(self):
        cursor = Mock()
        quarantine(cursor)
        self.assertEqual(cursor.execute.call_count, 2)
        for call in cursor.execute.call_args_list:
            self.assertIn("WHERE status='processing'", call.args[0])
            self.assertNotIn("'pending'", call.args[0])
        self.assertIn("status='ambiguous'", cursor.execute.call_args_list[0].args[0])

    def test_hung_child_is_killed_after_grace(self):
        child = Mock()
        child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired('worker', 20), 0]
        runtime_guard.stop_child(child)
        child.terminate.assert_called_once()
        child.kill.assert_called_once()

    def test_stale_scheduler_stops_and_relaunches_child(self):
        stop = Mock()
        stop.is_set.return_value = False
        waits = []

        def wait(seconds):
            waits.append(seconds)
            if len(waits) == 3:
                stop.is_set.return_value = True
                return True
            return False

        stop.wait.side_effect = wait
        db = MagicMock()
        cursor = db.__enter__.return_value.cursor.return_value.__enter__.return_value
        values = self.settings(990)
        values['scheduler_heartbeat_at'] = self.settings(500)['scheduler_heartbeat_at']
        cursor.fetchall.return_value = list(values.items())
        child = Mock(pid=7)
        child.poll.return_value = None
        with (patch.object(runtime_guard.threading, 'Event', return_value=stop),
              patch.object(runtime_guard.signal, 'signal'),
              patch.object(runtime_guard, 'connection', return_value=db),
              patch.object(runtime_guard.subprocess, 'Popen', return_value=child) as launch,
              patch.object(runtime_guard.time, 'time', side_effect=[500, 1000, 1000, 1001, 1010]),
              patch.object(runtime_guard, 'log') as log):
            self.assertEqual(runtime_guard.main(), 0)
        self.assertEqual(launch.call_count, 2)
        self.assertEqual(child.terminate.call_count, 2)
        log.assert_any_call('guard_stale', heartbeat='scheduler_heartbeat_at')


if __name__ == '__main__':
    unittest.main()
