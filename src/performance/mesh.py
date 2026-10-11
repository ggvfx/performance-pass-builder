"""
Rendering the Face Mesh.

Written for this project. minicut drew nothing.

**The mesh is its own picture with transparency, not a drawing on top of
depth.** That one decision is what lets it be output alone, sit over any
other layer, be reordered, or be left out of a composite entirely — all
without re-tracking anything. A mesh burned into depth would make every one
of those a new render.

**All faces go into one layer**, not one layer each. A three-person shot
should not fill the stack with three near-identical rows, and which faces
are visible belongs on the Faces step beside the faces, not in the
compositor.

Notes:
    **Straight alpha, which anti-aliasing does not give for free.** OpenCV
    blends an anti-aliased edge toward the existing pixel across all four
    channels, so a half-covered pixel comes out with half colour *and* half
    alpha — premultiplied. The compositor expects straight, so the colour is
    divided back out at the end. See `_unpremultiply`.

    OpenCV draws. It never opens or writes a video file; `FrameWriter` does
    that, as it does for everything else.
"""

import logging

import cv2
import numpy as np

from src.core import config
from src.core.models import LANDMARK_COUNT, FaceTrack
from src.media.frames import RGBA

# Alpha is the fourth channel of an RGBA frame.
ALPHA = 3

# Drawn in this order, so the features sit on top of the surface they belong
# to rather than being lost in 2,556 tessellation edges.
FEATURE_SETS = (
    "FACE_LANDMARKS_TESSELATION",
    "FACE_LANDMARKS_FACE_OVAL",
    "FACE_LANDMARKS_LEFT_EYEBROW",
    "FACE_LANDMARKS_RIGHT_EYEBROW",
    "FACE_LANDMARKS_LEFT_EYE",
    "FACE_LANDMARKS_RIGHT_EYE",
    "FACE_LANDMARKS_LIPS",
    "FACE_LANDMARKS_LEFT_IRIS",
    "FACE_LANDMARKS_RIGHT_IRIS",
)


def connections() -> list[tuple[str, tuple, tuple[int, int, int], float]]:
    """
    Which edges to draw, in what colour, at what width.

    Returns:
        (name, edges, colour, width as a fraction of picture height) per set,
        in drawing order.

    Notes:
        Imported here rather than at module scope for the same reason the
        tracker does it: there is no MediaPipe wheel for Intel macOS, and
        the dependency panel should get the chance to say so.
    """
    from mediapipe.tasks.python.vision import FaceLandmarksConnections as sets

    surface = (config.MESH_TESSELATION_COLOUR, config.MESH_TESSELATION_WIDTH)
    eyes = (config.MESH_EYES_COLOUR, config.MESH_FEATURE_WIDTH)
    lips = (config.MESH_LIPS_COLOUR, config.MESH_FEATURE_WIDTH)
    iris = (config.MESH_IRIS_COLOUR, config.MESH_FEATURE_WIDTH)

    styles = {
        "FACE_LANDMARKS_TESSELATION": surface,
        "FACE_LANDMARKS_FACE_OVAL": surface,
        "FACE_LANDMARKS_LEFT_EYEBROW": eyes,
        "FACE_LANDMARKS_RIGHT_EYEBROW": eyes,
        "FACE_LANDMARKS_LEFT_EYE": eyes,
        "FACE_LANDMARKS_RIGHT_EYE": eyes,
        "FACE_LANDMARKS_LIPS": lips,
        "FACE_LANDMARKS_LEFT_IRIS": iris,
        "FACE_LANDMARKS_RIGHT_IRIS": iris,
    }

    return [
        (name, getattr(sets, name), *styles[name])
        for name in FEATURE_SETS
        if hasattr(sets, name)
    ]


def line_width(fraction: float, height: int) -> int:
    """
    A width in pixels, never less than one.

    Notes:
        Scaled by height rather than width, because height is what changes
        between a 16:9 master and a vertical phone clip of the same
        resolution class. A zero would make OpenCV draw nothing at all,
        silently, on a small proxy.
    """
    return max(1, round(fraction * height))


def empty_layer(width: int, height: int) -> np.ndarray:
    """
    A fully transparent RGBA frame.

    Notes:
        Transparent *black*, not transparent white. With straight alpha the
        colour under a zero alpha should never reach a composite — but if a
        bug ever lets it through, black is the one that looks like an error
        rather than like a blown highlight.
    """
    return np.zeros((height, width, RGBA.channels), dtype=np.uint8)


def draw_face(canvas: np.ndarray, points: np.ndarray) -> None:
    """
    Draws one face's mesh onto an RGBA canvas, in place.

    Args:
        canvas: (height, width, 4) uint8, modified.
        points: (LANDMARK_COUNT, 3) as fractions of the picture.

    Raises:
        ValueError: The points are the wrong shape.

    Notes:
        Leaves the canvas premultiplied. `render_frame` divides the colour
        back out once, after every face is drawn, rather than per face —
        doing it per face would compound the rounding where two faces
        overlap.
    """
    if points.shape != (LANDMARK_COUNT, 3):
        raise ValueError(f"expected ({LANDMARK_COUNT}, 3) landmarks, got {points.shape}")

    height, width = canvas.shape[:2]

    # Fractions to pixels once, for every landmark, rather than per edge.
    pixels = np.empty((LANDMARK_COUNT, 2), dtype=np.int32)
    pixels[:, 0] = np.clip(points[:, 0] * width, 0, width - 1)
    pixels[:, 1] = np.clip(points[:, 1] * height, 0, height - 1)

    for _name, edges, colour, fraction in connections():
        thickness = line_width(fraction, height)
        stroke = (*colour, 255)

        for edge in edges:
            cv2.line(
                canvas,
                tuple(pixels[edge.start]),
                tuple(pixels[edge.end]),
                stroke,
                thickness,
                cv2.LINE_AA,
            )


def render_frame(
    tracks: list[FaceTrack],
    frame: int,
    width: int,
    height: int,
    visible: set[str] | None = None,
) -> np.ndarray:
    """
    Every visible face's mesh for one frame, as a transparent RGBA picture.

    Args:
        tracks: One per face. All drawn into the same layer.
        frame: Which frame to render.
        width: Picture width in pixels.
        height: Picture height.
        visible: Labels to draw. None draws them all.

    Returns:
        (height, width, 4) uint8 with straight alpha. Fully transparent
        where no face was found — which is correct, not a failure.

    Raises:
        IndexError: The frame is outside one of the tracks.

    Notes:
        A face with a gap on this frame contributes nothing, and the layer
        is simply empty there. Nothing is interpolated and nothing is held
        over from the previous frame: a mesh drawn where a face was last
        seen is a mesh in the wrong place.
    """
    canvas = empty_layer(width, height)

    for track in tracks:
        if visible is not None and track.label not in visible:
            continue

        points = track.landmarks_on(frame)
        if points is not None:
            draw_face(canvas, points)

    return _unpremultiply(canvas)


def render_layer(
    tracks: list[FaceTrack],
    width: int,
    height: int,
    visible: set[str] | None = None,
):
    """
    Every frame of the mesh layer, in order.

    Yields:
        One RGBA frame per frame of the track.

    Raises:
        ValueError: The tracks are not all the same length.

    Notes:
        A generator, so a `FrameWriter` can consume it a frame at a time.
        Holding a whole 1080p RGBA layer would be 8 MB a frame, and nothing
        needs more than one at once.
    """
    if not tracks:
        raise ValueError("a mesh layer needs at least one track")

    lengths = {track.frame_count for track in tracks}
    if len(lengths) != 1:
        raise ValueError(
            f"tracks disagree about the length of the source: {sorted(lengths)}. "
            f"Every pass is exactly as long as what it came from."
        )

    frame_count = lengths.pop()
    logging.info(
        f"Rendering a mesh layer: {frame_count} frames, "
        f"{len(visible) if visible is not None else len(tracks)} of {len(tracks)} face(s)"
    )

    for frame in range(frame_count):
        yield render_frame(tracks, frame, width, height, visible)


# --- ALPHA ---


def _unpremultiply(canvas: np.ndarray) -> np.ndarray:
    """
    Recovers straight alpha from what anti-aliased drawing leaves behind.

    Notes:
        Drawing a full-strength colour at half coverage gives OpenCV's
        anti-aliasing half the colour and half the alpha. That is
        premultiplied, and the compositor works in straight alpha — `fg·α +
        bg·(1−α)` — so feeding it premultiplied edges would darken every
        line against whatever is underneath.

        Dividing the colour back out restores the full-strength colour and
        leaves the alpha alone, which is exactly the straight form. Where
        alpha is zero there is nothing to recover and the pixel stays black.
    """
    alpha = canvas[:, :, ALPHA].astype(np.float32) / 255.0
    lit = alpha > 0

    if not lit.any():
        return canvas

    colour = canvas[:, :, :ALPHA].astype(np.float32)
    colour[lit] = np.clip(colour[lit] / alpha[lit, None], 0, 255)

    canvas[:, :, :ALPHA] = colour.astype(np.uint8)
    return canvas
