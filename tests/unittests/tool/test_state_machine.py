"""TaskStateMachine 任务状态机测试。

测试目标：fabrica/tool.py 中的 TaskStatus / TaskStateMachine
覆盖：枚举值、合法转换、非法转换、终态、进度更新、序列化、取消
"""

import unittest

from fabrica.tool import TaskStateMachine, TaskStatus


class TestTaskStatus(unittest.TestCase):
    """TaskStatus 枚举测试集。"""

    def test_enum_values(self):
        """8 种任务状态枚举值应正确。"""
        expected = {
            "PENDING": "pending",
            "VALIDATING": "validating",
            "VALID": "valid",
            "INVALID": "invalid",
            "RUNNING": "running",
            "COMPLETED": "completed",
            "FAILED": "failed",
            "CANCELLED": "cancelled",
        }
        self.assertEqual(len(TaskStatus), len(expected))
        for name, value in expected.items():
            self.assertEqual(getattr(TaskStatus, name).value, value)

    def test_enum_inherits_str(self):
        """枚举值应可直接作为字符串比较。"""
        self.assertEqual(TaskStatus.PENDING, "pending")
        self.assertEqual(TaskStatus.COMPLETED, "completed")


class TestTaskStateMachine(unittest.TestCase):
    """TaskStateMachine 任务状态机测试集。"""

    def _make_sm(self, **kwargs):
        """构造 TaskStateMachine 测试实例。"""
        defaults = {"task_id": "t1", "tool_name": "dummy", "params": {}}
        defaults.update(kwargs)
        return TaskStateMachine(**defaults)

    def test_initial_state(self):
        """初始状态应为 PENDING。"""
        sm = self._make_sm()
        self.assertEqual(sm.status, TaskStatus.PENDING)
        self.assertEqual(sm.progress, 0.0)

    def test_legal_transition_chain(self):
        """合法转换链应依次返回 True。"""
        sm = self._make_sm()
        self.assertTrue(sm.transition(TaskStatus.VALIDATING))
        self.assertTrue(sm.transition(TaskStatus.VALID))
        self.assertTrue(sm.transition(TaskStatus.RUNNING))
        self.assertTrue(sm.transition(TaskStatus.COMPLETED))
        self.assertEqual(sm.status, TaskStatus.COMPLETED)

    def test_illegal_transition_returns_false(self):
        """PENDING 直接转 COMPLETED 应返回 False。"""
        sm = self._make_sm()
        self.assertFalse(sm.transition(TaskStatus.COMPLETED))
        self.assertEqual(sm.status, TaskStatus.PENDING)

    def test_validating_to_invalid(self):
        """VALIDATING 可转 INVALID。"""
        sm = self._make_sm()
        self.assertTrue(sm.transition(TaskStatus.VALIDATING))
        self.assertTrue(sm.transition(TaskStatus.INVALID))
        self.assertEqual(sm.status, TaskStatus.INVALID)

    def test_running_to_failed(self):
        """RUNNING 可转 FAILED。"""
        sm = self._make_sm()
        sm.transition(TaskStatus.VALIDATING)
        sm.transition(TaskStatus.VALID)
        sm.transition(TaskStatus.RUNNING)
        self.assertTrue(sm.transition(TaskStatus.FAILED))
        self.assertEqual(sm.status, TaskStatus.FAILED)

    def test_running_to_cancelled(self):
        """RUNNING 可转 CANCELLED。"""
        sm = self._make_sm()
        sm.transition(TaskStatus.VALIDATING)
        sm.transition(TaskStatus.VALID)
        sm.transition(TaskStatus.RUNNING)
        self.assertTrue(sm.transition(TaskStatus.CANCELLED))
        self.assertEqual(sm.status, TaskStatus.CANCELLED)

    def test_terminal_states_cannot_transition(self):
        """终态不可再转换。"""
        for terminal in (
            TaskStatus.INVALID,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        ):
            sm = self._make_sm()
            # 直接摆到终态：先用合法路径到达
            if terminal == TaskStatus.INVALID:
                sm.transition(TaskStatus.VALIDATING)
                sm.transition(TaskStatus.INVALID)
            elif terminal == TaskStatus.COMPLETED:
                sm.transition(TaskStatus.VALIDATING)
                sm.transition(TaskStatus.VALID)
                sm.transition(TaskStatus.RUNNING)
                sm.transition(TaskStatus.COMPLETED)
            elif terminal == TaskStatus.FAILED:
                sm.transition(TaskStatus.VALIDATING)
                sm.transition(TaskStatus.VALID)
                sm.transition(TaskStatus.RUNNING)
                sm.transition(TaskStatus.FAILED)
            else:  # CANCELLED
                sm.transition(TaskStatus.VALIDATING)
                sm.transition(TaskStatus.VALID)
                sm.transition(TaskStatus.RUNNING)
                sm.transition(TaskStatus.CANCELLED)
            # 终态下任何转换都应失败
            self.assertFalse(sm.transition(TaskStatus.PENDING))
            self.assertEqual(sm.status, terminal)

    def test_update_progress(self):
        """update_progress 应更新进度。"""
        sm = self._make_sm()
        sm.update_progress(75.0)
        self.assertEqual(sm.progress, 75.0)

    def test_completed_at_set_on_terminal(self):
        """进入终态应记录 completed_at。"""
        sm = self._make_sm()
        self.assertIsNone(sm._completed_at)
        sm.transition(TaskStatus.VALIDATING)
        sm.transition(TaskStatus.VALID)
        sm.transition(TaskStatus.RUNNING)
        sm.transition(TaskStatus.COMPLETED)
        self.assertIsNotNone(sm._completed_at)

    def test_to_summary(self):
        """to_summary 应返回字段正确的摘要。"""
        sm = self._make_sm(task_id="abc", tool_name="dummy", params={"x": 1})
        sm.update_progress(30.0)
        summary = sm.to_summary()
        self.assertEqual(summary.task_id, "abc")
        self.assertEqual(summary.tool_name, "dummy")
        self.assertEqual(summary.status, "pending")
        self.assertEqual(summary.progress, 30.0)
        self.assertIsNone(summary.completed_at)

    def test_to_detail(self):
        """to_detail 应返回包含参数/结果/错误的详情。"""
        sm = self._make_sm(params={"x": 1})
        sm._result = {"ok": True}
        sm._error = "err"
        detail = sm.to_detail()
        self.assertEqual(detail.params, {"x": 1})
        self.assertEqual(detail.result, {"ok": True})
        self.assertEqual(detail.error, "err")
        self.assertEqual(detail.logs, [])
        self.assertEqual(detail.status, "pending")

    def test_cancel_and_cancelled(self):
        """cancel 后 cancelled 应为 True。"""
        sm = self._make_sm()
        self.assertFalse(sm.cancelled)
        sm.cancel()
        self.assertTrue(sm.cancelled)


if __name__ == "__main__":
    unittest.main()