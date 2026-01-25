# Eve-Nexus-APP Reference Snippets

> Extracted from Eve-Nexus-APP before deprecation (Jan 2026).
> These patterns may be useful for future EVE_Sentinel enhancements.

---

## 1. ESI OAuth Flow (Python adaptation)

Original was React Native with Expo AuthSession. Key concepts for FastAPI:

```python
# ESI OAuth endpoints
ESI_AUTHORIZE_URL = "https://login.eveonline.com/v2/oauth/authorize"
ESI_TOKEN_URL = "https://login.eveonline.com/v2/oauth/token"

# Useful ESI scopes for recruitment vetting
ESI_SCOPES = [
    "esi-assets.read_assets.v1",           # See what they own
    "esi-characters.read_standings.v1",     # NPC/player standings
    "esi-markets.read_character_orders.v1", # Market activity
    "esi-location.read_location.v1",        # Current location
    "esi-skills.read_skills.v1",            # Skill verification
    "esi-wallet.read_character_wallet.v1",  # ISK/transactions
]

# JWT decoding to extract character_id from ESI token
def decode_esi_jwt(token: str) -> int:
    """Extract character_id from ESI access token."""
    import base64
    import json

    parts = token.split('.')
    # Add padding if needed
    payload = parts[1] + '=' * (4 - len(parts[1]) % 4)
    decoded = json.loads(base64.b64decode(payload))
    # Format: "CHARACTER:EVE:<character_id>"
    return int(decoded['sub'].split(':')[2])
```

---

## 2. ZKillboard Danger Rating System

```python
from enum import Enum
from dataclasses import dataclass

class DangerRating(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"

@dataclass
class SystemDanger:
    system_id: int
    kills_last_hour: int
    danger_rating: DangerRating
    recent_kills: list

def calculate_danger_rating(kills_last_hour: int) -> DangerRating:
    """Calculate danger rating based on kill activity."""
    if kills_last_hour > 20:
        return DangerRating.EXTREME
    elif kills_last_hour > 10:
        return DangerRating.HIGH
    elif kills_last_hour > 5:
        return DangerRating.MEDIUM
    return DangerRating.LOW

async def get_route_danger_assessment(
    zkill_client,
    system_ids: list[int]
) -> dict[int, SystemDanger]:
    """Assess danger for each system in a route."""
    import asyncio

    async def assess_system(system_id: int) -> tuple[int, SystemDanger]:
        kills = await zkill_client.get_system_kills(system_id, hours_back=1)
        kill_count = len(kills)
        return system_id, SystemDanger(
            system_id=system_id,
            kills_last_hour=kill_count,
            danger_rating=calculate_danger_rating(kill_count),
            recent_kills=kills[:10]
        )

    results = await asyncio.gather(*[assess_system(sid) for sid in system_ids])
    return dict(results)
```

---

## 3. Comprehensive Type Definitions

```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class Asset(BaseModel):
    """Character asset from ESI."""
    item_id: int
    location_id: int
    location_type: str
    type_id: int
    type_name: Optional[str] = None
    quantity: int
    location_flag: str
    is_singleton: bool

class MarketOrder(BaseModel):
    """Character market order."""
    order_id: int
    type_id: int
    type_name: Optional[str] = None
    location_id: int
    volume_total: int
    volume_remain: int
    min_volume: int
    price: float
    is_buy_order: bool
    duration: int
    issued: datetime
    range: str

class FitModule(BaseModel):
    """Module in a ship fit."""
    type_id: int
    type_name: str
    slot: str
    quantity: int

class ShipFit(BaseModel):
    """Complete ship fitting."""
    ship_type_id: int
    ship_name: str
    fit_name: str
    description: Optional[str] = None
    low_slots: list[FitModule] = []
    mid_slots: list[FitModule] = []
    high_slots: list[FitModule] = []
    rig_slots: list[FitModule] = []
    subsystems: list[FitModule] = []
    drones: list[FitModule] = []
    cargo: list[FitModule] = []

class SolarSystem(BaseModel):
    """EVE solar system data."""
    system_id: int
    system_name: str
    constellation_id: int
    region_id: int
    security_status: float
    stargates: list[int] = []
    stations: list[int] = []

class Skill(BaseModel):
    """Character skill."""
    skill_id: int
    skill_name: Optional[str] = None
    trained_skill_level: int
    active_skill_level: int
    skillpoints_in_skill: int

class CharacterSkills(BaseModel):
    """Character skill summary."""
    character_id: int
    skills: list[Skill]
    total_sp: int
```

---

## 4. Route Safety Analysis

```python
async def analyze_route_safety(
    system_ids: list[int],
    danger_map: dict[int, SystemDanger]
) -> str:
    """Generate human-readable route safety assessment."""
    extreme = sum(1 for d in danger_map.values() if d.danger_rating == DangerRating.EXTREME)
    high = sum(1 for d in danger_map.values() if d.danger_rating == DangerRating.HIGH)
    medium = sum(1 for d in danger_map.values() if d.danger_rating == DangerRating.MEDIUM)

    if extreme > 0:
        return f"HIGH RISK: {extreme} systems with extreme danger. Consider alternative route."
    elif high > 2:
        return f"MEDIUM RISK: {high} systems with high activity. Exercise caution."
    elif medium > 3:
        return f"LOW-MEDIUM RISK: {medium} systems with moderate activity."

    return "LOW RISK: Route appears relatively safe."

def generate_route_warnings(danger_map: dict[int, SystemDanger]) -> list[str]:
    """Generate specific warnings for dangerous systems."""
    warnings = []
    for system_id, data in danger_map.items():
        if data.danger_rating == DangerRating.EXTREME:
            warnings.append(
                f"System {system_id}: EXTREME danger - {data.kills_last_hour} kills/hour"
            )
        elif data.danger_rating == DangerRating.HIGH:
            warnings.append(
                f"System {system_id}: HIGH danger - {data.kills_last_hour} kills/hour"
            )
    return warnings
```

---

## 5. Asset Distribution Analysis

```python
def analyze_asset_distribution(assets: list[Asset]) -> dict:
    """Analyze where a character's assets are distributed."""
    from collections import Counter

    location_counts = Counter(a.location_id for a in assets)
    locations = location_counts.most_common()

    total_locations = len(locations)
    top_location, top_count = locations[0] if locations else (None, 0)

    if total_locations > 10:
        assessment = "SCATTERED"
        note = f"Assets spread across {total_locations} locations - potential logistics nightmare or multi-region trader"
    elif total_locations > 5:
        assessment = "DISTRIBUTED"
        note = f"Assets in {total_locations} locations - moderately spread"
    else:
        assessment = "CONSOLIDATED"
        note = f"Assets well-consolidated in {total_locations} locations"

    return {
        "assessment": assessment,
        "total_locations": total_locations,
        "top_location_id": top_location,
        "top_location_count": top_count,
        "note": note,
        "distribution": dict(locations[:10])  # Top 10 locations
    }
```

---

## 6. Jump Drive Calculations

```python
def calculate_jump_range(
    base_range_ly: float,
    jump_drive_calibration_level: int,
    jump_freighter_level: int = 0
) -> float:
    """
    Calculate actual jump range for capital ships.

    JDC adds 20% per level (5 levels = 100% bonus = 2x range)
    Jump Freighters skill adds 10% per level
    """
    jdc_bonus = 1 + (jump_drive_calibration_level * 0.20)
    jf_bonus = 1 + (jump_freighter_level * 0.10)
    return base_range_ly * jdc_bonus * jf_bonus

# Base ranges for common capitals
CAPITAL_BASE_RANGES = {
    "carrier": 6.5,      # LY
    "dreadnought": 6.5,
    "fax": 6.5,
    "supercarrier": 5.0,
    "titan": 5.0,
    "jump_freighter": 10.0,
    "black_ops": 8.0,
    "rorqual": 5.0,
}
```

---

## 7. Corporation Kill History

```python
async def get_corporation_kill_history(
    zkill_client,
    corporation_id: int,
    limit: int = 50
) -> dict:
    """
    Fetch and analyze corporation kill history.
    Useful for vetting applicant's current/previous corps.
    """
    kills = await zkill_client.get_corporation_kills(corporation_id, limit)

    if not kills:
        return {
            "kill_count": 0,
            "assessment": "NO DATA",
            "note": "No recent kills found - possibly inactive or PvE focused"
        }

    # Analyze patterns
    total_value = sum(k.get('zkb', {}).get('totalValue', 0) for k in kills)

    return {
        "kill_count": len(kills),
        "total_isk_destroyed": total_value,
        "avg_kill_value": total_value / len(kills) if kills else 0,
        "assessment": "ACTIVE" if len(kills) > 20 else "MODERATE" if len(kills) > 5 else "LOW",
        "note": f"Corp has {len(kills)} recent kills worth {total_value/1e9:.1f}B ISK"
    }
```

---

## Future Enhancement Ideas

1. **Authenticated Vetting**: Use ESI OAuth to get applicant's wallet/assets with permission
2. **Route Analysis**: Analyze where applicant typically operates based on killboard
3. **Corp Reputation**: Score corporations based on kill history and known affiliations
4. **Asset Verification**: Verify claimed assets/capitals with ESI data
5. **Skill Verification**: Confirm claimed skills match ESI data

---

*Archived from Eve-Nexus-APP - January 2026*
