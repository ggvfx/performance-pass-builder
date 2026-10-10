"""
The Layer Stack.

Combines whichever layers are switched on, in the order the artist put them,
and writes the result.

**This module knows nothing about what made a layer.** It takes pictures and
an order; it has never heard of depth, faces or segmentation. That is the
whole point of the structure: a new pass is a module in `performance/` that
produces a layer, and it does not touch this file. `composite/` may not
import `performance/`.

Index 0 is the bottom. Each layer is composited over the one below with the
"over" operator and nothing else — no opacity, no blend modes, no masks. They
fit this shape without changing it and have nothing to drive them yet.

Alpha is **straight**, not premultiplied:

    out = fg·α + bg·(1 − α)

Premultiplied would be one multiply rather than two, and is what antialiased
drawing on black naturally produces. It is rejected because PNG and QuickTime
RLE conventionally carry straight alpha, and premultiplied data in a file
claiming to be straight puts dark fringes on every edge in a compositor that
believes the label.
"""

from pathlib import Path

import numpy as np

from src.core.config import GREY_CARD_LEVEL
from src.core.models import LayerSource, LayerStack
from src.media.frames import FrameReader, FrameWriter

# --- SOURCES THAT ARE NOT FILES ---

# A flat card has no file and never will: it is one number. Synthesising it
# per frame costs nothing and saves writing a few thousand identical frames to
# disk for a layer that is, definitionally, constant.
CONSTANT_LEVELS = {
    LayerSource.GREY: GREY_CARD_LEVEL,
    LayerSource.BLACK: 0.0,
}


def constant_frame(source: LayerSource, width: int, height: int) -> np.ndarray:
    """
    The picture for a layer that is a single value rather than a file.

    Raises:
        KeyError: The source is not a constant. A caller asking for a file
            source here has confused the two, which is worth a loud failure.
    """
    level = CONSTANT_LEVELS[source]
    value = round(level * 255)
    return np.full((height, width, 3), value, dtype=np.uint8)


# --- COMPOSITING ---


def over(foreground: np.ndarray, background: np.ndarray) -> np.ndarray:
    """
    One RGBA layer over one RGB layer, with straight alpha.

    Args:
        foreground: (h, w, 4) uint8. Its alpha decides what shows through.
        background: (h, w, 3) uint8, opaque.

    Returns:
        (h, w, 3) uint8.

    Notes:
        The arithmetic runs in float32 and comes back to uint8 once. Doing it
        in uint8 throughout would round at every layer, and the rounding
        compounds — three layers of a faint mesh would visibly darken.

        An RGB foreground has nothing to composite: it is opaque, so it
        replaces what is beneath it. `composite_frame` short-circuits that
        rather than building a full alpha channel to multiply by one.
    """
    alpha = foreground[:, :, 3:4].astype(np.float32) / 255.0
    colour = foreground[:, :, :3].astype(np.float32)

    blended = colour * alpha + background.astype(np.float32) * (1.0 - alpha)
    return np.clip(blended, 0, 255).astype(np.uint8)


def composite_frame(layers: list[np.ndarray]) -> np.ndarray:
    """
    One frame from each enabled layer, bottom first, into one picture.

    Args:
        layers: Bottom first. Each is (h, w, 3) or (h, w, 4) uint8.

    Returns:
        (h, w, 3) uint8.

    Raises:
        ValueError: No layers, or they disagree about their size.

    Notes:
        An opaque layer replaces everything beneath it rather than being
        blended over it. That is not an optimisation — it is what "opaque"
        means — and it is why a stack with depth above the plate shows no
        plate at all, which is the correct and sometimes surprising answer.
    """
    if not layers:
        raise ValueError("a composite needs at least one layer")

    shapes = {layer.shape[:2] for layer in layers}
    if len(shapes) != 1:
        raise ValueError(f"layers disagree about their size: {sorted(shapes)}")

    result = None
    for layer in layers:
        if layer.shape[2] == 3:
            result = layer
            continue

        if result is None:
            # The bottom layer has alpha and nothing to show through to.
            # Black is what an h264 output would give it anyway, so make
            # that explicit rather than letting the encoder decide.
            result = np.zeros((*layer.shape[:2], 3), dtype=np.uint8)

        result = over(layer, result)

    return result


# --- THE STACK OVER A WHOLE CLIP ---


class Compositor:
    """
    Reads every enabled layer frame by frame and writes the stack.

    Notes:
        One frame per layer is held at a time, which is about 8 MB each at
        1080p. Nothing loads a whole layer.
    """

    def __init__(self, stack: LayerStack, sources: dict[LayerSource, Path]):
        """
        Args:
            stack: What to composite, and in what order.
            sources: Where each file-backed layer lives. Constants — the grey
                card and black — are not expected here and are synthesised.

        Raises:
            ValueError: An enabled layer has neither a file nor a constant.
        """
        self.stack = stack
        self.sources = sources

        missing = [
            source
            for source in stack.enabled_sources
            if source not in sources and source not in CONSTANT_LEVELS
        ]
        if missing:
            names = ", ".join(source.value for source in missing)
            raise ValueError(f"no picture for enabled layer(s): {names}")

    def run(
        self,
        readers: dict[LayerSource, FrameReader],
        writer: FrameWriter,
        frame_count: int,
        width: int,
        height: int,
    ) -> int:
        """
        Composites every frame and writes it.

        Args:
            readers: An open reader per file-backed enabled layer.
            writer: An open writer.
            frame_count: How many frames the SOURCE has. The stack is never
                asked how long it is.
            width: Picture width, for the constant layers.
            height: Picture height, for the constant layers.

        Returns:
            Frames written, for the caller to check against the source.

        Raises:
            RuntimeError: A layer ran out before the source did.

        Notes:
            Non-negotiable 2 lives here as much as in the validator: the
            length comes from the source, never from whichever layer is
            shortest, and a layer ending early stops the job rather than
            quietly shortening the output.
        """
        enabled = self.stack.enabled_sources

        for index in range(frame_count):
            frames = []

            for source in enabled:
                if source in CONSTANT_LEVELS:
                    frames.append(constant_frame(source, width, height))
                    continue

                frame = readers[source].read()
                if frame is None:
                    raise RuntimeError(
                        f"the {source.value} layer ran out at frame {index}, but the "
                        f"source has {frame_count} frames. Nothing is trimmed to fit."
                    )
                frames.append(frame)

            writer.write(composite_frame(frames))

        return frame_count

    def __repr__(self) -> str:
        enabled = " over ".join(source.value for source in self.stack.enabled_sources)
        return f"Compositor({enabled or 'nothing enabled'})"
