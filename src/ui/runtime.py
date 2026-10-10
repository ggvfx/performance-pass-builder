"""
Shared Runtime Objects.

Ported from minicut-shot-detector (6dcbd60).

The toolchain and the environment checker, built once for the life of the
process and used by every router.

They live here rather than in `server.py` because the routers would otherwise
import the app module to reach them, and the app module imports the routers —
which is a circular import waiting to happen the first time anyone adds a
route. One small module that imports nothing of ours breaks the cycle before
it exists.

Shared because both are expensive to make and safe to reuse: ffmpeg is
discovered once rather than per request, and the environment report is cached
between panel refreshes.
"""

from src.core.environment import EnvironmentChecker
from src.core.ffmpeg_tools import MediaToolchain

toolchain = MediaToolchain()
checker = EnvironmentChecker(toolchain)
