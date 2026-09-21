"""Named connected map masks, shared by campaigns and the map studio."""
from dataclasses import dataclass
from functools import lru_cache

from .generation import template_mask
from .model import Cell


@dataclass(frozen=True)
class MapTemplate:
    id: str
    name: str
    difficulty: str
    mask: frozenset[Cell]


@lru_cache(maxsize=1)
def preset_maps() -> tuple[MapTemplate, ...]:
    specs = (
        ("easy-square", "初见方庭", "easy", "square", 6, 6),
        ("easy-rectangle", "曲折长廊", "easy", "rectangle", 9, 6),
        ("easy-heart", "心有回环", "easy", "heart", 9, 8),
        ("medium-square", "方寸之间", "medium", "square", 10, 10),
        ("medium-rectangle", "回声长廊", "medium", "rectangle", 12, 10),
        ("medium-heart", "双瓣花园", "medium", "heart", 14, 12),
        ("medium-diamond", "菱光浮岛", "medium", "diamond", 16, 12),
        ("medium-ring", "回环庭院", "medium", "ring", 14, 12),
        ("medium-cross", "十字路口", "medium", "cross", 16, 12),
        ("hard-square", "巨型方阵", "hard", "square", 15, 15),
        ("hard-rectangle", "无声迷宫", "hard", "rectangle", 18, 12),
        ("hard-heart", "重重心墙", "hard", "heart", 20, 16),
        ("hard-diamond", "钻石之境", "hard", "diamond", 20, 16),
        ("hard-ring", "环形要塞", "hard", "ring", 20, 16),
        ("hard-cross", "交错中枢", "hard", "cross", 20, 16),
    )
    return tuple(MapTemplate(key, title, difficulty, template_mask(shape, width, height))
                 for key, title, difficulty, shape, width, height in specs)


def maps_for(difficulty: str) -> tuple[MapTemplate, ...]:
    result = tuple(item for item in preset_maps() if item.difficulty == difficulty)
    if not result:
        raise ValueError(f"Unknown map difficulty: {difficulty}")
    return result
