from __future__ import annotations

import unittest

from xiexie_usage_overlay.pet_window import (
    WS_EX_LAYERED,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_EX_TRANSPARENT,
    Rect,
    WindowInfo,
    calculate_follow_position,
    pet_candidate_score,
)


class PetWindowDetectionTests(unittest.TestCase):
    def test_real_pet_window_shape_scores(self) -> None:
        pet = WindowInfo(
            handle=1,
            rect=Rect(2138, 992, 2850, 1632),
            visible=True,
            cloaked=False,
            title="ChatGPT",
            class_name="Chrome_WidgetWin_1",
            process_name="ChatGPT.exe",
            style=0x14000000,
            ex_style=WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_TRANSPARENT,
        )
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


class FollowPositionTests(unittest.TestCase):
    def test_tail_aligns_to_measured_pet_anchor(self) -> None:
        target, base = calculate_follow_position(
            pet_rect=Rect(2138, 992, 2850, 1632),
            overlay_width=760,
            overlay_height=354,
            tail_offset_x=578,
            work_area=Rect(0, 0, 3072, 1728),
        )
        self.assertEqual(target, base)
        self.assertAlmostEqual(target[0] + 578, 2668, delta=2)
        self.assertAlmostEqual(target[1] + 354, 1376, delta=2)

    def test_position_is_clamped_to_monitor(self) -> None:
        target, _base = calculate_follow_position(
            pet_rect=Rect(-100, -100, 400, 500),
            overlay_width=760,
            overlay_height=354,
            tail_offset_x=578,
            work_area=Rect(0, 0, 1920, 1040),
            offset_x=-999,
            offset_y=-999,
        )
        self.assertEqual(target, (0, 0))


if __name__ == "__main__":
    unittest.main()

