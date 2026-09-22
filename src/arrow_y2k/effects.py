"""Independent visual timelines; gameplay commits immediately in GameRun."""
from dataclasses import dataclass
import math
from .model import Arrow, MoveResult
from .pixels import Animation

EXIT_SECONDS = .65
COLLISION_SECONDS = .95
HEART_SECONDS = .70
IMPACT_DELAY = COLLISION_SECONDS * .30


@dataclass
class ArrowMotion:
    arrow: Arrow
    kind: str
    duration: float
    collision_distance: int | None = None
    elapsed: float = 0.0

    @property
    def frame(self):
        return Animation(self.arrow, self.kind, min(1.0, self.elapsed / self.duration), self.collision_distance)


class GameplayEffects:
    """Compose independent arrows and damaged hearts, advanced by active play time."""
    def __init__(self):
        self.motions: dict[str, ArrowMotion] = {}
        self.hearts: dict[int, float] = {}

    def clear(self):
        self.motions.clear()
        self.hearts.clear()

    def busy(self, arrow_id):
        return arrow_id in self.motions

    @property
    def active(self):
        return bool(self.motions or self.hearts)

    @property
    def animations(self):
        return tuple(motion.frame for motion in self.motions.values())

    @property
    def heart_frames(self):
        return {index: elapsed / HEART_SECONDS for index, elapsed in self.hearts.items()}

    @property
    def remaining_seconds(self):
        return max([0.0, *(motion.duration - motion.elapsed for motion in self.motions.values()),
                    *(HEART_SECONDS - elapsed for elapsed in self.hearts.values())])

    def start(self, result: MoveResult):
        if result.kind not in ("escaped", "collision") or result.arrow is None:
            raise ValueError("Only committed arrow moves have an animation")
        collision = result.kind == "collision"
        self.motions[result.arrow.id] = ArrowMotion(result.arrow, "collision" if collision else "exit",
            COLLISION_SECONDS if collision else EXIT_SECONDS,
            result.collision.distance if collision else None)
        if collision:
            self.hearts[result.lives] = -IMPACT_DELAY

    def advance(self, seconds):
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Visual time must be finite and nonnegative")
        collided = set()
        for arrow_id, motion in tuple(self.motions.items()):
            motion.elapsed += seconds
            if motion.elapsed >= motion.duration:
                if motion.kind == "collision":
                    collided.add(arrow_id)
                del self.motions[arrow_id]
        for index in tuple(self.hearts):
            self.hearts[index] += seconds
            if self.hearts[index] >= HEART_SECONDS:
                del self.hearts[index]
        return collided
