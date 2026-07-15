from __future__ import annotations

import unittest
from unittest import mock

from xiexie_usage_overlay.pet_window import (
    WS_EX_LAYERED,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_EX_TRANSPARENT,
    PetPresenceDebouncer,
    PetWindowLocator,
    Rect,
    WindowInfo,
    calculate_follow_position,
    pet_candidate_score,
)


def sample_pet() -> WindowInfo:
    return WindowInfo(
        handle=1,
        rect=Rect(2138, 992, 2850, 1632),
        visible=True,
        cloaked=False,
        title="ChatGPT",
        class_name="Chrome_WidgetWin_1",
        process_name="ChatGPT.exe",
        style=0x14000000,
        ex_style=WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_TRANSPARENT,
        process_id=42,
    )


class PetPresenceDebouncerTests(unittest.TestCase):
    def test_brief_detection_misses_keep_pet_present(self) -> None:
        tracker = PetPresenceDebouncer(miss_threshold=3)

        self.assertTrue(tracker.observe(True))
        self.assertTrue(tracker.observe(False))
        self.assertTrue(tracker.observe(False))
        self.assertEqual(tracker.consecutive_misses, 2)

    def test_consecutive_misses_eventually_hide_pet(self) -> None:
        tracker = PetPresenceDebouncer(miss_threshold=3)

        tracker.observe(True)
        tracker.observe(False)
        tracker.observe(False)
        self.assertFalse(tracker.observe(False))

    def test_successful_detection_resets_miss_count(self) -> None:
        tracker = PetPresenceDebouncer(miss_threshold=2)

        tracker.observe(True)
        tracker.observe(False)
        self.assertTrue(tracker.observe(True))
        self.assertEqual(tracker.consecutive_misses, 0)
        self.assertTrue(tracker.observe(False))

    def test_pet_starts_hidden_until_detected(self) -> None:
        tracker = PetPresenceDebouncer(miss_threshold=3)

        self.assertFalse(tracker.observe(False))


class PetWindowDetectionTests(unittest.TestCase):
    def test_real_pet_window_shape_scores(self) -> None:
        pet = sample_pet()
        self.assertIsNotNone(pet_candidate_score(pet))

    def test_main_app_window_is_rejected(self) -> None:
        main = WindowInfo(
            handle=2,
            rect=Rect(0, 0, 3000, 1800),
            visible=True,
            cloaked=False,
            title="ChatGPT",
            class_name="Chrome_WidgetWin_1",
            process_name="ChatGPT.exe",
            style=0x15C70000,
            ex_style=0x00240100,
        )
        self.assertIsNone(pet_candidate_score(main))

    def test_hidden_pet_is_rejected(self) -> None:
        hidden = WindowInfo(
            handle=3,
            rect=Rect(0, 0, 712, 640),
            visible=False,
            cloaked=False,
            title="ChatGPT",
            class_name="Chrome_WidgetWin_1",
            process_name="ChatGPT.exe",
            style=0,
            ex_style=WS_EX_LAYERED | WS_EX_TOOLWINDOW,
        )
        self.assertIsNone(pet_candidate_score(hidden))


class PetWindowLocatorEfficiencyTests(unittest.TestCase):
    def test_cached_window_skips_full_enumeration(self) -> None:
        locator = PetWindowLocator.__new__(PetWindowLocator)
        locator.supported = True
        locator._last_handle = 1
        locator._last_process_id = 42
        locator._last_process_name = "ChatGPT.exe"
        locator._next_full_scan_at = 0.0
        locator._read_window = mock.Mock(return_value=sample_pet())
        locator.user32 = mock.Mock()

        self.assertEqual(locator.find(), sample_pet())
        locator.user32.EnumWindows.assert_not_called()

    def test_missing_window_throttles_full_enumeration(self) -> None:
        locator = PetWindowLocator.__new__(PetWindowLocator)
        locator.supported = True
        locator._last_handle = None
        locator._last_process_id = None
        locator._last_process_name = ""
        locator._next_full_scan_at = 0.0
        locator._enum_proc_type = lambda callback: callback
        locator._read_window = mock.Mock(return_value=None)
        locator.user32 = mock.Mock()

        self.assertIsNone(locator.find())
        self.assertIsNone(locator.find())
        locator.user32.EnumWindows.assert_called_once()


class FollowPositionTests(unittest.TestCase):
    def test_right_pointer_aligns_left_of_pet_shoulder(self) -> None:
        target, base = calculate_follow_position(
            pet_rect=Rect(2138, 992, 2850, 1632),
            overlay_width=760,
            overlay_height=354,
            pointer_offset_y=177,
            gap=24,
            work_area=Rect(0, 0, 3072, 1728),
        )
        self.assertEqual(target, base)
        self.assertAlmostEqual(target[0] + 760 + 24, 2629, delta=2)
        self.assertAlmostEqual(target[1] + 177, 1446, delta=2)

    def test_position_is_clamped_to_monitor(self) -> None:
        target, _base = calculate_follow_position(
            pet_rect=Rect(-100, -100, 400, 500),
            overlay_width=760,
            overlay_height=354,
            pointer_offset_y=177,
            gap=24,
            work_area=Rect(0, 0, 1920, 1040),
            offset_x=-999,
            offset_y=-999,
        )
        self.assertEqual(target, (0, 0))


if __name__ == "__main__":
    unittest.main()
