"""Camera identity and selection logic.

Pure functions only: no ffmpeg, no attached device. Enumeration itself is covered by the
camera-in-the-loop work deferred to Phase 2.
"""

from __future__ import annotations

from watchpost.camera import CameraDevice, camera_options, same_device

STREAMCAM = CameraDevice(index=0, name="Logitech StreamCam", uid="0x2140000046d0893")
BUILTIN = CameraDevice(index=1, name="MacBook Pro Camera", uid="uid-builtin")
IPHONE = CameraDevice(index=2, name="Vitaly's iPhone", uid=None)


class TestSameDevice:
    def test_uids_decide_when_both_sides_have_one(self) -> None:
        assert same_device("Anything", "uid-a", "Other name", "uid-a")
        assert not same_device("Same name", "uid-a", "Same name", "uid-b")

    def test_names_decide_when_a_uid_is_missing(self) -> None:
        # system_profiler does not report a UID for every device, notably Continuity
        # Camera, so name matching has to remain a valid fallback.
        assert same_device("Vitaly's iPhone", None, "Vitaly's iPhone", "uid-later")
        assert same_device("Vitaly's iPhone", "uid-later", "Vitaly's iPhone", None)
        assert not same_device("Vitaly's iPhone", None, "MacBook Pro Camera", None)

    def test_an_empty_identity_matches_nothing(self) -> None:
        assert not same_device(None, None, "Logitech StreamCam", "uid-a")
        assert not same_device(None, None, None, None)


class TestCameraOptions:
    def test_attached_devices_are_listed_and_marked_present(self) -> None:
        options = camera_options([STREAMCAM, BUILTIN], [], "Logitech StreamCam", STREAMCAM.uid)

        assert [o.name for o in options] == ["Logitech StreamCam", "MacBook Pro Camera"]
        assert all(o.present for o in options)
        assert [o.selected for o in options] == [True, False]

    def test_a_remembered_camera_survives_being_unplugged(self) -> None:
        """The bug this exists for: Continuity Camera leaves the device list with the
        phone, and listing only attached devices made it permanently unselectable."""
        options = camera_options(
            [STREAMCAM],
            [("Logitech StreamCam", STREAMCAM.uid), ("Vitaly's iPhone", None)],
            "Logitech StreamCam",
            STREAMCAM.uid,
        )

        by_name = {o.name: o for o in options}
        assert set(by_name) == {"Logitech StreamCam", "Vitaly's iPhone"}
        assert by_name["Logitech StreamCam"].present
        assert not by_name["Vitaly's iPhone"].present

    def test_an_attached_camera_is_not_duplicated_by_its_memory(self) -> None:
        options = camera_options([STREAMCAM], [("Logitech StreamCam", STREAMCAM.uid)], None, None)
        assert len(options) == 1
        assert options[0].present

    def test_memory_without_a_uid_still_matches_the_attached_device(self) -> None:
        # The iPhone is remembered by name alone; when it comes back ffmpeg may report it
        # with a UID. It must not appear twice.
        options = camera_options(
            [CameraDevice(index=0, name="Vitaly's iPhone", uid="uid-continuity")],
            [("Vitaly's iPhone", None)],
            None,
            None,
        )
        assert len(options) == 1
        assert options[0].present

    def test_the_selected_camera_is_present_even_if_unknown(self) -> None:
        """A config naming a camera this install has never enumerated — hand-edited, or
        restored from another machine — must still show as selected rather than letting
        the control silently display a different camera."""
        options = camera_options([STREAMCAM], [], "Some Old Webcam", "uid-gone")

        selected = [o for o in options if o.selected]
        assert len(selected) == 1
        assert selected[0].name == "Some Old Webcam"
        assert not selected[0].present

    def test_an_absent_selected_camera_is_marked_selected_once(self) -> None:
        options = camera_options(
            [STREAMCAM],
            [("Vitaly's iPhone", None)],
            "Vitaly's iPhone",
            None,
        )

        assert [o.selected for o in options] == [False, True]
        assert sum(o.selected for o in options) == 1

    def test_nothing_attached_and_nothing_configured_yields_an_empty_list(self) -> None:
        assert camera_options([], [], None, None) == []

    def test_absent_cameras_are_ordered_by_name_after_attached_ones(self) -> None:
        options = camera_options(
            [STREAMCAM],
            [("Zebra Cam", "uid-z"), ("Alpha Cam", "uid-a")],
            None,
            None,
        )
        assert [o.name for o in options] == ["Logitech StreamCam", "Alpha Cam", "Zebra Cam"]
